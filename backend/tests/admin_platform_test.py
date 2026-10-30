"""Painel da plataforma: o admin master ve e administra TODOS os clientes.

O defeito que este arquivo tranca: antes so existia `PUT /api/company/flag`, que
aplica na empresa em que o admin ESTA. Nao havia como listar as empresas da
plataforma — entao "ter acesso a todos os clientes" era impossivel por construcao.

Cobre tambem a extracao de `aplicar_modalidade`: as duas portas (empresa atual e
empresa escolhida) tem de obedecer a MESMA regra de rebaixamento.
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
from backend.models import (
    Agenda,
    Agendamento,
    Base,
    Client,
    ClientCompany,
    Company,
    Professional,
    User,
)
from backend.routes import admin_platform_routes
from backend.routes import company_flag_routes

if not getattr(SQLiteTypeCompiler, "_hermes_jsonb_patch", False):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"
    SQLiteTypeCompiler._hermes_jsonb_patch = True

CHEFE = "chefe@plataforma.com"

TABELAS = [
    Company.__table__,
    Professional.__table__,
    User.__table__,
    Client.__table__,
    ClientCompany.__table__,
    Agenda.__table__,
    Agendamento.__table__,
]


@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng, tables=TABELAS)
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def cenario(db):
    a = Company(name="Clinica A", cnpj="00000000000900", professional_tier="up_to_4", max_professionals=4)
    b = Company(name="Clinica B", cnpj="00000000000901", professional_tier="mono", max_professionals=1)
    db.add_all([a, b])
    db.commit()

    db.add_all([
        Professional(company_id=a.id, name="Dra. Ana", email="ana@a.com", active=True),
        Professional(company_id=a.id, name="Dr. Caio", email="caio@a.com", active=True),
        Professional(company_id=a.id, name="Dr. Inativo", email="off@a.com", active=False),
        Professional(company_id=b.id, name="Dra. Bia", email="bia@b.com", active=True),
    ])
    db.commit()

    chefe = Client(
        email=CHEFE, password="x", company_id=a.id,
        ownership_company_id=a.id, is_active=True,
    )
    db.add(chefe)
    db.commit()
    db.add(ClientCompany(client_id=chefe.id, company_id=a.id))
    db.add(User(client_id=chefe.id, company_id=a.id, name="Recepcao", email="rec@a.com",
                password="x", role="staff", is_active=True))
    db.add(User(client_id=chefe.id, company_id=a.id, name="Saiu", email="saiu@a.com",
                password="x", role="staff", is_active=False))
    agenda = Agenda(company_id=a.id, name="Dra. Ana", slot_duration=30, active=True)
    db.add(agenda)
    db.commit()
    for i in range(3):
        db.add(Agendamento(client_id=1, lead_id=1, agenda_id=agenda.id, nome=f"P{i}"))
    db.commit()
    return {"a": a, "b": b, "chefe": chefe}


@pytest.fixture()
def app(db):
    app = FastAPI()
    app.include_router(admin_platform_routes.router)
    app.include_router(company_flag_routes.router)
    app.dependency_overrides[get_db] = lambda: db
    return app


def _cliente(app, usuario, monkeypatch, admin=True):
    monkeypatch.setenv("ADMIN_EMAILS", CHEFE if admin else "")
    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app)


# ------------------------------------------------------------------- /eu
def test_eu_diz_que_sou_admin_master(cenario, app, monkeypatch):
    corpo = _cliente(app, cenario["chefe"], monkeypatch).get("/api/admin/eu").json()
    assert corpo["admin_plataforma"] is True, corpo
    assert corpo["email"] == CHEFE


def test_eu_nao_da_403_para_quem_nao_e_admin(cenario, app, monkeypatch):
    """O menu pergunta isto no boot do layout: 403 aqui viraria erro na cara de
    todo usuario comum."""
    usuario = User(client_id=1, company_id=cenario["a"].id, name="Recepcao",
                   email="rec@a.com", password="x", role="staff", is_active=True)
    resposta = _cliente(app, usuario, monkeypatch, admin=False).get("/api/admin/eu")
    assert resposta.status_code == 200
    assert resposta.json()["admin_plataforma"] is False


# ------------------------------------------------------------ /companies
def test_lista_todas_as_empresas_com_os_numeros(cenario, app, monkeypatch):
    corpo = _cliente(app, cenario["chefe"], monkeypatch).get("/api/admin/companies").json()
    assert corpo["total_empresas"] == 2, corpo
    por_id = {e["id"]: e for e in corpo["empresas"]}

    a = por_id[cenario["a"].id]
    assert a["profissionais_ativos"] == 2, "o inativo nao conta como ativo"
    assert a["profissionais_total"] == 3
    assert a["usuarios_ativos"] == 1, "o usuario inativo nao conta"
    assert a["usuarios_total"] == 2
    assert a["agendas_ativas"] == 1
    assert a["agendamentos_total"] == 3
    assert a["empresa_atual"] is True
    assert a["vinculada_ao_meu_login"] is True

    b = por_id[cenario["b"].id]
    assert b["professional_tier"] == "mono" and b["max_professionals"] == 1
    assert b["profissionais_ativos"] == 1
    assert b["empresa_atual"] is False
    assert b["vinculada_ao_meu_login"] is False


def test_quem_nao_e_admin_nao_lista(cenario, app, monkeypatch):
    usuario = User(client_id=1, company_id=cenario["a"].id, name="Recepcao",
                   email="rec@a.com", password="x", role="staff", is_active=True)
    resposta = _cliente(app, usuario, monkeypatch, admin=False).get("/api/admin/companies")
    assert resposta.status_code == 403


# --------------------------------------------------------------- /entrar
def test_entrar_cria_vinculo_e_move_o_contexto(db, cenario, app, monkeypatch):
    resposta = _cliente(app, cenario["chefe"], monkeypatch).post(
        f"/api/admin/companies/{cenario['b'].id}/entrar"
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["vinculo_criado"] is True

    db.refresh(cenario["chefe"])
    assert cenario["chefe"].company_id == cenario["b"].id
    assert (
        db.query(ClientCompany)
        .filter(ClientCompany.client_id == cenario["chefe"].id)
        .filter(ClientCompany.company_id == cenario["b"].id)
        .first()
        is not None
    ), "sem o vinculo o select do frontend responderia 404"

    # entrar de novo nao duplica vinculo
    segunda = _cliente(app, cenario["chefe"], monkeypatch).post(
        f"/api/admin/companies/{cenario['b'].id}/entrar"
    )
    assert segunda.json()["vinculo_criado"] is False


def test_entrar_em_empresa_inexistente_e_404(cenario, app, monkeypatch):
    resposta = _cliente(app, cenario["chefe"], monkeypatch).post("/api/admin/companies/9999/entrar")
    assert resposta.status_code == 404


def test_usuario_de_equipe_nao_troca_de_empresa(cenario, app, monkeypatch):
    usuario = User(client_id=1, company_id=cenario["a"].id, name="Recepcao",
                   email="rec@a.com", password="x", role="staff", is_active=True)
    monkeypatch.setenv("ADMIN_EMAILS", "outro@x.com")
    # nem admin master e: 403 antes de qualquer logica
    resposta = _cliente(app, usuario, monkeypatch, admin=False).post(
        f"/api/admin/companies/{cenario['b'].id}/entrar"
    )
    assert resposta.status_code == 403


# ---------------------------------------------------------- /modalidade
def test_modalidade_de_outra_empresa_sem_trocar_de_contexto(db, cenario, app, monkeypatch):
    resposta = _cliente(app, cenario["chefe"], monkeypatch).put(
        f"/api/admin/companies/{cenario['b'].id}/modalidade",
        json={"professional_tier": "up_to_10"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["professional_tier"] == "up_to_10"
    assert resposta.json()["max_professionals"] == 10

    db.refresh(cenario["b"])
    assert cenario["b"].max_professionals == 10
    db.refresh(cenario["chefe"])
    assert cenario["chefe"].company_id == cenario["a"].id, "nao pode trocar o contexto so por mudar modalidade"


def test_rebaixamento_abaixo_dos_ativos_e_bloqueado_pelo_painel(db, cenario, app, monkeypatch):
    """Empresa A tem 2 profissionais ativos: mono (limite 1) tem de ser recusado."""
    resposta = _cliente(app, cenario["chefe"], monkeypatch).put(
        f"/api/admin/companies/{cenario['a'].id}/modalidade",
        json={"professional_tier": "mono"},
    )
    assert resposta.status_code == 409, resposta.text
    assert "2 profissionais ativos" in resposta.json()["detail"]
    db.refresh(cenario["a"])
    assert cenario["a"].max_professionals == 4, "nada pode ser alterado no bloqueio"


def test_reducao_sem_confirmar_pede_confirmacao(db, cenario, app, monkeypatch):
    # B tem 1 ativo e hoje limite 1; sobe para 10 e tenta voltar sem confirmar
    cliente = _cliente(app, cenario["chefe"], monkeypatch)
    cliente.put(f"/api/admin/companies/{cenario['b'].id}/modalidade", json={"professional_tier": "up_to_10"})
    sem_confirmar = cliente.put(
        f"/api/admin/companies/{cenario['b'].id}/modalidade", json={"professional_tier": "up_to_4"}
    )
    assert sem_confirmar.status_code == 409
    assert "confirmar=true" in sem_confirmar.json()["detail"]

    com_confirmar = cliente.put(
        f"/api/admin/companies/{cenario['b'].id}/modalidade",
        json={"professional_tier": "up_to_4", "confirmar": True},
    )
    assert com_confirmar.status_code == 200
    db.refresh(cenario["b"])
    assert cenario["b"].max_professionals == 4


def test_a_rota_antiga_do_flag_continua_com_a_mesma_regra(db, cenario, app, monkeypatch):
    """A extracao de `aplicar_modalidade` nao pode ter mudado o comportamento do
    PUT /api/company/flag (empresa em que o admin esta)."""
    cliente = _cliente(app, cenario["chefe"], monkeypatch)
    ok = cliente.put("/api/company/flag", json={"professional_tier": "up_to_10"})
    assert ok.status_code == 200, ok.text
    db.refresh(cenario["a"])
    assert cenario["a"].max_professionals == 10

    bloqueio = cliente.put("/api/company/flag", json={"professional_tier": "mono"})
    assert bloqueio.status_code == 409, bloqueio.text
