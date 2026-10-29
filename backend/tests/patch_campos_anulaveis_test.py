"""Patch parcial: null explicito LIMPA, campo ausente PRESERVA.

Defeito que este arquivo tranca: os PUT de procedimentos e profissionais faziam
`if valor is not None: setattr(...)`. Resultado em producao seria (e era) este:
o dono da clinica removia o preco de um procedimento na tela, a tela dizia
"preco removido" e o agente continuava citando valor ao paciente — porque o
null nunca chegava na coluna.

A duvida que o codigo antigo nao sabia responder:
    {"name": "Clareamento"}   -> nao falou do preco  -> PRESERVAR
    {"price_cents": null}     -> pediu para apagar   -> APAGAR
"""
import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Base,
    Company,
    Professional,
    ProfessionalService,
    Service,
)
from backend.routes.professionals_routes import (
    ProfessionalPatch,
    atualizar as atualizar_profissional,
)
from backend.routes.services_routes import ServicePatch, atualizar as atualizar_servico
from backend.utils.patch_utils import aplicar_patch, campos_enviados


# --------------------------------------------------------------- helper puro

class Alvo:
    """Objeto bobo com os MESMOS nomes de campo do schema."""

    def __init__(self):
        self.price_cents = 25000
        self.duration_minutes = 30


def test_campo_ausente_nao_toca_no_valor():
    dados = ServicePatch(name="Clareamento")
    alvo = Alvo()
    aplicar_patch(alvo, dados, ("duration_minutes", "price_cents"), anulaveis=("price_cents",))
    assert alvo.price_cents == 25000 and alvo.duration_minutes == 30


def test_null_em_campo_anulavel_apaga():
    dados = ServicePatch(price_cents=None)
    alvo = Alvo()
    aplicar_patch(alvo, dados, ("price_cents",), anulaveis=("price_cents",))
    assert alvo.price_cents is None


def test_null_em_campo_obrigatorio_e_ignorado():
    """duration_minutes e NOT NULL: aplicar null trocaria um dado por um 500."""
    dados = ServicePatch(duration_minutes=None)
    alvo = Alvo()
    aplicar_patch(alvo, dados, ("duration_minutes",), anulaveis=("price_cents",))
    assert alvo.duration_minutes == 30


def test_campos_enviados_distingue_ausente_de_null():
    assert campos_enviados(ServicePatch(price_cents=None)) == {"price_cents"}
    assert campos_enviados(ServicePatch(name="XY")) == {"name"}


# ------------------------------------------------------- integracao nas rotas

@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        eng,
        tables=[
            Company.__table__,
            Service.__table__,
            Professional.__table__,
            ProfessionalService.__table__,
        ],
    )
    sessao = sessionmaker(bind=eng)()
    try:
        yield sessao
    finally:
        sessao.close()


class UsuarioFalso:
    def __init__(self, company_id):
        self.company_id = company_id


@pytest.fixture()
def cenario(db):
    empresa = Company(name="Clinica Teste", cnpj="00000000000300")
    db.add(empresa)
    db.commit()
    proc = Service(
        company_id=empresa.id, name="Clareamento", duration_minutes=60,
        price_cents=25000, is_evaluation=False, active=True,
    )
    prof = Professional(
        company_id=empresa.id, name="Dra. Ana", email="ana@teste.com",
        phone="11999999999", cro="CRO-SP-123", active=True,
    )
    db.add_all([proc, prof])
    db.commit()
    return {"db": db, "proc": proc, "prof": prof, "user": UsuarioFalso(empresa.id)}


def test_put_do_procedimento_apaga_o_preco_com_null(cenario):
    """O caso que a tela precisa: procedimento sem preco, agente nao cita valor."""
    atualizar_servico(
        cenario["proc"].id,
        ServicePatch(price_cents=None),
        db=cenario["db"],
        usuario=cenario["user"],
    )
    cenario["db"].refresh(cenario["proc"])
    assert cenario["proc"].price_cents is None


def test_put_do_procedimento_sem_falar_do_preco_preserva(cenario):
    atualizar_servico(
        cenario["proc"].id,
        ServicePatch(name="Clareamento Dental"),
        db=cenario["db"],
        usuario=cenario["user"],
    )
    cenario["db"].refresh(cenario["proc"])
    assert cenario["proc"].price_cents == 25000
    assert cenario["proc"].name == "Clareamento Dental"


def test_put_do_procedimento_nao_apaga_duracao_com_null(cenario):
    atualizar_servico(
        cenario["proc"].id,
        ServicePatch(duration_minutes=None),
        db=cenario["db"],
        usuario=cenario["user"],
    )
    cenario["db"].refresh(cenario["proc"])
    assert cenario["proc"].duration_minutes == 60


def test_put_do_profissional_apaga_telefone_e_cro_com_null(cenario):
    atualizar_profissional(
        cenario["prof"].id,
        ProfessionalPatch(phone=None, cro=None),
        db=cenario["db"],
        usuario=cenario["user"],
    )
    cenario["db"].refresh(cenario["prof"])
    assert cenario["prof"].phone is None
    assert cenario["prof"].cro is None


def test_put_do_profissional_sem_falar_de_telefone_preserva(cenario):
    atualizar_profissional(
        cenario["prof"].id,
        ProfessionalPatch(name="Dra. Ana Paula"),
        db=cenario["db"],
        usuario=cenario["user"],
    )
    cenario["db"].refresh(cenario["prof"])
    assert cenario["prof"].phone == "11999999999"
    assert cenario["prof"].cro == "CRO-SP-123"
