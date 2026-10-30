"""Quem pode listar/gerenciar perfis de permissao (equipes) — e de qual clinica.

Tranca o defeito que a tela de acessos encontrou: `clinic_admin` administra
usuarios da clinica, mas tomava 403 em `GET /api/teams/` e o seletor de perfil
vinha vazio. E tranca o que NAO pode mudar: ninguem enxerga equipe de outra
clinica, e os papeis de atendimento/profissional continuam fora.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Base, Client, Company, Team, TeamPermission, User
from backend.routes.teams import router as teams_router

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
        tables=[
            Company.__table__, Team.__table__, TeamPermission.__table__,
            User.__table__, Client.__table__,
        ],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    a = Company(name="Clinica A", cnpj="00000000002000")
    b = Company(name="Clinica B", cnpj="00000000002001")
    db.add_all([a, b])
    db.commit()

    db.add_all([
        Team(company_id=a.id, name="Recepcao", code="RECEPCAO"),
        Team(company_id=a.id, name="Clinico", code="CLINICO"),
        Team(company_id=b.id, name="Equipe da B", code="B"),
    ])
    db.commit()

    usuarios = {
        "clinic_admin": User(client_id=1, company_id=a.id, name="Admin Clinica",
                             email="ca@a.com", password="x", role="clinic_admin", is_active=True),
        "admin": User(client_id=1, company_id=a.id, name="Admin", email="ad@a.com",
                      password="x", role="admin", is_active=True),
        "manager": User(client_id=1, company_id=a.id, name="Gerente", email="ge@a.com",
                        password="x", role="manager", is_active=True),
        "staff": User(client_id=1, company_id=a.id, name="Recepcao", email="re@a.com",
                      password="x", role="staff", is_active=True),
    }
    db.add_all(list(usuarios.values()))
    db.commit()
    dono = Client(email="dono@a.com", password="x", company_id=a.id,
                  ownership_company_id=a.id, is_active=True)
    db.add(dono)
    db.commit()
    return {"a": a, "b": b, "usuarios": usuarios, "dono": dono}


@pytest.fixture()
def app(db):
    app = FastAPI()
    app.include_router(teams_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return app


def _get(app, usuario):
    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app).get("/api/teams/")


def test_clinic_admin_lista_os_perfis_da_propria_clinica(cenario, app):
    """Era 403. Sem esta lista o seletor de perfil da tela de acessos vem vazio."""
    resposta = _get(app, cenario["usuarios"]["clinic_admin"])
    assert resposta.status_code == 200, resposta.text
    nomes = {t["name"] for t in resposta.json()}
    assert nomes == {"Recepcao", "Clinico"}, nomes


def test_clinic_admin_nao_ve_equipe_de_outra_clinica(cenario, app):
    corpo = _get(app, cenario["usuarios"]["clinic_admin"]).json()
    assert all(t["company_id"] == cenario["a"].id for t in corpo)
    assert "Equipe da B" not in {t["name"] for t in corpo}


def test_dono_da_conta_continua_listando(cenario, app):
    assert _get(app, cenario["dono"]).status_code == 200


def test_admin_e_manager_continuam_listando(cenario, app):
    for papel in ("admin", "manager"):
        assert _get(app, cenario["usuarios"][papel]).status_code == 200, papel


def test_staff_continua_sem_acesso(cenario, app):
    assert _get(app, cenario["usuarios"]["staff"]).status_code == 403
