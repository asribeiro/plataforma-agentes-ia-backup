"""Tools clinicas do agente: procedimento, quem atende e janela do profissional.

Card F1-04. O defeito que este arquivo tranca e o que mais dói no atendimento:
o agente oferecer um horario que NAO esta livre — ou o horario de outro
profissional — e o paciente chegar e nao ter atendimento.

Nada aqui e "confianca no prompt": sao funcoes que decidem, com banco.
"""
from datetime import datetime, date, time, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.agents_sdk.database.models import CompanySlot
from backend.agents_sdk.tools.clinical_tools import (
    agenda_ativa_do_profissional,
    buscar_procedimentos,
    duracao_efetiva_minutos,
    horarios_disponiveis,
    profissionais_que_atendem,
    resolver_profissional_por_nome,
    turnos_do_dia,
    verificar_janela_livre,
)
from backend.models import (
    Agenda,
    AgendaSchedule,
    Agendamento,
    Base,
    Company,
    Professional,
    ProfessionalService,
    Service,
)


# --------------------------------------------------------------------- fixtures

@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        eng,
        tables=[
            Company.__table__,
            Service.__table__,
            Professional.__table__,
            ProfessionalService.__table__,
            Agenda.__table__,
            AgendaSchedule.__table__,
            Agendamento.__table__,
        ],
    )
    # company_slots tem declarative_base proprio (agents_sdk.database.models)
    CompanySlot.__table__.create(eng)
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


def _agenda(company_id, professional_id, turnos_por_dia, duracao=30, margem=0,
            ativa=True, google=None):
    """`turnos_por_dia`: {dia_semana: [(inicio, fim), ...]}.

    UMA linha por dia (a tabela tem unique em agenda_id+day_of_week): os turnos
    do dia caem em manha/tarde/noite na ordem em que vierem.
    """
    agenda = Agenda(
        company_id=company_id,
        professional_id=professional_id,
        name=f"Agenda {professional_id}",
        slot_duration=duracao,
        active=ativa,
        safety_margin_minutes=margem,
        google_calendar_id=google,
        schedules=[],
    )
    campos = (
        ("morning_start", "morning_end"),
        ("afternoon_start", "afternoon_end"),
        ("night_start", "night_end"),
    )
    for dia, turnos in turnos_por_dia.items():
        linha = AgendaSchedule(day_of_week=dia)
        for (ini, fim), (campo_ini, campo_fim) in zip(turnos, campos):
            setattr(linha, campo_ini, ini)
            setattr(linha, campo_fim, fim)
        agenda.schedules.append(linha)
    return agenda


TODOS_OS_DIAS = {d: [(time(8, 0), time(18, 0))] for d in range(7)}


@pytest.fixture()
def clinica(db):
    empresa = Company(name="Clinica Tools", cnpj="00000000000500")
    outra = Company(name="Clinica Vizinha", cnpj="00000000000501")
    db.add_all([empresa, outra])
    db.commit()

    clareamento = Service(
        company_id=empresa.id, name="Clareamento Dental", duration_minutes=90,
        price_cents=120000, is_evaluation=False, active=True,
    )
    avaliacao = Service(
        company_id=empresa.id, name="Avaliação", duration_minutes=30,
        price_cents=None, is_evaluation=True, active=True,
    )
    limpeza = Service(
        company_id=empresa.id, name="Limpeza", duration_minutes=30,
        price_cents=25000, is_evaluation=False, active=True,
    )
    db.add_all([clareamento, avaliacao, limpeza])
    db.commit()

    ana = Professional(company_id=empresa.id, name="Dra. Ana", email="ana@t.com", active=True)
    bruno = Professional(company_id=empresa.id, name="Dr. Bruno", email="bruno@t.com", active=True)
    inativa = Professional(company_id=empresa.id, name="Dra. Inativa", email="off@t.com", active=False)
    vizinho = Professional(company_id=outra.id, name="Dr. Vizinho", email="viz@t.com", active=True)
    db.add_all([ana, bruno, inativa, vizinho])
    db.commit()

    # Ana faz clareamento (com override de 60) e avaliacao; Bruno so limpeza
    db.add_all([
        ProfessionalService(professional_id=ana.id, service_id=clareamento.id,
                            duration_override_minutes=60),
        ProfessionalService(professional_id=ana.id, service_id=avaliacao.id),
        ProfessionalService(professional_id=bruno.id, service_id=limpeza.id),
        ProfessionalService(professional_id=inativa.id, service_id=limpeza.id),
    ])
    db.commit()

    return {
        "db": db, "empresa": empresa, "outra": outra,
        "clareamento": clareamento, "avaliacao": avaliacao, "limpeza": limpeza,
        "ana": ana, "bruno": bruno, "inativa": inativa, "vizinho": vizinho,
    }


def _proximo_dia_util(dias=7):
    """Data futura longe do fim de semana e da margem: hora cheia, dia inteiro."""
    base = date.today() + timedelta(days=dias)
    return base


# ------------------------------------------------------------------- duracao

def test_duracao_usa_override_do_profissional(clinica):
    db = clinica["db"]
    assert duracao_efetiva_minutos(db, clinica["empresa"].id, clinica["ana"].id,
                                   clinica["clareamento"].id) == 60


def test_duracao_cai_para_o_procedimento_sem_override(clinica):
    db = clinica["db"]
    # Bruno faz limpeza (30 min), sem override
    assert duracao_efetiva_minutos(db, clinica["empresa"].id, clinica["bruno"].id,
                                   clinica["limpeza"].id) == 30


def test_duracao_cai_para_o_slot_da_agenda_sem_procedimento(clinica):
    db = clinica["db"]
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS, duracao=45))
    db.commit()
    assert duracao_efetiva_minutos(db, clinica["empresa"].id, clinica["ana"].id, None) == 45


def test_duracao_padrao_quando_nao_ha_nada(clinica):
    db = clinica["db"]
    assert duracao_efetiva_minutos(db, clinica["empresa"].id, None, None) == 30


# ------------------------------------------------------------------- catalogo

def test_busca_procedimento_por_trecho_sem_caixa(clinica):
    itens = buscar_procedimentos(clinica["db"], clinica["empresa"].id, "claream")
    assert [i["nome"] for i in itens] == ["Clareamento Dental"]
    assert itens[0]["preco_reais"] == 1200.0 and itens[0]["citavel"] is True


def test_procedimento_sem_preco_nao_e_citavel(clinica):
    itens = buscar_procedimentos(clinica["db"], clinica["empresa"].id, "avalia")
    assert itens[0]["preco_reais"] is None
    assert itens[0]["citavel"] is False, "sem preco, o agente nao pode citar valor"


def test_busca_nao_vaza_procedimento_de_outra_empresa(clinica):
    db = clinica["db"]
    db.add(Service(company_id=clinica["outra"].id, name="Clareamento da Vizinha",
                   duration_minutes=60, price_cents=9900, is_evaluation=False, active=True))
    db.commit()
    nomes = [i["nome"] for i in buscar_procedimentos(db, clinica["empresa"].id)]
    assert "Clareamento da Vizinha" not in nomes


# -------------------------------------------------------- quem atende o que

def test_so_quem_tem_vinculo_e_esta_ativo_atende(clinica):
    db = clinica["db"]
    quem = profissionais_que_atendem(db, clinica["empresa"].id, clinica["limpeza"].id)
    nomes = [q["nome"] for q in quem]
    assert nomes == ["Dr. Bruno"], "inativa nao atende e Ana nao faz limpeza"


def test_vinculo_traz_o_override_para_o_agente_ver(clinica):
    db = clinica["db"]
    quem = profissionais_que_atendem(db, clinica["empresa"].id, clinica["clareamento"].id)
    assert quem[0]["duracao_override_minutos"] == 60


def test_resolver_profissional_por_nome_do_paciente(clinica):
    db = clinica["db"]
    assert resolver_profissional_por_nome(db, clinica["empresa"].id, "dra ana").id == clinica["ana"].id
    assert resolver_profissional_por_nome(db, clinica["empresa"].id, "bruno").id == clinica["bruno"].id
    assert resolver_profissional_por_nome(db, clinica["empresa"].id, "carlos") is None
    # nome de outra clinica nunca resolve
    assert resolver_profissional_por_nome(db, clinica["empresa"].id, "vizinho") is None


# ------------------------------------------------------------ a janela livre

def test_dia_sem_turno_nao_tem_janela(clinica):
    db = clinica["db"]
    dia = _proximo_dia_util()
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, {}))  # nenhum turno
    db.commit()
    veredito = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                      datetime.combine(dia, time(10, 0)), 30)
    assert veredito["livre"] is False and veredito["motivo"] == "dia_sem_turno"


def test_procedimento_longo_nao_cabe_no_fim_do_turno(clinica):
    """90 min as 17:30 num turno que fecha 18:00: o inicio existe, o intervalo nao cabe."""
    db = clinica["db"]
    dia = _proximo_dia_util()
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS))
    db.commit()
    veredito = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                      datetime.combine(dia, time(17, 30)), 90)
    assert veredito["livre"] is False
    assert veredito["motivo"] == "fora_do_turno"
    assert "90 min" in veredito["detalhe"]


def test_agendamento_ativo_do_mesmo_profissional_bloqueia(clinica):
    db = clinica["db"]
    dia = _proximo_dia_util()
    agenda = _agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS, duracao=30)
    db.add(agenda)
    db.commit()
    db.add(Agendamento(client_id=1, lead_id=1, company_id=clinica["empresa"].id,
                       agenda_id=agenda.id, consulta_data=datetime.combine(dia, time(15, 0)),
                       status="CONFIRMED"))
    db.commit()

    # 15:00 exato colide
    colide = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                    datetime.combine(dia, time(15, 0)), 30)
    assert colide["livre"] is False and colide["motivo"] == "ocupado"
    # 15:15 tambem colide (o agendamento ocupa o slot da agenda inteiro)
    sobreposto = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                        datetime.combine(dia, time(15, 15)), 30)
    assert sobreposto["livre"] is False
    # 16:00 esta livre
    livre = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                   datetime.combine(dia, time(16, 0)), 30)
    assert livre["livre"] is True


def test_agendamento_cancelado_nao_bloqueia(clinica):
    db = clinica["db"]
    dia = _proximo_dia_util()
    agenda = _agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS)
    db.add(agenda)
    db.commit()
    db.add(Agendamento(client_id=1, lead_id=1, company_id=clinica["empresa"].id,
                       agenda_id=agenda.id, consulta_data=datetime.combine(dia, time(10, 0)),
                       status="CANCELLED_BY_PATIENT"))
    db.commit()
    veredito = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                      datetime.combine(dia, time(10, 0)), 30)
    assert veredito["livre"] is True, "cancelado libera o horario"


def test_slot_nao_publicado_bloqueia_quando_o_dia_tem_publicacao(clinica):
    db = clinica["db"]
    dia = _proximo_dia_util()
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS))
    # id explicito: no SQLite a PK BigInteger nao vira rowid autoincremental
    # (no Postgres de producao e serial). E limitacao do banco de teste.
    db.add(CompanySlot(id=1, company_id=clinica["empresa"].id, slot_date=dia,
                       slot_time=time(9, 0), is_available=True))
    db.commit()
    publicado = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                       datetime.combine(dia, time(9, 0)), 30)
    assert publicado["livre"] is True
    nao_publicado = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                           datetime.combine(dia, time(11, 0)), 30)
    assert nao_publicado["livre"] is False
    assert nao_publicado["motivo"] == "slot_nao_publicado"


def test_dia_sem_publicacao_usa_o_turno(clinica):
    """Clinica que nao usa company_slots nao pode ficar sem horario nenhum."""
    db = clinica["db"]
    dia = _proximo_dia_util()
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS))
    db.commit()
    veredito = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                      datetime.combine(dia, time(11, 0)), 30)
    assert veredito["livre"] is True


def test_profissional_sem_agenda_ativa_nao_tem_janela(clinica):
    db = clinica["db"]
    veredito = verificar_janela_livre(db, clinica["empresa"].id, clinica["bruno"].id,
                                      datetime.combine(_proximo_dia_util(), time(9, 0)), 30)
    assert veredito["livre"] is False and veredito["motivo"] == "sem_agenda"


def test_margem_de_seguranca_bloqueia_horario_colado_no_agora(clinica):
    db = clinica["db"]
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS, margem=180))
    db.commit()
    veredito = verificar_janela_livre(db, clinica["empresa"].id, clinica["ana"].id,
                                      datetime.now().replace(microsecond=0), 30)
    assert veredito["livre"] is False and veredito["motivo"] == "dentro_da_margem"


# ------------------------------------------------------- horarios disponiveis

def test_horarios_vem_em_ordem_cronologica_e_limitados(clinica):
    db = clinica["db"]
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS, duracao=30))
    db.commit()
    agora = datetime.combine(_proximo_dia_util() - timedelta(days=1), time(20, 0))
    horarios = horarios_disponiveis(db, clinica["empresa"].id, clinica["ana"].id,
                                    service_id=clinica["avaliacao"].id, limite=3, agora=agora)
    assert len(horarios) == 3
    assert [h["inicio"] for h in horarios] == sorted(h["inicio"] for h in horarios)
    assert horarios[0]["inicio"].endswith("08:00"), "primeiro horario do turno"


def test_horarios_respeitam_a_duracao_do_procedimento(clinica):
    """Clareamento da Ana dura 60 min: nao pode oferecer 17:30 de um turno ate 18:00."""
    db = clinica["db"]
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS, duracao=30))
    db.commit()
    agora = datetime.combine(_proximo_dia_util() - timedelta(days=1), time(20, 0))
    horarios = horarios_disponiveis(db, clinica["empresa"].id, clinica["ana"].id,
                                    service_id=clinica["clareamento"].id, limite=50, agora=agora)
    assert horarios, "deveria haver horario"
    assert all(h["duracao_minutos"] == 60 for h in horarios)
    assert not any(h["inicio"].endswith("17:30") for h in horarios), \
        "60 min as 17:30 nao cabem num turno que fecha 18:00"
    # o ultimo horario possivel com 60 min comeca as 17:00
    assert any(h["inicio"].endswith("17:00") for h in horarios)


def test_filtro_de_periodo_tarde(clinica):
    db = clinica["db"]
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS))
    db.commit()
    agora = datetime.combine(_proximo_dia_util() - timedelta(days=1), time(20, 0))
    horarios = horarios_disponiveis(db, clinica["empresa"].id, clinica["ana"].id,
                                    periodo="tarde", limite=3, agora=agora)
    assert horarios and all(12 <= int(h["inicio"].split()[1][:2]) < 18 for h in horarios)


def test_profissional_de_outra_empresa_nao_devolve_horario(clinica):
    db = clinica["db"]
    db.add(_agenda(clinica["outra"].id, clinica["vizinho"].id, TODOS_OS_DIAS))
    db.commit()
    assert horarios_disponiveis(db, clinica["empresa"].id, clinica["vizinho"].id) == []


def test_turnos_do_dia_le_os_tres_turnos(clinica):
    db = clinica["db"]
    agenda = _agenda(clinica["empresa"].id, clinica["ana"].id,
                     {0: [(time(8, 0), time(12, 0)), (time(13, 0), time(18, 0))]})
    db.add(agenda)
    db.commit()
    turnos = turnos_do_dia(agenda, 0)
    assert turnos == [(time(8, 0), time(12, 0)), (time(13, 0), time(18, 0))]
    assert turnos_do_dia(agenda, 1) == []


def test_agenda_ativa_e_a_unica_considerada(clinica):
    db = clinica["db"]
    db.add(_agenda(clinica["empresa"].id, clinica["ana"].id, TODOS_OS_DIAS, ativa=False))
    db.commit()
    assert agenda_ativa_do_profissional(db, clinica["empresa"].id, clinica["ana"].id) is None
