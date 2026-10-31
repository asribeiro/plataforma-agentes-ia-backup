"""Feriados — regra de negócio central.

Decisões do dono do produto (31/10/2026):

- feriado BLOQUEIA todas as agendas de TODAS as clínicas (inclusive o municipal);
- cada clínica pode liberar profissional por profissional naquele feriado, e só o admin da
  clínica faz isso (`papeis_que_administram_usuarios`);
- feriado NÃO cancela agendamento existente: a tela mostra quantos pacientes já estão marcados
  no dia e o admin decide o que fazer.

Este módulo é a única fonte da verdade: quem gera horário (agente, tela, API) pergunta aqui.
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import Agendamento, Feriado, FeriadoExcecao, Professional

logger = logging.getLogger("saas_business.feriados")

URL_FERIADOS_NACIONAIS = "https://brasilapi.com.br/api/feriados/v1/{ano}"
# A BrasilAPI responde 403 para o User-Agent padrão do urllib ("Python-urllib/3.x").
# Medido no container: sem UA -> 403; com UA -> 200. Não é problema de rede.
CABECALHOS_IMPORTACAO = {
    "User-Agent": "Transformativa-Agenda/1.0 (+https://transformativa.com.br)",
    "Accept": "application/json",
}


def _como_data(valor: Any) -> Optional[date]:
    """Aceita date, datetime ou string ISO (YYYY-MM-DD)."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def feriados_do_ano(db: Session, ano: int) -> List[Feriado]:
    """Feriados cadastrados no ano, mais os recorrentes de qualquer ano."""
    inicio = date(ano, 1, 1)
    fim = date(ano, 12, 31)
    fixos = (
        db.query(Feriado)
        .filter(Feriado.data >= inicio, Feriado.data <= fim)
        .order_by(Feriado.data)
        .all()
    )
    recorrentes = db.query(Feriado).filter(Feriado.recorrente.is_(True)).all()

    vistos = {(item.id) for item in fixos}
    lista = list(fixos)
    for item in recorrentes:
        if item.id in vistos:
            continue
        # materializa o recorrente no ano consultado (mesmo dia e mes)
        try:
            materializado = date(ano, item.data.month, item.data.day)
        except ValueError:
            continue
        clone = Feriado(
            id=item.id,
            data=materializado,
            nome=item.nome,
            tipo=item.tipo,
            uf=item.uf,
            cidade=item.cidade,
            recorrente=True,
            origem=item.origem,
        )
        lista.append(clone)
    lista.sort(key=lambda f: f.data)
    return lista


def feriado_do_dia(db: Session, dia: Any) -> Optional[Feriado]:
    """O feriado que cai nesse dia, se houver (data exata ou recorrente)."""
    alvo = _como_data(dia)
    if alvo is None:
        return None

    exato = (
        db.query(Feriado)
        .filter(Feriado.data == alvo)
        .order_by(Feriado.id)
        .first()
    )
    if exato is not None:
        return exato

    for candidato in db.query(Feriado).filter(Feriado.recorrente.is_(True)).all():
        if (candidato.data.month, candidato.data.day) == (alvo.month, alvo.day):
            return candidato
    return None


def profissional_liberado(
    db: Session,
    feriado: Feriado,
    professional_id: Optional[int],
) -> bool:
    """True quando existe exceção liberando aquele profissional naquele feriado."""
    if feriado is None or not professional_id:
        return False
    return (
        db.query(FeriadoExcecao.id)
        .filter(
            FeriadoExcecao.feriado_id == feriado.id,
            FeriadoExcecao.professional_id == int(professional_id),
        )
        .first()
        is not None
    )


def feriado_bloqueia(
    db: Session,
    dia: Any,
    professional_id: Optional[int],
) -> Optional[Feriado]:
    """Devolve o feriado quando o dia está BLOQUEADO para esse profissional.

    None significa "pode atender": ou não é feriado, ou é feriado com exceção liberando.
    """
    feriado = feriado_do_dia(db, dia)
    if feriado is None:
        return None
    if profissional_liberado(db, feriado, professional_id):
        return None
    return feriado


def liberacoes_por_feriado(
    db: Session,
    company_id: int,
    feriado_ids: Iterable[int],
) -> Dict[int, List[int]]:
    """Mapa feriado_id -> [professional_id] liberados naquela clínica."""
    ids = [int(item) for item in feriado_ids if item]
    if not ids:
        return {}
    linhas = (
        db.query(FeriadoExcecao.feriado_id, FeriadoExcecao.professional_id)
        .filter(
            FeriadoExcecao.company_id == company_id,
            FeriadoExcecao.feriado_id.in_(ids),
        )
        .all()
    )
    mapa: Dict[int, List[int]] = {}
    for feriado_id, professional_id in linhas:
        mapa.setdefault(int(feriado_id), []).append(int(professional_id))
    return mapa


def definir_liberacoes(
    db: Session,
    *,
    feriado: Feriado,
    company_id: int,
    professional_ids: Iterable[int],
    created_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Substitui o conjunto de profissionais liberados naquele feriado, naquela clínica.

    Só aceita profissional da própria empresa e ativo: liberar profissional de outra clínica
    seria vazamento entre tenants.
    """
    pedidos = {int(item) for item in professional_ids if item}
    validos = {
        int(item)
        for (item,) in db.query(Professional.id)
        .filter(
            Professional.company_id == company_id,
            Professional.active.is_(True),
            Professional.id.in_(pedidos) if pedidos else False,
        )
        .all()
    } if pedidos else set()

    invalidos = sorted(pedidos - validos)
    if invalidos:
        return {
            "ok": False,
            "erro": "profissional_invalido",
            "profissionais_invalidos": invalidos,
            "mensagem": "Só é possível liberar profissional ativo da própria clínica.",
        }

    # `created_by` é auditoria: se o usuário não existir mais (ou vier de um teste), grava NULL em
    # vez de estourar a FK e derrubar a liberação inteira.
    if created_by is not None:
        from backend.models import User as UserModel

        existe_usuario = (
            db.query(UserModel.id).filter(UserModel.id == int(created_by)).first()
        )
        if existe_usuario is None:
            created_by = None

    atuais = (
        db.query(FeriadoExcecao)
        .filter(
            FeriadoExcecao.feriado_id == feriado.id,
            FeriadoExcecao.company_id == company_id,
        )
        .all()
    )
    atuais_por_profissional = {int(item.professional_id): item for item in atuais}

    removidos = 0
    for professional_id, linha in atuais_por_profissional.items():
        if professional_id not in validos:
            db.delete(linha)
            removidos += 1

    criados = 0
    for professional_id in sorted(validos):
        if professional_id in atuais_por_profissional:
            continue
        db.add(
            FeriadoExcecao(
                feriado_id=feriado.id,
                company_id=company_id,
                professional_id=professional_id,
                created_by=created_by,
            )
        )
        criados += 1

    db.commit()
    logger.info(
        "[Feriados] feriado=%s empresa=%s liberados=%s (novos=%s removidos=%s)",
        feriado.id, company_id, sorted(validos), criados, removidos,
    )
    return {
        "ok": True,
        "feriado_id": feriado.id,
        "company_id": company_id,
        "liberados": sorted(validos),
        "criados": criados,
        "removidos": removidos,
    }


def agendamentos_por_dia(
    db: Session,
    dias: Iterable[Any],
    company_id: Optional[int] = None,
) -> Dict[str, Dict[str, int]]:
    """Quantos agendamentos ATIVOS existem por dia — o aviso para o admin.

    Feriado não cancela nada: quem decide é o admin da clínica, com o número na mão.
    """
    lista = [_como_data(dia) for dia in dias]
    lista = [item for item in lista if item]
    if not lista:
        return {}

    consulta = (
        db.query(
            func.date(Agendamento.consulta_data).label("dia"),
            func.count(Agendamento.id).label("total"),
        )
        .filter(
            func.date(Agendamento.consulta_data).in_(lista),
            ~Agendamento.status.ilike("CANCEL%"),
        )
    )
    if company_id:
        consulta = consulta.filter(Agendamento.company_id == company_id)
    consulta = consulta.group_by(func.date(Agendamento.consulta_data))

    return {
        str(dia): {"total": int(total)}
        for dia, total in consulta.all()
    }


def importar_nacionais(db: Session, ano: int) -> Dict[str, Any]:
    """Importa os feriados nacionais do ano pela BrasilAPI (idempotente).

    Falha de rede/API é declarada, nunca silenciosa: devolve `ok: False` com o motivo.
    """
    url = URL_FERIADOS_NACIONAIS.format(ano=ano)
    try:
        requisicao = urllib.request.Request(url, headers=CABECALHOS_IMPORTACAO)
        with urllib.request.urlopen(requisicao, timeout=20) as resposta:  # noqa: S310 - URL fixa
            dados = json.loads(resposta.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("[Feriados] falha ao importar %s: %s", url, exc)
        return {"ok": False, "erro": str(exc), "ano": ano, "importados": 0}

    if not isinstance(dados, list):
        return {"ok": False, "erro": "resposta_inesperada", "ano": ano, "importados": 0}

    importados = 0
    existentes = 0
    for item in dados:
        dia = _como_data(item.get("date"))
        nome = str(item.get("name") or "").strip()
        if dia is None or not nome:
            continue
        ja_existe = (
            db.query(Feriado.id)
            .filter(Feriado.data == dia, Feriado.nome == nome)
            .first()
        )
        if ja_existe:
            existentes += 1
            continue
        db.add(
            Feriado(
                data=dia,
                nome=nome[:120],
                tipo="nacional",
                recorrente=False,
                origem="importado",
            )
        )
        importados += 1

    db.commit()
    logger.info("[Feriados] importados %s nacionais de %s (%s ja existiam)", importados, ano, existentes)
    return {"ok": True, "ano": ano, "importados": importados, "ja_existiam": existentes}
