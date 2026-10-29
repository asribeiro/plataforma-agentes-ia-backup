"""Interruptor de múltiplos profissionais da empresa (F1-08, parte 3).

Fica em router próprio para não interferir no company.py existente.

Regra (decidida com o Anderson):
- flag desligada: clínica monoprofissional. O agente não oferece escolha de
  profissional e usa a agenda do único. Procedimentos continuam cadastráveis.
- flag ligada: vários profissionais, escolha de quem atende cada procedimento.

Desligar a flag com profissionais já cadastrados é PERMITIDO e não apaga
ninguém: os dados permanecem para o caso de religar. O que muda é o
comportamento do fluxo, não o cadastro.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Company, Professional

logger = logging.getLogger("saas_business.company_flag")

router = APIRouter(prefix="/api/company", tags=["company"])


def _company_do_usuario(usuario) -> int:
    company_id = getattr(usuario, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não está vinculado a uma empresa",
        )
    return int(company_id)


class FlagOut(BaseModel):
    multi_professional_enabled: bool
    profissionais_ativos: int
    # mensagem pronta para a tela exibir ao lado do interruptor
    orientacao: str


class FlagIn(BaseModel):
    multi_professional_enabled: bool
    # opcional: aplicar só se o cliente confirmar, quando houver mais de um
    confirmar: Optional[bool] = False


def _montar(company_id: int, db: Session) -> FlagOut:
    flag = bool(
        db.query(Company.multi_professional_enabled)
        .filter(Company.id == company_id)
        .scalar()
    )
    ativos = (
        db.query(Professional)
        .filter(Professional.company_id == company_id, Professional.active.is_(True))
        .count()
    )
    if flag:
        orientacao = (
            "Múltiplos profissionais ativo. O agente oferece os profissionais que "
            "atendem o procedimento e consulta a agenda do escolhido."
        )
    else:
        orientacao = (
            "Clínica monoprofissional. O agente não pergunta o profissional e usa a "
            "agenda do único cadastrado. Procedimentos continuam cadastráveis."
        )
    return FlagOut(
        multi_professional_enabled=flag,
        profissionais_ativos=ativos,
        orientacao=orientacao,
    )


@router.get("/flag", response_model=FlagOut)
def ler_flag(db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    return _montar(_company_do_usuario(usuario), db)


@router.put("/flag", response_model=FlagOut)
def definir_flag(
    dados: FlagIn,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)

    # Desligar com mais de um profissional ativo é permitido, mas pede
    # confirmação: a tela deve mostrar que ninguém será apagado e que a
    # seleção deixa de aparecer.
    if dados.multi_professional_enabled is False and not dados.confirmar:
        ativos = (
            db.query(Professional)
            .filter(Professional.company_id == company_id, Professional.active.is_(True))
            .count()
        )
        if ativos > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Há {ativos} profissionais ativos. Desligar o interruptor não apaga "
                    "nenhum cadastro nem vínculo — apenas o agente deixa de oferecer "
                    "escolha de profissional. Reenvie com confirmar=true para aplicar."
                ),
            )

    db.query(Company).filter(Company.id == company_id).update(
        {Company.multi_professional_enabled: dados.multi_professional_enabled}
    )
    db.commit()
    logger.info(
        "flag multi_professional empresa=%s valor=%s", company_id,
        dados.multi_professional_enabled,
    )
    return _montar(company_id, db)
