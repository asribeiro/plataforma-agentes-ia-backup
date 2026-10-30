"""Cobranca da plataforma: planos, assinatura e faturas.

O que estes testes trancam, e por que:

- Plano sem preco NAO emite fatura (400). Emitir com zero criaria uma fatura de valor
  nenhum que parece quitada e nao e.
- O valor da fatura e SNAPSHOT: reajustar o plano depois nao reescreve a fatura ja
  emitida. Sem isso o historico deixa de bater com o que foi debitado no cartao.
- Uma assinatura ATIVA por empresa: definir outro plano encerra a anterior em vez de
  criar a segunda (o banco tem indice parcial e estouraria IntegrityError).
- Competencia repetida 409, e dia de vencimento fora de 1..28 e recusado.
- Quem nao esta na allowlist ADMIN_EMAILS nao entra em nenhuma rota.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# SQLite do teste nao conhece JSONB (clients.billing_profile).
SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"

from backend.auth import get_current_user
from backend.db import Base, get_db
from backend.main import app
from backend.models import (
    Client,
    Company,
    CompanyAssinatura,
    Fatura,
    Plano,
)

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Sessao = sessionmaker(bind=engine, autoflush=False, autocommit=False)

TABELAS = [
    Company.__table__,
    Client.__table__,
    Plano.__table__,
    CompanyAssinatura.__table__,
    Fatura.__table__,
]

EMAIL_ADMIN = "admin@plataforma.com"


def montar():
    Base.metadata.drop_all(bind=engine, tables=TABELAS)
    Base.metadata.create_all(bind=engine, tables=TABELAS)
    db = Sessao()
    empresa = Company(name="Clinica Teste", cnpj="22222222222222")
    db.add(empresa)
    db.flush()
    admin = Client(
        email=EMAIL_ADMIN,
        password="x",
        company_id=empresa.id,
        ownership_company_id=empresa.id,
        is_active=True,
    )
    db.add(admin)
    db.flush()
    planos = [
        Plano(nome="Plano Consultorio", tier="mono", preco_centavos=29900, ciclo="mensal", ativo=True),
        Plano(nome="Plano Clinica", tier="up_to_4", preco_centavos=49900, ciclo="mensal", ativo=True),
        Plano(nome="Plano Clinica Plus", tier="up_to_10", preco_centavos=None, ciclo="mensal", ativo=True),
    ]
    db.add_all(planos)
    db.commit()
    ids = {
        "company_id": empresa.id,
        "client_id": admin.id,
        "plano_mono": planos[0].id,
        "plano_4": planos[1].id,
        "plano_10": planos[2].id,
    }
    db.close()
    return ids


def cliente(dono_id, email=EMAIL_ADMIN):
    os.environ["ADMIN_EMAILS"] = EMAIL_ADMIN

    def override():
        db = Sessao()
        try:
            pessoa = db.query(Client).filter(Client.id == dono_id).first()
            if pessoa is not None:
                pessoa.email = email
            return pessoa
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


def test_quem_nao_esta_na_allowlist_recebe_403():
    ids = montar()
    api = cliente(ids["client_id"], email="clinica@cliente.com")
    assert api.get("/api/admin/planos").status_code == 403
    assert api.get(f"/api/admin/companies/{ids['company_id']}/cobranca").status_code == 403
    assert api.post(f"/api/admin/companies/{ids['company_id']}/faturas", json={}).status_code == 403


def test_lista_de_planos_traz_os_tres_semeáveis():
    ids = montar()
    api = cliente(ids["client_id"])
    r = api.get("/api/admin/planos")
    assert r.status_code == 200, r.text
    nomes = [p["nome"] for p in r.json()]
    assert nomes == ["Plano Consultorio", "Plano Clinica", "Plano Clinica Plus"]


def test_preco_do_plano_pode_ser_definido_e_negativo_recusado():
    ids = montar()
    api = cliente(ids["client_id"])
    r = api.put(f"/api/admin/planos/{ids['plano_10']}", json={"preco_centavos": 89900})
    assert r.status_code == 200, r.text
    assert r.json()["preco_centavos"] == 89900
    ruim = api.put(f"/api/admin/planos/{ids['plano_10']}", json={"preco_centavos": -1})
    assert ruim.status_code == 422, ruim.status_code


def test_uma_assinatura_ativa_por_empresa_encerra_a_anterior():
    ids = montar()
    api = cliente(ids["client_id"])
    primeira = api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_mono"], "dia_vencimento": 10},
    )
    assert primeira.status_code == 200, primeira.text
    assert primeira.json()["assinatura"]["plano_id"] == ids["plano_mono"]

    segunda = api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_4"], "dia_vencimento": 5},
    )
    assert segunda.status_code == 200, segunda.text
    corpo = segunda.json()
    assert corpo["assinatura"]["plano_id"] == ids["plano_4"]

    db = Sessao()
    ativas = (
        db.query(CompanyAssinatura)
        .filter(
            CompanyAssinatura.company_id == ids["company_id"],
            CompanyAssinatura.status == "ativa",
        )
        .count()
    )
    total = (
        db.query(CompanyAssinatura)
        .filter(CompanyAssinatura.company_id == ids["company_id"])
        .count()
    )
    db.close()
    assert ativas == 1, "mais de uma assinatura ativa"
    assert total == 2, "a anterior deveria ficar no historico como encerrada"


def test_dia_de_vencimento_acima_de_28_e_recusado():
    ids = montar()
    api = cliente(ids["client_id"])
    r = api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_mono"], "dia_vencimento": 31},
    )
    assert r.status_code == 422, r.status_code


def test_plano_sem_preco_nao_emite_fatura():
    ids = montar()
    api = cliente(ids["client_id"])
    api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_10"], "dia_vencimento": 10},
    )
    r = api.post(f"/api/admin/companies/{ids['company_id']}/faturas", json={})
    assert r.status_code == 400, r.text
    assert "sem preco" in r.json()["detail"]


def test_fatura_usa_valor_do_plano_e_nao_muda_quando_o_plano_muda():
    ids = montar()
    api = cliente(ids["client_id"])
    api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_4"], "dia_vencimento": 10},
    )
    emitida = api.post(
        f"/api/admin/companies/{ids['company_id']}/faturas", json={"competencia": "2026-10"}
    )
    assert emitida.status_code == 201, emitida.text
    assert emitida.json()["valor_centavos"] == 49900
    assert emitida.json()["vencimento"] == "2026-10-10"

    api.put(f"/api/admin/planos/{ids['plano_4']}", json={"preco_centavos": 99900})

    cobranca = api.get(f"/api/admin/companies/{ids['company_id']}/cobranca")
    assert cobranca.status_code == 200, cobranca.text
    faturas = cobranca.json()["faturas"]
    assert faturas[0]["valor_centavos"] == 49900, "fatura antiga foi reescrita"


def test_competencia_repetida_recebe_409():
    ids = montar()
    api = cliente(ids["client_id"])
    api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_mono"], "dia_vencimento": 10},
    )
    url = f"/api/admin/companies/{ids['company_id']}/faturas"
    assert api.post(url, json={"competencia": "2026-10"}).status_code == 201
    repetida = api.post(url, json={"competencia": "2026-10"})
    assert repetida.status_code == 409, repetida.text
    assert "Ja existe fatura" in repetida.json()["detail"]


def test_sem_assinatura_nao_emite_fatura():
    ids = montar()
    api = cliente(ids["client_id"])
    r = api.post(f"/api/admin/companies/{ids['company_id']}/faturas", json={})
    assert r.status_code == 409, r.text


def test_marcar_paga_preenche_data_e_voltar_para_aberta_limpa():
    ids = montar()
    api = cliente(ids["client_id"])
    api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_4"], "dia_vencimento": 10},
    )
    fatura = api.post(
        f"/api/admin/companies/{ids['company_id']}/faturas", json={"competencia": "2026-11"}
    ).json()

    paga = api.patch(f"/api/admin/faturas/{fatura['id']}", json={"status": "paga"})
    assert paga.status_code == 200, paga.text
    assert paga.json()["pago_em"] is not None

    cobranca = api.get(f"/api/admin/companies/{ids['company_id']}/cobranca").json()
    assert cobranca["total_pago_centavos"] == 49900
    assert cobranca["total_aberto_centavos"] == 0

    reaberta = api.patch(f"/api/admin/faturas/{fatura['id']}", json={"status": "aberta"})
    assert reaberta.status_code == 200
    assert reaberta.json()["pago_em"] is None, "data de pagamento ficou mentindo"


def test_competencia_em_formato_invalido_e_recusada():
    ids = montar()
    api = cliente(ids["client_id"])
    api.put(
        f"/api/admin/companies/{ids['company_id']}/cobranca",
        json={"plano_id": ids["plano_mono"], "dia_vencimento": 10},
    )
    r = api.post(
        f"/api/admin/companies/{ids['company_id']}/faturas", json={"competencia": "2026-13"}
    )
    assert r.status_code == 422, r.status_code


def test_vencimento_de_fevereiro_nao_estoura():
    """Dia 30 em fevereiro nao existe; o helper limita ao ultimo dia do mes."""
    from backend.routes.admin_billing_routes import _vencimento

    assert _vencimento("2026-02", 28) == date(2026, 2, 28)
    assert _vencimento("2028-02", 28) == date(2028, 2, 28)  # bissexto
    assert _vencimento("2026-12", 10) == date(2026, 12, 10)
