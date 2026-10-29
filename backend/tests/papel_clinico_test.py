"""Os quatro papeis contra uma rota clinica de exemplo (card F1-13).

CRITERIO DE ACEITE DO CARD: teste automatizado com os quatro papeis provando 200
para admin/clinico e 403 para atendimento, e a linha de log gravada e
consultavel.

A rota de exemplo vive AQUI, nao em producao: um endpoint clinico falso no ar so
serviria para confundir. O que vai para producao e a dependency e o helper que
este teste exercita.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import get_db
from backend.models import Base, ClinicalAccessLog, Company, Professional, User
from backend.services.papel_clinico import (
    PAPEIS_COM_PROFISSIONAL_OBRIGATORIO,
    PAPEIS_QUE_VEEM_PRONTUARIO,
    exigir_admin_de_usuarios,
    exigir_papel_clinico,
    listar_acessos,
    pode_ver_prontuario,
    registrar_acesso_clinico,
)


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
        tables=[
            Company.__table__,
            Professional.__table__,
            User.__table__,
            ClinicalAccessLog.__table__,
        ],
    )
    sessao = sessionmaker(bind=eng)()
    # company_slots/clinical_access_log usam PK BigInteger, que no SQLite nao vira
    # rowid autoincremental (em producao e serial). Recriar a tabela do log com
    # INTEGER PRIMARY KEY e concessao do harness, nao mudanca de producao.
    sessao.execute(text("DROP TABLE clinical_access_log"))
    sessao.execute(text(
        """
        CREATE TABLE clinical_access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id BIGINT NOT NULL,
            user_id INTEGER,
            user_email VARCHAR(255) NOT NULL,
            professional_id INTEGER,
            patient_id INTEGER,
            resource VARCHAR(60),
            action VARCHAR(30),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    ))
    sessao.commit()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture()
def empresas(db):
    a = Company(name="Clinica A", cnpj="00000000000600")
    b = Company(name="Clinica B", cnpj="00000000000601")
    db.add_all([a, b])
    db.commit()
    profissionais = {}
    for empresa in (a, b):
        prof = Professional(
            company_id=empresa.id, name=f"Dra. {empresa.name}",
            email=f"prof@{empresa.id}.com", active=True,
        )
        db.add(prof)
        db.commit()
        profissionais[empresa.id] = prof
    return {"a": a, "b": b, "profissionais": profissionais}


def _usuario(db, empresa, papel, email=None):
    # O banco tem CHECK ck_users_papel_clinico_tem_profissional: papel clinico
    # sem profissional e recusado pelo PROPRIO schema (migration 0011). O
    # fixture respeita a regra em vez de contorna-la.
    vinculo = None
    if papel in PAPEIS_COM_PROFISSIONAL_OBRIGATORIO:
        vinculo = (
            db.query(Professional.id)
            .filter(Professional.company_id == empresa.id)
            .scalar()
        )
    u = User(
        client_id=1,
        company_id=empresa.id,
        name=f"Usuario {papel}",
        email=email or f"{papel}@teste.com",
        password="x",
        role=papel,
        professional_id=vinculo,
        is_active=True,
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def app_com_rota_clinica(db):
    """App minimo com UMA rota que le dado clinico usando a guarda real."""
    app = FastAPI()

    @app.get("/exemplo/prontuario")
    def ler_prontuario(
        paciente_id: int,
        sessao=Depends(get_db),
        usuario=Depends(exigir_papel_clinico),
    ):
        registrar_acesso_clinico(
            sessao, usuario, resource="prontuario", action="read", patient_id=paciente_id
        )
        return {"ok": True, "paciente_id": paciente_id}

    @app.get("/exemplo/auditoria")
    def auditoria(sessao=Depends(get_db), usuario=Depends(exigir_admin_de_usuarios)):
        return [
            {"id": r.id, "user_email": r.user_email, "patient_id": r.patient_id}
            for r in listar_acessos(sessao, usuario.company_id)
        ]

    app.dependency_overrides[get_db] = lambda: db
    return app


def _cliente(app, usuario):
    from backend.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app)


# ---------------------------------------------------------------- os 4 papeis

@pytest.mark.parametrize(
    "papel,esperado",
    [
        ("clinic_admin", 200),          # ve o prontuario de toda a clinica
        ("clinical_professional", 200),  # ve os proprios pacientes
        ("service_professional", 403),   # agenda e contato, sem prontuario
        ("admin", 200),                  # administrador da conta
    ],
)
def test_quatro_papeis_na_rota_de_prontuario(db, empresas, app_com_rota_clinica, papel, esperado):
    usuario = _usuario(db, empresas["a"], papel)
    resposta = _cliente(app_com_rota_clinica, usuario).get("/exemplo/prontuario?paciente_id=77")
    assert resposta.status_code == esperado, resposta.text


def test_atendimento_recebe_403_com_orientacao(db, empresas, app_com_rota_clinica):
    usuario = _usuario(db, empresas["a"], "service_professional")
    resposta = _cliente(app_com_rota_clinica, usuario).get("/exemplo/prontuario?paciente_id=1")
    assert resposta.status_code == 403
    assert "não permite acessar este recurso" in resposta.json()["detail"]
    assert "Admin Clínica" in resposta.json()["detail"], "a mensagem diz a quem pedir"


def test_manager_nao_ve_prontuario_por_decisao(db, empresas, app_com_rota_clinica):
    """Gerente comercial entra na lista de negados de proposito."""
    usuario = _usuario(db, empresas["a"], "manager")
    resposta = _cliente(app_com_rota_clinica, usuario).get("/exemplo/prontuario?paciente_id=1")
    assert resposta.status_code == 403


# --------------------------------------------------------------- o log gravado

def test_acesso_autorizado_grava_linha_com_quem_quando_e_paciente(
    db, empresas, app_com_rota_clinica
):
    usuario = _usuario(db, empresas["a"], "clinic_admin", email="admin@clinica.com")
    resposta = _cliente(app_com_rota_clinica, usuario).get("/exemplo/prontuario?paciente_id=4242")
    assert resposta.status_code == 200

    linhas = db.query(ClinicalAccessLog).all()
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha.user_email == "admin@clinica.com"
    assert linha.patient_id == 4242
    assert linha.resource == "prontuario"
    assert linha.action == "read"
    assert linha.company_id == empresas["a"].id
    assert linha.created_at is not None


def test_acesso_negado_nao_grava_log_de_leitura(db, empresas, app_com_rota_clinica):
    """403 nao e leitura: o log registra o que foi LIDO, nao o que foi tentado."""
    usuario = _usuario(db, empresas["a"], "service_professional")
    _cliente(app_com_rota_clinica, usuario).get("/exemplo/prontuario?paciente_id=1")
    assert db.query(ClinicalAccessLog).count() == 0


def test_log_e_consultavel_pelo_admin_e_filtra_por_paciente(db, empresas, app_com_rota_clinica):
    usuario = _usuario(db, empresas["a"], "clinic_admin")
    cliente = _cliente(app_com_rota_clinica, usuario)
    cliente.get("/exemplo/prontuario?paciente_id=10")
    cliente.get("/exemplo/prontuario?paciente_id=20")

    todos = cliente.get("/exemplo/auditoria").json()
    assert len(todos) == 2
    assert {t["patient_id"] for t in todos} == {10, 20}

    filtrando = listar_acessos(db, empresas["a"].id, patient_id=20)
    assert len(filtrando) == 1 and filtrando[0].patient_id == 20


def test_log_de_uma_clinica_nao_aparece_na_outra(db, empresas):
    admin_a = _usuario(db, empresas["a"], "clinic_admin", email="a@a.com")
    admin_b = _usuario(db, empresas["b"], "clinic_admin", email="b@b.com")
    registrar_acesso_clinico(db, admin_a, resource="prontuario", patient_id=1)
    registrar_acesso_clinico(db, admin_b, resource="prontuario", patient_id=2)

    da_a = listar_acessos(db, empresas["a"].id)
    assert [l.user_email for l in da_a] == ["a@a.com"]


def test_auditoria_so_para_admin_da_clinica(db, empresas, app_com_rota_clinica):
    clinico = _usuario(db, empresas["a"], "clinical_professional")
    resposta = _cliente(app_com_rota_clinica, clinico).get("/exemplo/auditoria")
    assert resposta.status_code == 403


# --------------------------------------------------------- falha fechada

def test_sem_empresa_o_log_nao_e_gravado_e_a_leitura_falha(db):
    """Fail closed: acesso clinico sem registro nao pode acontecer (LGPD)."""
    class UsuarioSemEmpresa:
        id = 1
        email = "semempresa@teste.com"
        role = "clinic_admin"
        company_id = None

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as erro:
        registrar_acesso_clinico(db, UsuarioSemEmpresa(), resource="prontuario")
    assert erro.value.status_code == 400
    assert db.query(ClinicalAccessLog).count() == 0


def test_pode_ver_prontuario_resume_a_regra():
    assert pode_ver_prontuario("clinic_admin")
    assert pode_ver_prontuario("clinical_professional")
    assert pode_ver_prontuario("admin")
    assert not pode_ver_prontuario("service_professional")
    assert not pode_ver_prontuario("manager")
    assert not pode_ver_prontuario(None)
    assert set(PAPEIS_QUE_VEEM_PRONTUARIO) == {"admin", "clinic_admin", "clinical_professional"}
