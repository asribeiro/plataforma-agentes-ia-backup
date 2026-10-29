"""Reativar profissional consome vaga da modalidade (card F1-14).

O furo: `_verificar_limite_de_profissionais` só rodava no POST. Numa clínica
`up_to_4` com 4 ativos, bastava desativar um e reativar um quinto — o cadastro
é regra COMERCIAL (o que o cliente contratou), não preferência de tela.

O que este arquivo tranca:
  1. reativar no limite -> 409, com mensagem que diz o que fazer;
  2. reativar com vaga livre -> passa;
  3. editar nome/telefone de um profissional JÁ ATIVO numa clínica cheia não
     pode ser bloqueado (o erro clássico de checar toda escrita em vez de só a
     transição inativo -> ativo);
  4. desativar continua sempre permitido — é o que libera a vaga.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, Company, Professional, ProfessionalService
from backend.routes.professionals_routes import (
    ProfessionalPatch,
    atualizar as atualizar_profissional,
)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        eng,
        tables=[
            Company.__table__,
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


def _clinica(db, limite):
    """Empresa com a modalidade e `limite` profissionais ATIVOS + 1 inativo."""
    empresa = Company(
        name="Clinica Limite",
        cnpj="00000000000400",
        professional_tier={1: "mono", 4: "up_to_4", 10: "up_to_10"}[limite],
        max_professionals=limite,
    )
    db.add(empresa)
    db.commit()

    ativos = [
        Professional(
            company_id=empresa.id, name=f"Dra. Ativa {i}",
            email=f"ativa{i}@teste.com", active=True,
        )
        for i in range(1, limite + 1)
    ]
    dormindo = Professional(
        company_id=empresa.id, name="Dr. Desligado",
        email="desligado@teste.com", active=False,
    )
    db.add_all(ativos + [dormindo])
    db.commit()
    return empresa, dormindo, ativos


def test_reativar_no_limite_e_recusado_com_orientacao(db):
    empresa, dormindo, _ = _clinica(db, 4)
    with pytest.raises(HTTPException) as erro:
        atualizar_profissional(
            dormindo.id,
            ProfessionalPatch(active=True),
            db=db,
            usuario=UsuarioFalso(empresa.id),
        )
    assert erro.value.status_code == 409
    assert "4 de 4" in erro.value.detail
    assert "desative outro antes" in erro.value.detail
    db.refresh(dormindo)
    assert dormindo.active is False, "recusou mas mudou o registro"


def test_reativar_com_vaga_livre_passa(db):
    empresa, _, ativos = _clinica(db, 4)
    # libera uma vaga desativando o quarto
    atualizar_profissional(
        ativos[3].id, ProfessionalPatch(active=False), db=db, usuario=UsuarioFalso(empresa.id)
    )
    dormindo = (
        db.query(Professional).filter(Professional.email == "desligado@teste.com").one()
    )
    atualizar_profissional(
        dormindo.id, ProfessionalPatch(active=True), db=db, usuario=UsuarioFalso(empresa.id)
    )
    db.refresh(dormindo)
    assert dormindo.active is True


def test_editar_profissional_ativo_em_clinica_cheia_nao_e_bloqueado(db):
    empresa, _, ativos = _clinica(db, 4)
    atualizar_profissional(
        ativos[0].id,
        ProfessionalPatch(name="Dra. Ativa Um", phone="11988887777"),
        db=db,
        usuario=UsuarioFalso(empresa.id),
    )
    db.refresh(ativos[0])
    assert ativos[0].name == "Dra. Ativa Um"
    assert ativos[0].phone == "11988887777"


def test_desativar_nunca_e_bloqueado(db):
    empresa, _, ativos = _clinica(db, 4)
    atualizar_profissional(
        ativos[1].id, ProfessionalPatch(active=False), db=db, usuario=UsuarioFalso(empresa.id)
    )
    db.refresh(ativos[1])
    assert ativos[1].active is False


def test_monoprofissional_reativacao_avisa_para_desativar_antes(db):
    empresa, dormindo, _ = _clinica(db, 1)
    with pytest.raises(HTTPException) as erro:
        atualizar_profissional(
            dormindo.id,
            ProfessionalPatch(active=True),
            db=db,
            usuario=UsuarioFalso(empresa.id),
        )
    assert erro.value.status_code == 409
    assert "desative o que está ativo antes" in erro.value.detail
