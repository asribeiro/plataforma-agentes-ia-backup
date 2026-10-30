"""Consertos na raiz pedidos pela tela: destino do redirect e credencial do /link.

Sao os dois pontos em que a tela precisou contornar o backend (aba forcada na mao e
botoes legados escondidos). Se estes testes passam, o contorno deixa de ser
necessario — e o proximo que mexer nao reintroduz.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import get_db
from backend.models import Agenda, Base, CalendarIntegration, Company

EMPRESA = 1


@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        eng,
        tables=[Company.__table__, Agenda.__table__, CalendarIntegration.__table__],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    empresa = Company(name="Clinica A", cnpj="00000000001000")
    db.add(empresa)
    db.commit()
    agenda = Agenda(
        company_id=empresa.id,
        name="Dra. Ana",
        slot_duration=30,
        google_oauth_token={"refresh_token": "r-da-agenda"},
    )
    db.add(agenda)
    db.add(
        CalendarIntegration(
            company_id=empresa.id,
            provider="google",
            google_calendar_id="cal-empresa",
            google_oauth_token={"refresh_token": "r-da-empresa"},
        )
    )
    db.commit()
    return {"empresa": empresa, "agenda": agenda}


@pytest.fixture()
def app(db):
    import backend.routes.integrations.calendar_integration as ci

    app = FastAPI()
    app.include_router(ci.router, prefix="/api/integrations/calendar")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[ci.require_google_agenda_company_access] = lambda: type(
        "U", (), {"id": 7, "role": "clinic_admin"}
    )()
    return app


# --------------------------------------------------- destino depois do OAuth
def test_quem_autorizou_uma_agenda_volta_para_a_tela_de_agendas(cenario, app, monkeypatch):
    import backend.routes.integrations.calendar_integration as ci

    class Credenciais:
        scopes = ["s"]

        def to_json(self):
            return '{"refresh_token": "r-novo"}'

    class FlowFalso:
        credentials = Credenciais()

        def fetch_token(self, code=None):
            pass

    monkeypatch.setattr(ci, "_new_oauth_flow", lambda *a, **k: FlowFalso())
    monkeypatch.setattr(ci, "build_google_oauth_service", lambda *a, **k: object())
    monkeypatch.setattr(
        ci,
        "_list_writable_calendars",
        lambda s: [{"id": "cal-dra", "summary": "Dra. Ana", "primary": True}],
    )

    state = ci._make_state(EMPRESA, 7, cenario["agenda"].id)
    resposta = TestClient(app, follow_redirects=False).get(
        f"/api/integrations/calendar/google/oauth/callback?state={state}&code=abc"
    )
    destino = resposta.headers["location"]
    assert "/calendar-config" in destino, destino
    assert "tab=hours" in destino, destino
    assert destino.count(f"agenda_id={cenario['agenda'].id}") == 1, destino
    assert "/prompt/agenda" not in destino, "tela da empresa nao e o destino de quem autorizou a agenda"


def test_o_erro_do_oauth_diz_qual_agenda_falhou(cenario, app):
    import backend.routes.integrations.calendar_integration as ci

    state = ci._make_state(EMPRESA, 7, cenario["agenda"].id)
    resposta = TestClient(app, follow_redirects=False).get(
        f"/api/integrations/calendar/google/oauth/callback?state={state}&error=access_denied"
    )
    destino = resposta.headers["location"]
    assert "reason=access_denied" in destino
    assert f"agenda_id={cenario['agenda'].id}" in destino, (
        "sem o agenda_id a tela nao consegue dizer qual agenda falhou"
    )


def test_profissional_nao_inicia_oauth_para_agenda_de_outro_profissional(cenario, app):
    import backend.routes.integrations.calendar_integration as ci

    cenario["agenda"].professional_id = 41
    app.dependency_overrides[ci.require_google_agenda_company_access] = lambda: SimpleNamespace(
        role="service_professional",
        professional_id=42,
    )
    resposta = TestClient(app).get(
        f"/api/integrations/calendar/google/{EMPRESA}/oauth/start?agenda_id={cenario['agenda'].id}"
    )
    assert resposta.status_code == 403


def test_sem_agenda_o_destino_continua_sendo_a_tela_da_empresa(cenario, app, monkeypatch):
    import backend.routes.integrations.calendar_integration as ci

    class Credenciais:
        scopes = ["s"]

        def to_json(self):
            return '{"refresh_token": "r-empresa"}'

    class FlowFalso:
        credentials = Credenciais()

        def fetch_token(self, code=None):
            pass

    monkeypatch.setattr(ci, "_new_oauth_flow", lambda *a, **k: FlowFalso())
    monkeypatch.setattr(ci, "build_google_oauth_service", lambda *a, **k: object())
    monkeypatch.setattr(ci, "_list_writable_calendars", lambda s: [{"id": "cal-x", "primary": True}])

    state = ci._make_state(EMPRESA, 7)
    resposta = TestClient(app, follow_redirects=False).get(
        f"/api/integrations/calendar/google/oauth/callback?state={state}&code=abc"
    )
    assert "/prompt/agenda" in resposta.headers["location"]


# ------------------------------------------------- /link com credencial certa
def test_link_usa_a_credencial_da_agenda_e_nao_a_da_empresa(db, cenario, monkeypatch):
    """Com credencial propria, a agenda tem de validar o calendario na conta DELA.

    Antes o /link montava o servico com a credencial da empresa: dava para gravar
    um calendario da conta da clinica numa agenda que escreve com o token do
    profissional — e o evento iria para o calendario errado.
    """
    import backend.routes.integrations.calendar_integration as ci
    import backend.services.google_credencial as gc

    chamadas = {}

    class ServicoDaAgenda:
        def calendarList(self):
            class Lista:
                def get(self, calendarId):
                    chamadas["calendario_pedido"] = calendarId

                    class Exec:
                        def execute(self):
                            return {
                                "id": calendarId,
                                "summary": "Dra. Ana",
                                "accessRole": "owner",
                                "timeZone": "America/Sao_Paulo",
                            }

                    return Exec()

            return Lista()

    def build_da_agenda(_db, _company_id, agenda):
        chamadas["agenda"] = getattr(agenda, "name", None)
        return ServicoDaAgenda(), gc.FONTE_AGENDA

    monkeypatch.setattr(gc, "build_service_da_agenda", build_da_agenda)
    monkeypatch.setattr(
        ci,
        "build_google_oauth_service",
        lambda *a, **k: pytest.fail("nao pode usar a credencial da empresa"),
    )

    resultado = ci._link_calendar_to_agenda(db, None, cenario["agenda"], "cal-dra-ana")
    assert chamadas["agenda"] == "Dra. Ana", "tem de resolver pela AGENDA"
    assert chamadas["calendario_pedido"] == "cal-dra-ana"
    assert resultado.get("id") == "cal-dra-ana"

    db.refresh(cenario["agenda"])
    assert cenario["agenda"].google_calendar_id == "cal-dra-ana"


def test_desvincular_nao_exige_credencial_da_empresa(db, cenario, app):
    """Desvincular e limpar colunas. Antes o endpoint dava 404 se so a agenda
    tivesse Google conectado — a pessoa nao conseguia desfazer."""
    empresa_so_agenda = Company(name="Clinica C", cnpj="00000000001002")
    db.add(empresa_so_agenda)
    db.commit()
    agenda = Agenda(
        company_id=empresa_so_agenda.id,
        name="Dr. Bruno",
        slot_duration=30,
        google_oauth_token={"refresh_token": "r"},
        google_calendar_id="cal-bruno",
        google_calendar_summary="Dr. Bruno",
    )
    db.add(agenda)
    db.commit()
    assert (
        db.query(CalendarIntegration)
        .filter(CalendarIntegration.company_id == empresa_so_agenda.id)
        .first()
        is None
    )

    resposta = TestClient(app).delete(
        f"/api/integrations/calendar/google/{empresa_so_agenda.id}/agendas/{agenda.id}/link"
    )
    assert resposta.status_code == 200, resposta.text
    db.refresh(agenda)
    assert agenda.google_calendar_id is None
