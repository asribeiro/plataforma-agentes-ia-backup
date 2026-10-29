"""Testes da agenda POR PROFISSIONAL (card F1-10).

O que este arquivo prova, e por que cada item importa:

  1. `resolver_agenda` (funcao pura): com duas agendas ativas e nenhum
     endereco, o servico ABSTEM em vez de escolher a primeira. Era exatamente
     esse chute que fazia o agente responder o horario da Dra. Ana para quem
     perguntou pelo Dr. Bruno.
  2. O horario e gerado da agenda do profissional pedido — dois profissionais
     com turnos diferentes devolvem horarios diferentes.
  3. `validar_profissional_da_empresa`: agenda nao se vincula a profissional de
     OUTRA empresa (vazamento entre clinicas) nem a profissional inativo.
  4. `validar_agenda_unica_ativa`: 1 profissional = 1 agenda ATIVA, com
     mensagem de negocio (o indice parcial do Postgres nao e criado no SQLite,
     entao a regra e testada na funcao que a antecipa).

Roda em SQLite em memoria, sem PostgreSQL e sem rede.
"""
from datetime import datetime, time, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.agents_sdk.tools.slots_service import SlotsService, resolver_agenda
from backend.models import (
    Agenda,
    AgendaSchedule,
    Agendamento,
    Base,
    Company,
    Professional,
)
from backend.routes.calendar_routes import (
    AgendaCreate,
    validar_agenda_unica_ativa,
    validar_profissional_da_empresa,
)


# --------------------------------------------------------------------- fixtures

@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    tabelas = [
        Company.__table__,
        Professional.__table__,
        Agenda.__table__,
        AgendaSchedule.__table__,
        # a checagem de conflito de horario consulta agendamentos: sem esta
        # tabela o servico engole o OperationalError e devolve lista vazia, o
        # que faria o teste passar por acidente (e passou, na primeira versao).
        Agendamento.__table__,
    ]
    Base.metadata.create_all(eng, tables=tabelas)
    Sessao = sessionmaker(bind=eng)
    s = Sessao()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def clinica(db):
    """Empresa A com dois profissionais ativos e um inativo; empresa B com um."""
    a = Company(name="Clinica A", cnpj="00000000000110")
    b = Company(name="Clinica B", cnpj="00000000000120")
    db.add_all([a, b])
    db.commit()

    ana = Professional(company_id=a.id, name="Dra. Ana", email="ana@a.teste", active=True)
    bruno = Professional(company_id=a.id, name="Dr. Bruno", email="bruno@a.teste", active=True)
    inativo = Professional(company_id=a.id, name="Dr. Inativo", email="off@a.teste", active=False)
    beto = Professional(company_id=b.id, name="Dr. Beto", email="beto@b.teste", active=True)
    db.add_all([ana, bruno, inativo, beto])
    db.commit()
    return {"a": a, "b": b, "ana": ana, "bruno": bruno, "inativo": inativo, "beto": beto}


def _agenda(company_id, professional_id, nome, inicio, fim, ativa=True, duracao=30):
    """Agenda com turno de segunda a domingo na janela pedida."""
    return Agenda(
        company_id=company_id,
        professional_id=professional_id,
        name=nome,
        slot_duration=duracao,
        active=ativa,
        safety_margin_minutes=0,
        schedules=[
            AgendaSchedule(
                day_of_week=dia,
                morning_start=inicio,
                morning_end=fim,
            )
            for dia in range(7)
        ],
    )


# ------------------------------------- 1) funcao pura de resolucao da agenda

def test_sem_endereco_e_duas_agendas_abstem_em_vez_de_chutar():
    uma = Agenda(id=1, professional_id=10)
    outra = Agenda(id=2, professional_id=20)
    agenda, motivo = resolver_agenda([uma, outra])
    assert agenda is None
    assert motivo == "ambiguo"


def test_endereco_por_profissional_devolve_a_agenda_dele():
    uma = Agenda(id=1, professional_id=10)
    outra = Agenda(id=2, professional_id=20)
    agenda, motivo = resolver_agenda([uma, outra], professional_id=20)
    assert agenda is outra
    assert motivo == ""


def test_endereco_por_agenda_id_devolve_a_agenda_pedida():
    uma = Agenda(id=1, professional_id=10)
    outra = Agenda(id=2, professional_id=20)
    agenda, motivo = resolver_agenda([uma, outra], agenda_id=1)
    assert agenda is uma and motivo == ""


def test_agenda_id_que_nao_esta_entre_as_candidatas_nao_vaza():
    """Agenda de outra empresa nao aparece na lista, e nao pode ser devolvida."""
    agenda, motivo = resolver_agenda([Agenda(id=1, professional_id=10)], agenda_id=99)
    assert agenda is None and motivo == "agenda_inexistente"


def test_profissional_sem_agenda_ativa():
    agenda, motivo = resolver_agenda([Agenda(id=1, professional_id=10)], professional_id=20)
    assert agenda is None and motivo == "profissional_sem_agenda"


def test_uma_unica_agenda_resolve_sem_endereco():
    so = Agenda(id=7, professional_id=10)
    agenda, motivo = resolver_agenda([so])
    assert agenda is so and motivo == ""


def test_empresa_sem_agenda_ativa():
    agenda, motivo = resolver_agenda([])
    assert agenda is None and motivo == "sem_agenda_ativa"


# ------------------------------- 3) vinculo com profissional da mesma empresa

def test_vinculo_recusa_profissional_de_outra_empresa(db, clinica):
    with pytest.raises(HTTPException) as erro:
        validar_profissional_da_empresa(db, clinica["a"].id, clinica["beto"].id)
    assert erro.value.status_code == 404
    assert "não encontrado nesta empresa" in erro.value.detail


def test_vinculo_recusa_profissional_inativo_com_orientacao(db, clinica):
    with pytest.raises(HTTPException) as erro:
        validar_profissional_da_empresa(db, clinica["a"].id, clinica["inativo"].id)
    assert erro.value.status_code == 409
    assert "inativo" in erro.value.detail and "Reative" in erro.value.detail


def test_vinculo_aceita_profissional_ativo_da_empresa(db, clinica):
    prof = validar_profissional_da_empresa(db, clinica["a"].id, clinica["ana"].id)
    assert prof.id == clinica["ana"].id


# -------------------------------------------- 4) 1 profissional = 1 agenda ativa

def test_segunda_agenda_ativa_do_mesmo_profissional_e_recusada(db, clinica):
    db.add(_agenda(clinica["a"].id, clinica["ana"].id, "Agenda da Ana",
                   time(8, 0), time(12, 0)))
    db.commit()
    with pytest.raises(HTTPException) as erro:
        validar_agenda_unica_ativa(db, clinica["ana"].id)
    assert erro.value.status_code == 409
    assert "uma agenda só" in erro.value.detail


def test_editar_a_propria_agenda_nao_colide_com_ela_mesma(db, clinica):
    agenda = _agenda(clinica["a"].id, clinica["ana"].id, "Agenda da Ana",
                     time(8, 0), time(12, 0))
    db.add(agenda)
    db.commit()
    # ignorar a propria agenda: nao deve levantar
    validar_agenda_unica_ativa(db, clinica["ana"].id, ignorar_agenda_id=agenda.id)


def test_agenda_inativa_nao_ocupa_a_vaga_do_profissional(db, clinica):
    db.add(_agenda(clinica["a"].id, clinica["ana"].id, "Antiga",
                   time(8, 0), time(12, 0), ativa=False))
    db.commit()
    validar_agenda_unica_ativa(db, clinica["ana"].id)  # nao levanta


def test_cadastro_de_agenda_sem_profissional_e_recusado_no_schema():
    """A coluna nasceu nullable, mas o CADASTRO novo exige o dono."""
    with pytest.raises(ValidationError):
        AgendaCreate(name="Agenda solta", slot_duration=30, schedules=[])


# ------------------------------- 2) o horario vem da agenda do profissional

def test_slots_de_dois_profissionais_respeitam_o_turno_de_cada_um(db, clinica):
    """Ana atende de manha, Bruno de tarde: os horarios nao podem se misturar."""
    db.add(_agenda(clinica["a"].id, clinica["ana"].id, "Manha da Ana",
                   time(8, 0), time(12, 0)))
    db.add(_agenda(clinica["a"].id, clinica["bruno"].id, "Tarde do Bruno",
                   time(13, 0), time(18, 0)))
    db.commit()

    servico = SlotsService(db)
    da_ana = servico._generate_dynamic_slots(
        clinica["a"].id, days_ahead=7, professional_id=clinica["ana"].id, limit=50
    )
    do_bruno = servico._generate_dynamic_slots(
        clinica["a"].id, days_ahead=7, professional_id=clinica["bruno"].id, limit=50
    )

    assert da_ana and do_bruno, "os dois profissionais deveriam ter horarios"
    assert {s["professional_id"] for s in da_ana} == {clinica["ana"].id}
    assert {s["professional_id"] for s in do_bruno} == {clinica["bruno"].id}
    assert all(s["datetime"].hour < 12 for s in da_ana), "Ana so atende de manha"
    assert all(s["datetime"].hour >= 13 for s in do_bruno), "Bruno so a partir das 13h"
    # os conjuntos de horario nao se sobrepoem
    assert not ({s["datetime"] for s in da_ana} & {s["datetime"] for s in do_bruno})


def test_sem_endereco_e_duas_agendas_ativas_o_servico_nao_devolve_horario(db, clinica):
    db.add(_agenda(clinica["a"].id, clinica["ana"].id, "Ana", time(8, 0), time(12, 0)))
    db.add(_agenda(clinica["a"].id, clinica["bruno"].id, "Bruno", time(13, 0), time(18, 0)))
    db.commit()

    servico = SlotsService(db)
    assert servico._generate_dynamic_slots(clinica["a"].id, days_ahead=7) == []
    # e o caminho publico tambem abstem
    assert servico.get_available_slots(clinica["a"].id) == []


def test_agenda_de_outra_empresa_nao_responde_pelo_profissional(db, clinica):
    """Beto e da empresa B: pedir a agenda dele no escopo da A nao acha nada."""
    db.add(_agenda(clinica["b"].id, clinica["beto"].id, "Beto", time(8, 0), time(12, 0)))
    db.commit()

    servico = SlotsService(db)
    assert servico._generate_dynamic_slots(
        clinica["a"].id, days_ahead=7, professional_id=clinica["beto"].id
    ) == []
