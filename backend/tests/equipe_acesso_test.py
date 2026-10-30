"""Perfil de acesso (equipe) na API de usuarios da clinica — bloco B.

O defeito que isto tranca: papel e perfil de permissao viviam em APIs diferentes,
e a tela que editava usuario oferecia uma unica "funcao" (`staff`). Perfil existia
no banco e nao existia na tela. Aqui o mesmo endpoint que edita papel passa a
editar o perfil, com a mesma regra de null/ausente do vinculo com profissional.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Base, Company, Professional, Team, User
from backend.routes.clinic_users_routes import router as clinic_users_router


@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        eng,
        tables=[Company.__table__, Professional.__table__, User.__table__, Team.__table__],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    a = Company(name="Clinica A", cnpj="00000000001000")
    b = Company(name="Clinica B", cnpj="00000000001001")
    db.add_all([a, b])
    db.commit()

    prof = Professional(company_id=a.id, name="Dra. Ana", email="ana@a.com", active=True)
    db.add(prof)
    db.commit()

    recepcao = Team(company_id=a.id, name="Recepcao", code="RECEPCAO")
    clinico = Team(company_id=a.id, name="Clinico", code="CLINICO")
    da_outra = Team(company_id=b.id, name="Equipe da B", code="B")
    db.add_all([recepcao, clinico, da_outra])
    db.commit()

    admin = User(
        client_id=1, company_id=a.id, name="Admin Clinica", email="admin@a.com",
        password="x", role="clinic_admin", is_active=True,
    )
    operador = User(
        client_id=1, company_id=a.id, name="Operador", email="op@a.com",
        password="x", role="staff", team_id=recepcao.id, is_active=True,
    )
    db.add_all([admin, operador])
    db.commit()
    return {
        "a": a, "b": b, "prof": prof, "recepcao": recepcao, "clinico": clinico,
        "da_outra": da_outra, "admin": admin, "operador": operador,
    }


@pytest.fixture()
def app(db):
    app = FastAPI()
    app.include_router(clinic_users_router)
    app.dependency_overrides[get_db] = lambda: db
    return app


def _cliente(app, usuario):
    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app)


# ------------------------------------------------------------------- criar
def test_criar_com_perfil_de_acesso(cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={
            "name": "Nova Recepcao",
            "email": "nova@a.com",
            "password": "senha12345",
            "role": "staff",
            "team_id": cenario["recepcao"].id,
        },
    )
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["team_id"] == cenario["recepcao"].id
    assert corpo["team_nome"] == "Recepcao"


def test_perfil_de_outra_clinica_e_recusado(cenario, app):
    """Sem esta guarda, um id de equipe de outra clinica seria aceito e o usuario
    daqui herdaria permissoes de la."""
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={
            "name": "Intruso",
            "email": "intruso@a.com",
            "password": "senha12345",
            "role": "staff",
            "team_id": cenario["da_outra"].id,
        },
    )
    assert resposta.status_code == 400, resposta.text
    assert "não encontrado nesta clínica" in resposta.json()["detail"]


def test_criar_sem_perfil_continua_valendo(cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={
            "name": "Sem perfil",
            "email": "semperfil@a.com",
            "password": "senha12345",
            "role": "staff",
        },
    )
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["team_id"] is None
    assert resposta.json()["team_nome"] is None


# ------------------------------------------------------------------ editar
def test_trocar_o_perfil_de_acesso(cenario, app):
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{cenario['operador'].id}",
        json={"team_id": cenario["clinico"].id},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["team_id"] == cenario["clinico"].id
    assert resposta.json()["team_nome"] == "Clinico"


def test_patch_sem_team_preserva_o_perfil(cenario, app):
    """Corpo sem `team_id` nao pode zerar o perfil de quem ja tem — mesma regra do
    vinculo com profissional (so null explicito limpa)."""
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{cenario['operador'].id}",
        json={"name": "Operador Renomeado"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["team_id"] == cenario["recepcao"].id


def test_null_explicito_tira_o_perfil(cenario, app):
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{cenario['operador'].id}",
        json={"team_id": None},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["team_id"] is None


def test_nao_troca_para_perfil_de_outra_clinica(cenario, app):
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{cenario['operador'].id}",
        json={"team_id": cenario["da_outra"].id},
    )
    assert resposta.status_code == 400
    # e nada mudou
    corpo = _cliente(app, cenario["admin"]).get("/api/clinic/users").json()
    op = next(u for u in corpo if u["email"] == "op@a.com")
    assert op["team_id"] == cenario["recepcao"].id


# ---------------------------------------------------------------- /eu e lista
def test_eu_mostra_o_perfil_de_acesso(cenario, app):
    corpo = _cliente(app, cenario["operador"]).get("/api/clinic/users/eu").json()
    assert corpo["team_id"] == cenario["recepcao"].id
    assert corpo["team_nome"] == "Recepcao"


def test_lista_traz_o_perfil_de_cada_usuario(cenario, app):
    corpo = _cliente(app, cenario["admin"]).get("/api/clinic/users").json()
    por_email = {u["email"]: u for u in corpo}
    assert por_email["op@a.com"]["team_nome"] == "Recepcao"
    assert por_email["admin@a.com"]["team_id"] is None


# --------------------------------------------------- regras antigas intactas
def test_papel_clinico_sem_profissional_continua_recusado(cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={
            "name": "Clinico sem vinculo",
            "email": "semvinculo@a.com",
            "password": "senha12345",
            "role": "clinical_professional",
            "team_id": cenario["clinico"].id,
        },
    )
    # 409 (conflito de regra), nao 400: o payload esta bem formado, o que falta e
    # o vinculo. O que importa aqui e que o perfil de acesso NAO abriu brecha para
    # criar papel clinico sem profissional.
    assert resposta.status_code == 409, resposta.text
    assert "precisa estar vinculado a um profissional" in resposta.json()["detail"]
