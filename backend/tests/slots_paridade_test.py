"""Uma regra de disponibilidade para a tela e para o agente (card F1-03).

O defeito que este teste tranca: a rota `GET /api/calendar/{id}/slots` devolvia
TODO slot do turno — passado, ocupado no banco e ocupado no Google. A tela oferecia
vaga que o agente descartava na conversa seguinte. Duas regras de disponibilidade no
mesmo sistema e um bug garantido.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agents_sdk.tools.slots_service import SlotsService
from backend.models import Agenda, Agendamento, Base, Company, Professional


@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        eng,
        tables=[
            Company.__table__,
            Professional.__table__,
            Agenda.__table__,
            Agendamento.__table__,
        ],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    empresa = Company(name="Clinica A", cnpj="00000000000900")
    db.add(empresa)
    db.commit()
    agenda = Agenda(
        company_id=empresa.id, name="Dra. Ana", slot_duration=30,
        timezone="America/Sao_Paulo", safety_margin_minutes=30,
    )
    db.add(agenda)
    db.commit()
    return {"empresa": empresa, "agenda": agenda}


def _agendamento(db, agenda, quando, status="SCHEDULED"):
    registro = Agendamento(
        client_id=1,
        lead_id=1,
        company_id=agenda.company_id,
        agenda_id=agenda.id,
        consulta_data=quando,
        status=status,
        nome="Paciente",
    )
    db.add(registro)
    db.commit()
    return registro


def test_remove_passado_ocupado_no_banco_e_ocupado_no_google(db, cenario, monkeypatch):
    agenda = cenario["agenda"]
    agora = datetime(2026, 11, 2, 8, 0)

    _agendamento(db, agenda, datetime(2026, 11, 2, 10, 0))

    # Google diz que 11:00 esta ocupado (compromisso marcado direto no Gmail).
    monkeypatch.setattr(
        SlotsService,
        "_fetch_google_busy_intervals",
        lambda self, company_id, ag, ini, fim: [
            {"start": datetime(2026, 11, 2, 11, 0), "end": datetime(2026, 11, 2, 11, 30)}
        ],
    )

    candidatos = [
        datetime(2026, 11, 2, 8, 0),    # dentro da margem de 30 min -> fora
        datetime(2026, 11, 2, 9, 0),    # livre
        datetime(2026, 11, 2, 10, 0),   # ocupado no banco -> fora
        datetime(2026, 11, 2, 11, 0),   # ocupado no Google -> fora
    ]

    livres = SlotsService(db).filtrar_slots_indisponiveis(
        cenario["empresa"].id, agenda, candidatos, agora=agora
    )
    assert livres == [datetime(2026, 11, 2, 9, 0)]


def test_cancelado_nao_bloqueia_horario(db, cenario, monkeypatch):
    agenda = cenario["agenda"]
    monkeypatch.setattr(
        SlotsService, "_fetch_google_busy_intervals", lambda self, *a: []
    )
    _agendamento(db, agenda, datetime(2026, 11, 2, 10, 0), status="CANCELLED")

    livres = SlotsService(db).filtrar_slots_indisponiveis(
        cenario["empresa"].id, agenda,
        [datetime(2026, 11, 2, 10, 0)],
        agora=datetime(2026, 11, 2, 8, 0),
    )
    assert livres == [datetime(2026, 11, 2, 10, 0)]


def test_duracao_do_slot_conta_na_colisao_do_google(db, cenario, monkeypatch):
    """Slot de 30 min nao pode entrar em cima do fim de um compromisso de 60."""
    agenda = cenario["agenda"]
    monkeypatch.setattr(
        SlotsService,
        "_fetch_google_busy_intervals",
        lambda self, *a: [
            {"start": datetime(2026, 11, 2, 9, 0), "end": datetime(2026, 11, 2, 10, 0)}
        ],
    )
    livres = SlotsService(db).filtrar_slots_indisponiveis(
        cenario["empresa"].id, agenda,
        [datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 2, 9, 30), datetime(2026, 11, 2, 10, 0)],
        agora=datetime(2026, 11, 2, 7, 0),
    )
    assert livres == [datetime(2026, 11, 2, 10, 0)]


def test_sem_google_a_regra_continua_valendo(db, cenario, monkeypatch):
    """Google fora do ar nao pode liberar horario ocupado no banco."""
    agenda = cenario["agenda"]
    monkeypatch.setattr(
        SlotsService, "_fetch_google_busy_intervals", lambda self, *a: []
    )
    _agendamento(db, agenda, datetime(2026, 11, 2, 9, 0))
    livres = SlotsService(db).filtrar_slots_indisponiveis(
        cenario["empresa"].id, agenda,
        [datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 2, 9, 30)],
        agora=datetime(2026, 11, 2, 7, 0),
    )
    assert livres == [datetime(2026, 11, 2, 9, 30)]


def test_lista_vazia_nao_chama_google(db, cenario, monkeypatch):
    chamou = {"vezes": 0}

    def registra(self, *a):
        chamou["vezes"] += 1
        return []

    monkeypatch.setattr(SlotsService, "_fetch_google_busy_intervals", registra)
    assert SlotsService(db).filtrar_slots_indisponiveis(
        cenario["empresa"].id, cenario["agenda"], []
    ) == []
    assert chamou["vezes"] == 0
