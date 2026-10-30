"""Regressao do 500 em GET /api/users/ com papeis clinicos.

Antes do conserto: o schema de resposta restringia `role` a admin/manager/staff e a
serializacao da LISTA estourava (500) na primeira pessoa com papel clinico — a tela
"Minha Empresa" caia para 0 usuarios e alerta vermelho. Estes testes falham sem o
conserto, e o de POST falha se apenas a resposta for ampliada (o corpo tambem
precisa aceitar os papeis que o banco aceita).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# O SQLite do teste nao conhece JSONB (coluna `billing_profile` de `clients`).
# Ensina o dialeto de teste a escrever JSON no lugar de JSONB.
SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"

from backend.auth import get_current_user
from backend.db import Base, get_db
from backend.main import app
from backend.models import Client, ClientCompany, Company, Team, TeamPermission, User

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Sessao = sessionmaker(bind=engine, autoflush=False, autocommit=False)


TABELAS = [
    Company.__table__,
    Client.__table__,
    ClientCompany.__table__,
    User.__table__,
    Team.__table__,
    TeamPermission.__table__,
]


def montar():
    # Cada teste comeca de banco vazio: o engine e compartilhado (StaticPool) e
    # sem o drop a segunda chamada colide com os e-mails unicos da primeira.
    Base.metadata.drop_all(bind=engine, tables=TABELAS)
    Base.metadata.create_all(bind=engine, tables=TABELAS)
    db = Sessao()
    empresa = Company(name="Clinica Teste", cnpj="11111111111111")
    db.add(empresa)
    db.flush()
    dono = Client(
        email="dono@teste.com",
        password="x",
        company_id=empresa.id,
        ownership_company_id=empresa.id,
        is_active=True,
    )
    db.add(dono)
    db.flush()
    # Sem o vinculo em client_companies o master nao tem acesso a empresa:
    # validate_company_access responde 403 (e a lista dependeria dele).
    db.add(ClientCompany(client_id=dono.id, company_id=empresa.id))
    db.flush()
    time = Team(company_id=empresa.id, name="Recepcao", code="REC")
    db.add(time)
    db.flush()
    db.add_all(
        [
            User(
                company_id=empresa.id,
                client_id=dono.id,
                name="Dra Clinica",
                email="clinica@teste.com",
                password="x",
                # clinic_admin tambem e papel clinico (o validador antigo recusava)
                # e, ao contrario de clinical_professional, nao exige vinculo com
                # profissional — o CHECK do banco cobra o vinculo so dos papeis de
                # atendimento.
                role="clinic_admin",
                is_active=True,
            ),
            User(
                company_id=empresa.id,
                client_id=dono.id,
                name="Recepcao",
                email="recepcao@teste.com",
                password="x",
                role="staff",
                is_active=True,
                team_id=time.id,
            ),
        ]
    )
    db.commit()
    ids = {"company_id": empresa.id, "client_id": dono.id}
    db.close()
    return ids


def cliente(dono_id):
    def override():
        db = Sessao()
        try:
            return db.query(Client).filter(Client.id == dono_id).first()
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = override

    def override_db():
        db = Sessao()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app, base_url="https://meu-agente.transformativa.com.br")


def test_lista_com_papel_clinico_nao_estoura():
    ids = montar()
    api = cliente(ids["client_id"])
    resposta = api.get("/api/users/", params={"company_id": ids["company_id"]})
    assert resposta.status_code == 200, resposta.text
    papeis = sorted(u["role"] for u in resposta.json())
    assert papeis == ["clinic_admin", "staff"], papeis


def test_resposta_preserva_o_papel_clinico_sem_renomear():
    """Se alguem "consertar" mapeando papel clinico para staff, isto pega."""
    ids = montar()
    api = cliente(ids["client_id"])
    resposta = api.get("/api/users/", params={"company_id": ids["company_id"]})
    assert resposta.status_code == 200, resposta.text
    por_email = {u["email"]: u for u in resposta.json()}
    assert por_email["clinica@teste.com"]["role"] == "clinic_admin"


def test_criar_usuario_com_papel_clinico_e_aceito():
    ids = montar()
    api = cliente(ids["client_id"])
    resposta = api.post(
        "/api/users/",
        json={
            "email": "novo@teste.com",
            "name": "Novo Clinico",
            "role": "clinic_admin",
            "company_id": ids["company_id"],
            "password": "SenhaForte123!",
            "confirm_password": "SenhaForte123!",
        },
    )
    assert resposta.status_code in (200, 201), resposta.text
    assert resposta.json()["role"] == "clinic_admin"


def test_papel_inventado_continua_recusado():
    """Ampliar para os papeis reais nao pode virar 'aceita qualquer string'."""
    ids = montar()
    api = cliente(ids["client_id"])
    resposta = api.post(
        "/api/users/",
        json={
            "email": "inventado@teste.com",
            "name": "Inventado",
            "role": "super_usuario",
            "company_id": ids["company_id"],
            "password": "SenhaForte123!",
            "confirm_password": "SenhaForte123!",
        },
    )
    assert resposta.status_code == 422, resposta.status_code
