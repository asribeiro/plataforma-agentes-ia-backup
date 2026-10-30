"""Tools clinicas do agente: procedimento, quem atende e horario POR profissional.

Card F1-04. O que existia antes: um unico tool (`get_available_slots`) que
recebia `professional` como texto e **ignorava** o argumento, e um
`slots_service` que respondia "a primeira agenda ativa da empresa". Dava para o
agente dizer o horario da Dra. Ana para quem pediu o Dr. Bruno, e nao havia como
o agente falar de procedimento nem de preco.

A ordem que o prompt passa a seguir (spec do Anderson, 28/10):
    procedimento -> quem atende -> escolher o profissional -> horario daquele
    -> verificar a janela antes de convidar

REGRA DE OURO (requisito do dono): antes de mandar convite, a janela tem de
estar livre de verdade. Quatro checagens, na ordem do mais barato ao mais caro:

  1. o INTERVALO [inicio, inicio+duracao) cabe num turno da agenda daquele
     profissional — nao basta o horario de inicio existir; procedimento de 90
     min nao cabe num vao de 30;
  2. o slot esta publicado em `company_slots` para aquela data (quando a tabela
     tem linhas para o dia; sem linhas, vale o turno);
  3. nenhum agendamento ATIVO da mesma agenda colide (status NOT LIKE
     'CANCELLED%');
  4. `freebusy` do Google sem evento no intervalo, quando a agenda tem
     credencial.

A corrida entre duas conversas no mesmo horario nao e resolvida aqui: quem
garante a verdade e o indice unico `uq_agendamento_agenda_slot` da migration
0008. Isto aqui e a verificacao da BOA EXPERIENCIA — nao convidar para um
horario que ja se sabe ocupado.

DURACAO EFETIVA: override do profissional > duracao do procedimento > slot da
agenda > 30 min. Slot padrao de 30 nao serve para procedimento de 90.
"""
import logging
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.models import (
    Agenda,
    AgendaSchedule,
    Agendamento,
    Professional,
    ProfessionalService,
    Service,
)

logger = logging.getLogger(__name__)

DURACAO_PADRAO_MIN = 30
STATUS_CANCELADO = "CANCELLED"

# Faixas usadas pelos filtros do agente ("manha", "tarde", "noite").
PERIODOS = {
    "manha": (time(0, 0), time(12, 0)),
    "tarde": (time(12, 0), time(18, 0)),
    "noite": (time(18, 0), time(23, 59)),
}


# ---------------------------------------------------------------------------
# Duracao
# ---------------------------------------------------------------------------
def duracao_efetiva_minutos(
    db: Session,
    company_id: int,
    professional_id: Optional[int],
    service_id: Optional[int],
) -> int:
    """Quanto tempo a vaga precisa ter, na ordem: override > procedimento > agenda.

    Um procedimento de 90 min num slot de 30 min nao cabe — e o sistema antigo
    nao tinha como saber disso porque so conhecia o slot da agenda.
    """
    if professional_id and service_id:
        override = (
            db.query(ProfessionalService.duration_override_minutes)
            .filter(
                ProfessionalService.professional_id == professional_id,
                ProfessionalService.service_id == service_id,
            )
            .scalar()
        )
        if override:
            return int(override)

    if service_id:
        duracao_servico = (
            db.query(Service.duration_minutes)
            .filter(Service.id == service_id, Service.company_id == company_id)
            .scalar()
        )
        if duracao_servico:
            return int(duracao_servico)

    agenda = agenda_ativa_do_profissional(db, company_id, professional_id)
    if agenda and agenda.slot_duration:
        return int(agenda.slot_duration)

    return DURACAO_PADRAO_MIN


# ---------------------------------------------------------------------------
# Catalogo
# ---------------------------------------------------------------------------
def buscar_procedimentos(
    db: Session,
    company_id: int,
    termo: Optional[str] = None,
    incluir_inativos: bool = False,
    limite: int = 20,
) -> List[Dict[str, Any]]:
    """Procedimentos da clinica, com preco em reais e marcacao de avaliacao.

    `price_cents` None significa "sem preco": o agente NAO deve citar valor
    nenhum nesse caso — combinado com o dono (procedimento sem preco existe para
    a clinica que prefere falar valor so na avaliacao).
    """
    q = db.query(Service).filter(Service.company_id == company_id)
    if not incluir_inativos:
        q = q.filter(Service.active.is_(True))
    if termo:
        # busca por trecho, sem diferenciar maiuscula: "clareamento" acha
        # "Clareamento Dental"
        q = q.filter(Service.name.ilike(f"%{termo.strip()}%"))

    saida = []
    for s in q.order_by(Service.name.asc()).limit(limite).all():
        saida.append(
            {
                "service_id": s.id,
                "nome": s.name,
                "duracao_minutos": s.duration_minutes,
                "preco_reais": (s.price_cents / 100.0) if s.price_cents is not None else None,
                "citavel": s.price_cents is not None,
                "avaliacao": bool(s.is_evaluation),
                "ativo": bool(s.active),
            }
        )
    return saida


def profissionais_que_atendem(
    db: Session, company_id: int, service_id: int
) -> List[Dict[str, Any]]:
    """Quem, da clinica, esta habilitado a fazer aquele procedimento.

    So ativos e so quem tem o vinculo em `professional_services`. Precisa ser
    com vinculo, nao "todos os profissionais": o agente nao pode oferecer o Dr.
    Bruno para um procedimento que ele nao faz.
    """
    linhas = (
        db.query(Professional, ProfessionalService.duration_override_minutes)
        .join(
            ProfessionalService,
            ProfessionalService.professional_id == Professional.id,
        )
        .filter(
            Professional.company_id == company_id,
            Professional.active.is_(True),
            ProfessionalService.service_id == service_id,
        )
        .order_by(Professional.name.asc())
        .all()
    )
    return [
        {
            "professional_id": prof.id,
            "nome": prof.name,
            "duracao_override_minutos": override,
        }
        for prof, override in linhas
    ]


def _profissionais_com_agenda(db: Session, company_id: int) -> List[Dict[str, Any]]:
    """Profissionais ativos que tem agenda ativa — usado quando o modelo nao passa id.

    Existe para a tool nunca responder "erro de parametro" por um id que so o banco sabe.
    """
    from backend.models import Agenda, Professional

    linhas = (
        db.query(Professional)
        .join(Agenda, Agenda.professional_id == Professional.id)
        .filter(
            Professional.company_id == company_id,
            Professional.active.is_(True),
            Agenda.active.is_(True),
        )
        .order_by(Professional.name.asc())
        .all()
    )
    unicos = {}
    for prof in linhas:
        unicos[prof.id] = {"professional_id": prof.id, "nome": prof.name}
    return list(unicos.values())


def _normalizar_nome(texto: str) -> str:
    """Minusculo, sem pontuacao e com espaco simples.

    O paciente fala "dra ana"; o cadastro diz "Dra. Ana". Comparar cru nunca
    casaria por causa do ponto — e o agente concluiria que o profissional nao
    existe.
    """
    limpo = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in (texto or "").lower())
    return " ".join(limpo.split())


def resolver_profissional_por_nome(
    db: Session, company_id: int, nome: Optional[str]
) -> Optional[Professional]:
    """Acha o profissional pelo que o paciente falou ("dra ana", "bruno").

    Casamento por trecho, sem caixa e sem pontuacao, e so entre ATIVOS da
    empresa — nome de profissional de outra clinica nunca resolve.
    """
    if not nome or not nome.strip():
        return None
    trecho = _normalizar_nome(nome)
    # A comparacao acontece em Python, nao no SQL: o cadastro tem pontuacao
    # ("Dra. Ana") e o paciente nao ("dra ana"), e `ilike '%dra ana%'` nunca
    # casaria. Uma clinica tem dezenas de profissionais, nao milhares — trazer
    # os ativos da empresa e filtrar aqui custa nada e acerta.
    ativos = (
        db.query(Professional)
        .filter(
            Professional.company_id == company_id,
            Professional.active.is_(True),
        )
        .all()
    )
    candidatos = [p for p in ativos if trecho in _normalizar_nome(p.name)]
    if len(candidatos) == 1:
        return candidatos[0]
    # "ana" pode casar com "Dra. Ana" e "Dra. Ana Paula": tenta pela palavra
    # inteira antes de desistir, e desiste se continuar ambiguo.
    palavras = trecho.split()
    por_palavra = [
        cand
        for cand in ativos
        if all(p in _normalizar_nome(cand.name).split() for p in palavras)
    ]
    if len(por_palavra) == 1:
        return por_palavra[0]
    return None


# ---------------------------------------------------------------------------
# Agenda e turnos
# ---------------------------------------------------------------------------
def agenda_ativa_do_profissional(
    db: Session, company_id: int, professional_id: Optional[int]
) -> Optional[Agenda]:
    if not professional_id:
        return None
    return (
        db.query(Agenda)
        .filter(
            Agenda.company_id == company_id,
            Agenda.professional_id == professional_id,
            Agenda.active.is_(True),
        )
        .first()
    )


def turnos_do_dia(agenda: Agenda, dia_semana: int) -> List[Tuple[time, time]]:
    """Janelas de atendimento daquele dia da semana (0=segunda)."""
    turnos: List[Tuple[time, time]] = []
    for sched in agenda.schedules or []:
        if sched.day_of_week != dia_semana:
            continue
        for inicio, fim in (
            (sched.morning_start, sched.morning_end),
            (sched.afternoon_start, sched.afternoon_end),
            (sched.night_start, sched.night_end),
        ):
            if inicio and fim and inicio < fim:
                turnos.append((inicio, fim))
    return sorted(turnos)


def _intervalo_cabe(inicio: datetime, duracao_min: int, turnos: List[Tuple[time, time]]) -> bool:
    fim = inicio + timedelta(minutes=duracao_min)
    if fim.date() != inicio.date():
        return False
    for abre, fecha in turnos:
        if inicio.time() >= abre and fim.time() <= fecha:
            return True
    return False


def _conflito_agendamento(
    db: Session, agenda: Agenda, inicio: datetime, duracao_min: int
) -> Optional[Agendamento]:
    """Agendamento ativo que se sobrepoe ao intervalo [inicio, inicio+duracao).

    `Agendamento` nao guarda a duracao: usa o slot da agenda como tamanho do
    compromisso existente. Sem isso, um paciente as 15:00 e outro as 15:15 com
    slot de 30 min passariam os dois.
    """
    fim = inicio + timedelta(minutes=duracao_min)
    slot = timedelta(minutes=int(agenda.slot_duration or DURACAO_PADRAO_MIN))
    existentes = (
        db.query(Agendamento)
        .filter(
            Agendamento.agenda_id == agenda.id,
            Agendamento.consulta_data.isnot(None),
            Agendamento.consulta_data < fim,
            Agendamento.consulta_data > inicio - slot,
            or_(
                Agendamento.status.is_(None),
                ~Agendamento.status.like(f"{STATUS_CANCELADO}%"),
            ),
        )
        .all()
    )
    for ag in existentes:
        # a query ja limita a janela; aqui confirma a sobreposicao real
        if ag.consulta_data < fim and ag.consulta_data + slot > inicio:
            return ag
    return None


def _slot_publicado(
    db: Session, company_id: int, inicio: datetime
) -> Optional[bool]:
    """O horario esta publicado em company_slots?

    Devolve None quando a tabela nao tem linha nenhuma para o dia — nesse caso a
    ausencia de linha nao significa indisponivel, e sim que aquele dia nunca foi
    publicado (clinica que nao usa a tabela). Tratar ausencia como "ocupado"
    faria o agente dizer que nao ha horario nenhum.
    """
    from backend.agents_sdk.database.models import CompanySlot

    dia = inicio.date()
    tem_linhas_no_dia = (
        db.query(CompanySlot.id)
        .filter(CompanySlot.company_id == company_id, CompanySlot.slot_date == dia)
        .first()
    )
    if not tem_linhas_no_dia:
        return None
    linha = (
        db.query(CompanySlot)
        .filter(
            CompanySlot.company_id == company_id,
            CompanySlot.slot_date == dia,
            CompanySlot.slot_time == inicio.time().replace(microsecond=0),
        )
        .first()
    )
    if not linha:
        return False
    return bool(linha.is_available)


def _google_ocupado(
    db: Session, company_id: int, agenda: Agenda, inicio: datetime, duracao_min: int
) -> Optional[bool]:
    """freebusy do Google cobre o intervalo?

    None = nao verificado (sem credencial ou falha na chamada). Falha de rede nao
    pode virar "esta livre": quem decide convidar precisa saber que esse teste
    nao rodou.
    """
    if not getattr(agenda, "google_calendar_id", None):
        return None
    try:
        from backend.agents_sdk.tools.slots_service import SlotsService

        intervalos = SlotsService(db)._fetch_google_busy_intervals(
            company_id, agenda, inicio.date(), inicio.date()
        )
    except Exception as exc:  # noqa: BLE001 - falha externa nao bloqueia, mas e declarada
        logger.warning("freebusy indisponivel na agenda %s: %s", agenda.id, exc)
        return None

    fim = inicio + timedelta(minutes=duracao_min)
    for intervalo in intervalos or []:
        ini_ocup = intervalo.get("start")
        fim_ocup = intervalo.get("end")
        if ini_ocup and fim_ocup and ini_ocup < fim and fim_ocup > inicio:
            return True
    return False


def verificar_janela_livre(
    db: Session,
    company_id: int,
    professional_id: int,
    inicio: datetime,
    duracao_min: int,
) -> Dict[str, Any]:
    """As quatro checagens da REGRA DE OURO, na ordem do mais barato ao mais caro.

    Devolve {"livre": bool, "motivo": str, "detalhe": str}. `motivo` e curto e
    estavel (o agente usa para decidir o que dizer); `detalhe` e a frase pronta
    para o paciente.
    """
    agenda = agenda_ativa_do_profissional(db, company_id, professional_id)
    if not agenda:
        return {
            "livre": False,
            "motivo": "sem_agenda",
            "detalhe": "Este profissional ainda não tem agenda ativa configurada.",
        }

    margem = int(agenda.safety_margin_minutes or 0)
    if inicio < datetime.now(inicio.tzinfo) + timedelta(minutes=margem):
        return {
            "livre": False,
            "motivo": "dentro_da_margem",
            "detalhe": (
                f"A clínica precisa de {margem} min de antecedência para confirmar "
                "este horário."
            ),
        }

    turnos = turnos_do_dia(agenda, inicio.weekday())
    if not turnos:
        return {
            "livre": False,
            "motivo": "dia_sem_turno",
            "detalhe": "Este profissional não atende neste dia da semana.",
        }

    if not _intervalo_cabe(inicio, duracao_min, turnos):
        return {
            "livre": False,
            "motivo": "fora_do_turno",
            "detalhe": (
                f"O procedimento leva {duracao_min} min e não cabe no turno deste "
                "horário."
            ),
        }

    publicado = _slot_publicado(db, company_id, inicio)
    if publicado is False:
        return {
            "livre": False,
            "motivo": "slot_nao_publicado",
            "detalhe": "Este horário não está aberto na agenda.",
        }

    conflito = _conflito_agendamento(db, agenda, inicio, duracao_min)
    if conflito:
        hora = conflito.consulta_data.strftime("%H:%M")
        return {
            "livre": False,
            "motivo": "ocupado",
            "detalhe": f"Já existe atendimento neste profissional às {hora}.",
        }

    google = _google_ocupado(db, company_id, agenda, inicio, duracao_min)
    if google is True:
        return {
            "livre": False,
            "motivo": "ocupado_no_google",
            "detalhe": "A agenda do profissional tem um compromisso neste horário.",
        }

    return {
        "livre": True,
        "motivo": "livre",
        "detalhe": "Horário livre para este profissional.",
        "google_verificado": google is False,
        "agenda_id": agenda.id,
        "duracao_minutos": duracao_min,
    }


def horarios_disponiveis(
    db: Session,
    company_id: int,
    professional_id: int,
    service_id: Optional[int] = None,
    periodo: Optional[str] = None,
    dias: int = 14,
    limite: int = 3,
    agora: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Primeiros horarios livres, em ordem CRONOLOGICA, para aquele profissional.

    Ordem cronologica crescente e proposital: o card pede alternativas ordenadas
    pelos primeiros slots livres. Nada de amostra aleatoria — o paciente quer a
    agenda mais cedo.
    """
    agenda = agenda_ativa_do_profissional(db, company_id, professional_id)
    if not agenda:
        return []

    duracao = duracao_efetiva_minutos(db, company_id, professional_id, service_id)
    referencia = agora or datetime.now()
    margem = int(agenda.safety_margin_minutes or 0)
    inicio_busca = referencia + timedelta(minutes=margem)

    faixa = PERIODOS.get((periodo or "").strip().lower())
    achados: List[Dict[str, Any]] = []

    for deslocamento in range(dias + 1):
        dia = (inicio_busca + timedelta(days=deslocamento)).date()
        turnos = turnos_do_dia(agenda, dia.weekday())
        if not turnos:
            continue

        for abre, fecha in turnos:
            cursor = datetime.combine(dia, abre)
            fim_turno = datetime.combine(dia, fecha)
            while cursor + timedelta(minutes=duracao) <= fim_turno:
                candidato = cursor
                cursor = cursor + timedelta(minutes=duracao)

                if candidato < inicio_busca:
                    continue
                if faixa and not (faixa[0] <= candidato.time() < faixa[1]):
                    continue

                veredito = verificar_janela_livre(
                    db, company_id, professional_id, candidato, duracao
                )
                if not veredito["livre"]:
                    continue

                achados.append(
                    {
                        "inicio": candidato.strftime("%d/%m/%Y %H:%M"),
                        "duracao_minutos": duracao,
                        "professional_id": professional_id,
                        "agenda_id": veredito.get("agenda_id"),
                        "google_verificado": veredito.get("google_verificado", False),
                    }
                )
                if len(achados) >= limite:
                    return achados

    return achados


# ---------------------------------------------------------------------------
# Tools expostas ao agente
# ---------------------------------------------------------------------------
def create_clinical_tools(company_id: int, db_session_factory=None) -> List[Any]:
    """As tres tools do card F1-04, no formato do `agents` (function_tool).

    Cada tool abre a propria sessao, como o `get_available_slots` ja faz com
    `next(get_db())` — o agente roda em outro contexto e nao compartilha sessao
    com a requisicao HTTP.
    """
    from agents import function_tool

    def _abrir_db():
        if db_session_factory is not None:
            return db_session_factory()
        from backend.db import get_db  # import tardio: evita ciclo

        return next(get_db())

    # strict_mode=False: em modo estrito o SDK poe TODOS os parametros em `required`,
    # e uma chamada sem o campo e recusada inteira. Com strict desligado, `required` lista
    # so o que nao tem default.
    @function_tool(strict_mode=False)
    async def buscar_procedimentos_tool(termo: Optional[str] = None) -> Dict[str, Any]:
        """Lista os procedimentos da clinica, com duracao e preco.

        Use ANTES de falar de valor: procedimento sem preco (`citavel=False`)
        NAO pode ter valor citado ao paciente. Chame com `termo` quando o
        paciente citar algo ("clareamento", "limpeza", "avaliacao").
        """
        db = _abrir_db()
        try:
            itens = buscar_procedimentos(db, company_id, termo or None)
            return {"total": len(itens), "procedimentos": itens}
        finally:
            db.close()

    @function_tool(strict_mode=False)
    async def profissionais_que_atendem_tool(service_id: Optional[int] = None) -> Dict[str, Any]:
        """Quem da clinica faz aquele procedimento (so ativos, so com vinculo).

        Chame sempre antes de oferecer um profissional: oferecer quem nao faz o
        procedimento gera remarcacao depois.
        """
        db = _abrir_db()
        try:
            itens = profissionais_que_atendem(db, company_id, service_id)
            return {"total": len(itens), "profissionais": itens}
        finally:
            db.close()

    @function_tool(strict_mode=False)
    async def horarios_disponiveis_tool(
        professional_id: Optional[int] = None,
        service_id: Optional[int] = None,
        periodo: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Horarios LIVRES, em ordem cronologica (no maximo 3 opcoes).

        `professional_id` e OPCIONAL: se nao vier, a tool resolve sozinha quando a
        clinica tem um unico profissional habilitado para o procedimento. Se houver
        mais de um, devolve a lista para voce perguntar com quem o paciente quer ser
        atendido. Nunca falhe por falta desse id.

        Use `periodo` = "manha", "tarde" ou "noite" quando o paciente restringir. Se
        vier lista vazia, NAO invente horario: ofereca mais dias, lista de espera ou
        atendente.
        """
        db = _abrir_db()
        try:
            service_id = service_id or 0
            alvo = professional_id or 0
            if not alvo:
                # Resolve o profissional sem depender de o modelo saber o id.
                if service_id:
                    candidatos = profissionais_que_atendem(db, company_id, service_id)
                else:
                    candidatos = profissionais_que_atendem(db, company_id, 0)
                    if not candidatos:
                        candidatos = _profissionais_com_agenda(db, company_id)
                if len(candidatos) == 1:
                    alvo = candidatos[0]["professional_id"]
                elif len(candidatos) > 1:
                    return {
                        "precisa_escolher": True,
                        "profissionais": candidatos,
                        "observacao": (
                            "Mais de um profissional atende: pergunte ao paciente com quem "
                            "ele quer ser atendido e chame de novo com professional_id."
                        ),
                    }
                else:
                    return {
                        "total": 0,
                        "horarios": [],
                        "observacao": (
                            "Nenhum profissional ativo habilitado para este procedimento. "
                            "Ofereca falar com um atendente."
                        ),
                    }

            itens = horarios_disponiveis(
                db, company_id, alvo, service_id or None, periodo or None
            )
            return {
                "total": len(itens),
                "horarios": itens,
                "observacao": (
                    "Sem horario livre nos proximos 14 dias para este profissional."
                    if not itens
                    else ""
                ),
            }
        finally:
            db.close()

    return [buscar_procedimentos_tool, profissionais_que_atendem_tool, horarios_disponiveis_tool]
