"""Fechamento de F1-02 (agente pergunta o e-mail) e F1-06 (OAuth por agenda).

Sem chamada real ao Google: o fluxo OAuth e o cliente sao substituidos. O que se
prova e o que o sistema GRAVA e ONDE grava — que era exatamente o furo: a coluna
existia e ninguem conseguia popular.
"""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
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
    agenda = Agenda(company_id=empresa.id, name="Dra. Ana", slot_duration=30)
    outra = Agenda(company_id=empresa.id, name="Dr. Bruno", slot_duration=30)
    db.add_all([agenda, outra])
    db.commit()
    return {"empresa": empresa, "agenda": agenda, "outra": outra}


# ============================================================ F1-02 (o e-mail)
def test_a_tool_de_agendar_expoe_lead_email_para_o_modelo():
    """A tool e o unico caminho do agente: se o parametro nao existe, o agente nao
    tem como pedir nem gravar o e-mail — foi exatamente o buraco do F1-02."""
    from backend.agents_sdk.tools.calendar_scheduling_tools import (
        create_calendar_scheduling_tools,
    )

    ferramentas = create_calendar_scheduling_tools(
        company_id=EMPRESA, allowed_actions=["create_appointment"]
    )
    por_nome = {getattr(f, "name", ""): f for f in ferramentas}
    assert "create_lead_appointment" in por_nome, list(por_nome)

    esquema = por_nome["create_lead_appointment"].params_json_schema
    propriedades = esquema.get("properties", {})
    assert "lead_email" in propriedades, sorted(propriedades)
    # O SDK poe TODO parametro em `required` (lead_phone tambem) e DESCARTA o
    # Field(description=...) de parametro anotado: o modelo recebe o campo sem
    # explicacao. Logo, o que instrui o modelo e a DOCSTRING da tool — e o teste
    # abaixo e o que garante que a instrucao exista. Sem ela o agente tende a
    # inventar e-mail para "cumprir" o schema.
    assert propriedades["lead_email"].get("default") == "", "vazio precisa ser o padrao"
    assert "lead_phone" in esquema.get("required", []), (
        "se isso falhar, o SDK mudou: revisar a premissa sobre required"
    )
    descricao_tool = (por_nome["create_lead_appointment"].description or "").lower()
    assert "lead_email" in descricao_tool, "a docstring precisa falar do e-mail"
    assert "whatsapp" in descricao_tool, "precisa dizer que sem e-mail o aviso vai por WhatsApp"
    assert "nunca invente" in descricao_tool, "precisa proibir e-mail inventado"


def test_email_invalido_do_lead_nao_vira_lixo_no_banco():
    from backend.services.google_convite import normalizar_email

    assert normalizar_email("paciente@exemplo.com") == "paciente@exemplo.com"
    assert normalizar_email("paciente arroba exemplo") is None
    assert normalizar_email("") is None


def test_prompt_manda_pedir_o_email_sem_bloquear():
    """O prompt e o que faz o agente perguntar. Sem instrucao, tool nenhuma e usada."""
    from backend.agents_sdk.prompts.legacy_domain import _get_formatted_prompt
    import inspect

    fonte = inspect.getsource(_get_formatted_prompt)
    assert "lead_email" in fonte or "E-MAIL DO PACIENTE" in fonte, (
        "o prompt precisa citar o e-mail do paciente dentro do que ele formata"
    )


# ===================================================== F1-06 (OAuth por agenda)
def test_state_carrega_o_agenda_id_quando_ha_agenda(cenario):
    import backend.routes.integrations.calendar_integration as ci

    sem_agenda = ci._read_state(ci._make_state(EMPRESA, 1))
    assert "agenda_id" not in sem_agenda

    com_agenda = ci._read_state(ci._make_state(EMPRESA, 1, cenario["agenda"].id))
    assert com_agenda["agenda_id"] == cenario["agenda"].id


def test_google_agenda_so_pode_ser_gerenciado_pelo_admin_ou_pelo_proprio_profissional():
    import backend.routes.integrations.calendar_integration as ci

    agenda = Agenda(company_id=EMPRESA, name="Dra. Ana", professional_id=41)
    admin_clinica = SimpleNamespace(role="clinic_admin")
    profissional_dono = SimpleNamespace(role="service_professional", professional_id=41)
    profissional_alheio = SimpleNamespace(role="service_professional", professional_id=42)
    gerente = SimpleNamespace(role="manager", professional_id=41)

    ci._ensure_google_agenda_access(admin_clinica, agenda)
    ci._ensure_google_agenda_access(profissional_dono, agenda)
    for usuario in (profissional_alheio, gerente):
        with pytest.raises(HTTPException) as erro:
            ci._ensure_google_agenda_access(usuario, agenda)
        assert erro.value.status_code == 403


def test_admin_da_plataforma_configura_agenda_de_qualquer_empresa(monkeypatch):
    import backend.routes.integrations.calendar_integration as ci

    agenda = Agenda(company_id=99, name="Dr. Outro", professional_id=77)
    admin_plataforma = SimpleNamespace(role="admin", email="master@x.com")
    monkeypatch.setattr(ci, "is_internal_admin", lambda u: u is admin_plataforma)

    ci._ensure_google_agenda_access(admin_plataforma, agenda)
    with pytest.raises(HTTPException) as erro:
        ci._ensure_google_agenda_access(SimpleNamespace(role="admin", email="outro@x.com"), agenda)
    assert erro.value.status_code == 403


def test_retorno_do_oauth_pode_ser_a_tela_google_agenda():
    import backend.routes.integrations.calendar_integration as ci

    destino = ci._oauth_success_redirect("google_oauth=success", 5, "integrations")
    assert "/calendar-config?tab=integrations&" in destino
    assert "agenda_id=5" in destino


@pytest.fixture()
def app(db):
    import backend.routes.integrations.calendar_integration as ci

    app = FastAPI()
    app.include_router(ci.router, prefix="/api/integrations/calendar")
    app.dependency_overrides[get_db] = lambda: db
    return app


def _mocar_oauth(monkeypatch, calendarios, token="r-da-agenda"):
    import backend.routes.integrations.calendar_integration as ci

    class Credenciais:
        scopes = ["https://www.googleapis.com/auth/calendar.events"]

        def to_json(self):
            return json.dumps({"refresh_token": token, "token": "t"})

    class FlowFalso:
        credentials = Credenciais()

        def fetch_token(self, code=None):
            assert code

    monkeypatch.setattr(ci, "_new_oauth_flow", lambda *a, **k: FlowFalso())
    monkeypatch.setattr(ci, "build_google_oauth_service", lambda *a, **k: object())
    monkeypatch.setattr(ci, "_list_writable_calendars", lambda service: calendarios)


CALENDARIOS = [
    {"id": "cal-dra-ana", "summary": "Dra. Ana", "primary": True, "timeZone": "America/Sao_Paulo"},
    {"id": "cal-clinica", "summary": "Clínica", "primary": False, "timeZone": "America/Sao_Paulo"},
]


def test_callback_com_agenda_id_grava_na_agenda_e_nao_na_empresa(db, cenario, app, monkeypatch):
    import backend.routes.integrations.calendar_integration as ci

    _mocar_oauth(monkeypatch, CALENDARIOS)
    state = ci._make_state(cenario["empresa"].id, 1, cenario["agenda"].id)

    resposta = TestClient(app, follow_redirects=False).get(
        f"/api/integrations/calendar/google/oauth/callback?state={state}&code=abc123"
    )
    assert resposta.status_code in (302, 307), resposta.text
    assert f"agenda_id={cenario['agenda'].id}" in resposta.headers["location"]

    agenda = db.query(Agenda).filter(Agenda.id == cenario["agenda"].id).first()
    db.refresh(agenda)
    assert agenda.google_oauth_token["refresh_token"] == "r-da-agenda"
    assert agenda.google_account_email == "cal-dra-ana"
    assert agenda.google_calendar_id == "cal-dra-ana", "calendario primario quando ainda nao havia"

    # A EMPRESA NAO PODE SER TOCADA: as outras agendas dependem dela.
    assert db.query(CalendarIntegration).filter(
        CalendarIntegration.company_id == cenario["empresa"].id
    ).first() is None

    outra = db.query(Agenda).filter(Agenda.id == cenario["outra"].id).first()
    db.refresh(outra)
    assert outra.google_oauth_token is None


def test_callback_com_agenda_de_outra_empresa_e_recusado(db, cenario, app, monkeypatch):
    import backend.routes.integrations.calendar_integration as ci

    _mocar_oauth(monkeypatch, CALENDARIOS)
    outra_empresa = Company(name="Clinica B", cnpj="00000000001001")
    db.add(outra_empresa)
    db.commit()
    agenda_alheia = Agenda(company_id=outra_empresa.id, name="Alheia", slot_duration=30)
    db.add(agenda_alheia)
    db.commit()

    state = ci._make_state(cenario["empresa"].id, 1, agenda_alheia.id)
    resposta = TestClient(app, follow_redirects=False).get(
        f"/api/integrations/calendar/google/oauth/callback?state={state}&code=abc123"
    )
    assert resposta.status_code == 404

    db.refresh(agenda_alheia)
    assert agenda_alheia.google_oauth_token is None


def test_callback_sem_agenda_id_continua_gravando_na_empresa(db, cenario, app, monkeypatch):
    """Compatibilidade: o fluxo antigo (empresa) nao pode quebrar."""
    import backend.routes.integrations.calendar_integration as ci

    _mocar_oauth(monkeypatch, CALENDARIOS, token="r-da-empresa")
    state = ci._make_state(cenario["empresa"].id, 1)

    resposta = TestClient(app, follow_redirects=False).get(
        f"/api/integrations/calendar/google/oauth/callback?state={state}&code=abc123"
    )
    assert resposta.status_code in (302, 307)

    integracao = db.query(CalendarIntegration).filter(
        CalendarIntegration.company_id == cenario["empresa"].id,
        CalendarIntegration.provider == "google",
    ).first()
    assert integracao is not None
    assert integracao.google_oauth_token["refresh_token"] == "r-da-empresa"

    agenda = db.query(Agenda).filter(Agenda.id == cenario["agenda"].id).first()
    db.refresh(agenda)
    assert agenda.google_oauth_token is None, "sem agenda_id a agenda nao recebe credencial"


def test_desconectar_credencial_da_agenda_nao_herda_a_da_empresa(db, cenario):
    from backend.services.google_credencial import FONTE_AGENDA, credencial_google_da_agenda

    agenda = cenario["agenda"]
    agenda.google_oauth_token = {"refresh_token": "r-agenda"}
    db.add(agenda)
    db.add(CalendarIntegration(
        company_id=cenario["empresa"].id,
        provider="google",
        google_calendar_id="cal-empresa",
        google_oauth_token={"refresh_token": "r-empresa"},
    ))
    db.commit()

    _dono, fonte = credencial_google_da_agenda(db, cenario["empresa"].id, agenda)
    assert fonte == FONTE_AGENDA

    agenda.google_oauth_token = None
    db.add(agenda)
    db.commit()

    dono, fonte = credencial_google_da_agenda(db, cenario["empresa"].id, agenda)
    assert dono is None
    assert fonte is None
