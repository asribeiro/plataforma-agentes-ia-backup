"""Usuarios da clinica: papel + vinculo com profissional (card F1-12).

A regra que este arquivo tranca: `clinical_professional` e `service_professional`
NAO existem sem um profissional vinculado. Sem isso o sistema nao sabe de quem e
o usuario logado, e "cada profissional so ve os seus pacientes" (F1-13) fica
impossivel de implementar depois.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import get_db
from backend.models import Base, Company, Professional, User
from backend.routes.clinic_users_routes import router as clinic_users_router


@pytest.fixture()
def db():
    # check_same_thread=False + StaticPool: o TestClient roda a app em OUTRA
    # thread, e o SQLite em memoria e por conexao. Sem isso o teste falha com
    # "SQLite objects created in a thread can only be used in that same thread"
    # e com "no such table" — erro de harness, nao do codigo sob teste.
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        eng,
        tables=[Company.__table__, Professional.__table__, User.__table__],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    a = Company(name="Clinica A", cnpj="00000000000700")
    b = Company(name="Clinica B", cnpj="00000000000701")
    db.add_all([a, b])
    db.commit()

    ativa = Professional(company_id=a.id, name="Dra. Ana", email="ana@a.com", active=True)
    inativa = Professional(company_id=a.id, name="Dr. Inativo", email="off@a.com", active=False)
    de_outra = Professional(company_id=b.id, name="Dr. Beto", email="beto@b.com", active=True)
    db.add_all([ativa, inativa, de_outra])
    db.commit()

    admin = User(
        client_id=1, company_id=a.id, name="Admin Clinica", email="admin@a.com",
        password="x", role="clinic_admin", is_active=True,
    )
    # service_professional EXIGE vinculo: o CHECK do banco recusa sem ele.
    atendente = User(
        client_id=1, company_id=a.id, name="Atendente", email="at@a.com",
        password="x", role="service_professional", professional_id=ativa.id,
        is_active=True,
    )
    db.add_all([admin, atendente])
    db.commit()
    return {"a": a, "b": b, "ativa": ativa, "inativa": inativa,
            "de_outra": de_outra, "admin": admin, "atendente": atendente}


@pytest.fixture()
def app(db):
    app = FastAPI()
    app.include_router(clinic_users_router)
    app.dependency_overrides[get_db] = lambda: db
    return app


def _cliente(app, usuario):
    from backend.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app)


# --------------------------------------------------------------------- guarda

def test_atendimento_nao_administra_usuarios(db, cenario, app):
    resposta = _cliente(app, cenario["atendente"]).get("/api/clinic/users")
    assert resposta.status_code == 403
    assert "Admin Clínica" in resposta.json()["detail"]


def test_admin_lista_usuarios_da_propria_clinica(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).get("/api/clinic/users")
    assert resposta.status_code == 200
    emails = {u["email"] for u in resposta.json()}
    assert emails == {"admin@a.com", "at@a.com"}, "so a propria clinica"


def test_papeis_avisam_quem_exige_vinculo(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).get("/api/clinic/users/papeis")
    assert resposta.status_code == 200
    por_papel = {p["role"]: p for p in resposta.json()}
    assert por_papel["clinical_professional"]["exige_profissional"] is True
    assert por_papel["service_professional"]["exige_profissional"] is True
    assert por_papel["clinic_admin"]["exige_profissional"] is False


# ------------------------------------------------------------------ validacao

def test_papel_clinico_sem_profissional_e_recusado(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Novo Clinico", "email": "novo@a.com", "password": "senha12345",
              "role": "clinical_professional"},
    )
    assert resposta.status_code == 409
    assert "precisa estar vinculado a um profissional" in resposta.json()["detail"]


def test_profissional_de_outra_empresa_e_recusado(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Clinico", "email": "c@a.com", "password": "senha12345",
              "role": "clinical_professional", "professional_id": cenario["de_outra"].id},
    )
    assert resposta.status_code == 404


def test_profissional_inativo_e_recusado(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Clinico", "email": "c2@a.com", "password": "senha12345",
              "role": "clinical_professional", "professional_id": cenario["inativa"].id},
    )
    assert resposta.status_code == 409
    assert "inativo" in resposta.json()["detail"]


def test_papel_inexistente_e_recusado_com_a_lista(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Alguem", "email": "x@a.com", "password": "senha12345",
              "role": "dentista"},
    )
    assert resposta.status_code == 422
    assert "clinical_professional" in resposta.json()["detail"]


def test_papel_administrativo_nao_aceita_vinculo_clinico(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Admin Dois", "email": "adm2@a.com", "password": "senha12345",
              "role": "clinic_admin", "professional_id": cenario["ativa"].id},
    )
    assert resposta.status_code == 409
    assert "não usa vínculo" in resposta.json()["detail"]


def test_email_repetido_e_recusado(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Repetido", "email": "admin@a.com", "password": "senha12345",
              "role": "clinic_admin"},
    )
    assert resposta.status_code == 409


def test_cadastro_valido_grava_papel_e_vinculo(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Dra. Ana", "email": "ana.user@a.com", "password": "senha12345",
              "role": "clinical_professional", "professional_id": cenario["ativa"].id},
    )
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["role"] == "clinical_professional"
    assert corpo["professional_id"] == cenario["ativa"].id
    assert corpo["professional_nome"] == "Dra. Ana"
    assert "prontuário" in corpo["role_rotulo"].lower()


# --------------------------------------------------------------------- edicao

def test_trocar_papel_clinico_para_admin_limpa_o_vinculo(db, cenario, app):
    criado = _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Clinica Um", "email": "um@a.com", "password": "senha12345",
              "role": "clinical_professional", "professional_id": cenario["ativa"].id},
    ).json()

    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{criado['id']}",
        json={"role": "clinic_admin", "professional_id": None},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["role"] == "clinic_admin"
    assert resposta.json()["professional_id"] is None


def test_ultimo_admin_nao_pode_ser_rebaixado(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{cenario['admin'].id}",
        json={"role": "staff"},
    )
    assert resposta.status_code == 409
    assert "último administrador" in resposta.json()["detail"]


def test_ultimo_admin_nao_pode_ser_desativado(db, cenario, app):
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{cenario['admin'].id}",
        json={"is_active": False},
    )
    assert resposta.status_code == 409


def test_com_dois_admins_o_primeiro_pode_ser_rebaixado(db, cenario, app):
    _cliente(app, cenario["admin"]).post(
        "/api/clinic/users",
        json={"name": "Admin Dois", "email": "adm2@a.com", "password": "senha12345",
              "role": "clinic_admin"},
    )
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{cenario['admin'].id}",
        json={"role": "staff"},
    )
    assert resposta.status_code == 200, resposta.text


def test_usuario_de_outra_clinica_nao_e_editavel(db, cenario, app):
    estranho = User(
        client_id=1, company_id=cenario["b"].id, name="De Fora", email="fora@b.com",
        password="x", role="clinic_admin", is_active=True,
    )
    db.add(estranho)
    db.commit()
    resposta = _cliente(app, cenario["admin"]).patch(
        f"/api/clinic/users/{estranho.id}", json={"name": "Tentativa"}
    )
    assert resposta.status_code == 404
