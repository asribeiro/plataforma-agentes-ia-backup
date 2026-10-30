"""Dono do workspace (Client) administra os acessos da clinica dele.

Contexto do defeito: quem entra com o e-mail do dono e um `Client` (o `User` da
equipe e outro cadastro). `Client` nao tem coluna `role`, entao o papel vinha
vazio e o dono tomava 403 em `/api/clinic/users` — a unica tela que configura
papel e vinculo de cada usuario — e ainda via o menu Equipe escondido, porque
`/eu` dizia `pode_administrar_usuarios=false`.

O que continua valendo: todo o resto nega por padrao. `staff`, `manager` e
`service_professional` seguem sem administrar usuarios.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Base, Client, Company, Professional, User
from backend.routes.clinic_users_routes import router as clinic_users_router
from backend.services.papel_clinico import (
    PAPEL_DO_DONO_DO_WORKSPACE,
    _papel_do_usuario,
)

# O SQLite do teste nao conhece JSONB (coluna `billing_profile` de `clients`).
# Sem isto o create_all quebra ANTES de qualquer assercao. Nao muda o codigo sob
# teste: so ensina o dialeto de teste a escrever JSON no lugar de JSONB.
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

if not getattr(SQLiteTypeCompiler, "_hermes_jsonb_patch", False):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"
    SQLiteTypeCompiler._hermes_jsonb_patch = True


@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        eng,
        tables=[Company.__table__, Professional.__table__, User.__table__, Client.__table__],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    empresa = Company(name="Clinica A", cnpj="00000000000800")
    db.add(empresa)
    db.commit()

    prof = Professional(company_id=empresa.id, name="Dra. Ana", email="ana@a.com", active=True)
    db.add(prof)
    db.commit()

    dono = Client(
        email="dono@clinica.com",
        password="x",
        company_id=empresa.id,
        ownership_company_id=empresa.id,
        is_active=True,
    )
    staff = User(
        client_id=1, company_id=empresa.id, name="Recepcao", email="recepcao@a.com",
        password="x", role="staff", is_active=True,
    )
    atendente = User(
        client_id=1, company_id=empresa.id, name="Atendente", email="at@a.com",
        password="x", role="service_professional", professional_id=prof.id, is_active=True,
    )
    db.add_all([dono, staff, atendente])
    db.commit()
    return {"empresa": empresa, "prof": prof, "dono": dono, "staff": staff, "atendente": atendente}


@pytest.fixture()
def app(db):
    app = FastAPI()
    app.include_router(clinic_users_router)
    app.dependency_overrides[get_db] = lambda: db
    return app


def _cliente(app, usuario):
    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app)


# ------------------------------------------------------------------- papel
def test_client_tem_papel_de_admin_da_clinica(cenario):
    assert _papel_do_usuario(cenario["dono"]) == PAPEL_DO_DONO_DO_WORKSPACE
    assert PAPEL_DO_DONO_DO_WORKSPACE == "clinic_admin"


def test_user_sem_papel_continua_sem_papel(cenario):
    """Negar por padrao segue valendo: so o Client ganhou papel derivado."""
    objeto = type("SemPapel", (), {"email": "x@y.com"})()
    assert _papel_do_usuario(objeto) == ""


# ---------------------------------------------------------------- na API
def test_dono_lista_os_usuarios_da_clinica(cenario, app):
    resposta = _cliente(app, cenario["dono"]).get("/api/clinic/users")
    assert resposta.status_code == 200, resposta.text
    emails = {u["email"] for u in resposta.json()}
    assert "recepcao@a.com" in emails


def test_dono_ve_no_eu_que_administra_usuarios(cenario, app):
    """Este endpoint alimenta o menu: sem ele o item Equipe nao aparece."""
    corpo = _cliente(app, cenario["dono"]).get("/api/clinic/users/eu").json()
    assert corpo["pode_administrar_usuarios"] is True, corpo
    assert corpo["role"] == "clinic_admin", corpo
    assert corpo["ve_prontuario"] is True, corpo


def test_recepcao_nao_administra_usuarios(cenario, app):
    resposta = _cliente(app, cenario["staff"]).get("/api/clinic/users")
    assert resposta.status_code == 403


def test_atendente_nao_administra_usuarios(cenario, app):
    resposta = _cliente(app, cenario["atendente"]).get("/api/clinic/users")
    assert resposta.status_code == 403


def test_dono_nao_escapa_da_validacao_de_vinculo(cenario, app):
    """O dono administra, mas as regras de negocio continuam valendo para ele:
    papel clinico sem profissional vinculado e recusado igual."""
    resposta = _cliente(app, cenario["dono"]).post(
        "/api/clinic/users",
        json={
            "name": "Sem vinculo",
            "email": "sem.vinculo@a.com",
            "password": "senha12345",
            "role": "clinical_professional",
        },
    )
    assert resposta.status_code in (400, 422), resposta.text
