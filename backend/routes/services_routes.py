"""CRUD de procedimentos (services) por empresa.

F1-08. Escopo por company_id do usuario autenticado — nunca cruzar clinicas.

Decisoes:
- Exclusao e logica (active=False), nao fisica: um procedimento pode estar
  referenciado por agendamentos antigos e por professional_services. Apagar
  de verdade quebraria historico e violaria FK.
- Nome unico por empresa: comparacao sem diferenciar maiusculas, para nao
  existirem "Clareamento" e "clareamento" como coisas distintas.
- is_evaluation marca o procedimento de avaliacao inicial, que toda clinica
  precisa ter (a primeira consulta e sempre diagnostico).
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client, ProfessionalService, Service, User

logger = logging.getLogger("saas_business.services")

router = APIRouter(prefix="/api/services", tags=["services"])


# --------------------------------------------------------------------------
# Escopo multiempresa
# --------------------------------------------------------------------------
def _company_do_usuario(usuario) -> int:
    """Extrai o company_id do usuario autenticado.

    get_current_user devolve Client (usuario master) ou User (usuario da
    clinica). Sem company_id nao ha como saber de qual clinica sao os dados,
    entao a requisicao e recusada em vez de adivinhar.
    """
    company_id = getattr(usuario, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não está vinculado a uma empresa",
        )
    return int(company_id)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class ServiceIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    duration_minutes: int = Field(30, ge=5, le=600)
    price_cents: Optional[int] = Field(None, ge=0)
    is_evaluation: bool = False


class ServicePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=160)
    duration_minutes: Optional[int] = Field(None, ge=5, le=600)
    price_cents: Optional[int] = Field(None, ge=0)
    is_evaluation: Optional[bool] = None
    active: Optional[bool] = None


class ServiceOut(BaseModel):
    id: int
    name: str
    duration_minutes: int
    price_cents: Optional[int] = None
    is_evaluation: bool
    active: bool
    professionals: int = 0

    class Config:
        from_attributes = True


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _buscar(service_id: int, company_id: int, db: Session) -> Service:
    """Busca por id E company_id. Nunca so por id — e isso que impede uma
    clinica de ler ou alterar procedimento de outra."""
    obj = (
        db.query(Service)
        .filter(Service.id == service_id, Service.company_id == company_id)
        .first()
    )
    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Procedimento não encontrado"
        )
    return obj


def _contar_profissionais(service_id: int, db: Session) -> int:
    return (
        db.query(ProfessionalService)
        .filter(ProfessionalService.service_id == service_id)
        .count()
    )


def _saida(s: Service, db: Session) -> ServiceOut:
    return ServiceOut(
        id=s.id,
        name=s.name,
        duration_minutes=s.duration_minutes,
        price_cents=s.price_cents,
        is_evaluation=s.is_evaluation,
        active=s.active,
        professionals=_contar_profissionais(s.id, db),
    )


def _nome_em_uso(nome: str, company_id: int, db: Session, ignorar_id: int = 0) -> bool:
    q = db.query(Service).filter(
        Service.company_id == company_id,
        func_lower(Service.name) == nome.strip().lower(),
    )
    if ignorar_id:
        q = q.filter(Service.id != ignorar_id)
    return db.query(q.exists()).scalar()


def func_lower(coluna):
    from sqlalchemy import func

    return func.lower(coluna)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@router.get("", response_model=List[ServiceOut])
def listar(
    incluir_inativos: bool = False,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)
    q = db.query(Service).filter(Service.company_id == company_id)
    if not incluir_inativos:
        q = q.filter(Service.active.is_(True))
    # avaliacao primeiro, depois alfabetico: e a ordem em que a clinica pensa
    q = q.order_by(Service.is_evaluation.desc(), Service.name.asc())
    return [_saida(s, db) for s in q.all()]


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def criar(
    dados: ServiceIn,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)

    if _nome_em_uso(dados.name, company_id, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Já existe um procedimento chamado "{dados.name}" nesta empresa',
        )

    novo = Service(
        company_id=company_id,
        name=dados.name.strip(),
        duration_minutes=dados.duration_minutes,
        price_cents=dados.price_cents,
        is_evaluation=dados.is_evaluation,
        active=True,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    logger.info("procedimento criado id=%s empresa=%s", novo.id, company_id)
    return _saida(novo, db)


@router.get("/{service_id}", response_model=ServiceOut)
def detalhar(
    service_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    return _saida(_buscar(service_id, _company_do_usuario(usuario), db), db)


@router.put("/{service_id}", response_model=ServiceOut)
def atualizar(
    service_id: int,
    dados: ServicePatch,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)
    obj = _buscar(service_id, company_id, db)

    if dados.name is not None:
        if _nome_em_uso(dados.name, company_id, db, ignorar_id=obj.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'Já existe um procedimento chamado "{dados.name}" nesta empresa',
            )
        obj.name = dados.name.strip()

    for campo in ("duration_minutes", "price_cents", "is_evaluation", "active"):
        valor = getattr(dados, campo)
        if valor is not None:
            setattr(obj, campo, valor)

    db.commit()
    db.refresh(obj)
    return _saida(obj, db)


@router.delete("/{service_id}", status_code=status.HTTP_200_OK)
def desativar(
    service_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    """Desativa (soft delete). Nao apaga: o procedimento pode estar em
    agendamentos antigos e no vinculo com profissionais."""
    obj = _buscar(service_id, _company_do_usuario(usuario), db)
    obj.active = False
    db.commit()
    return {"ok": True, "id": obj.id, "active": False,
            "mensagem": "Procedimento desativado. O histórico é preservado."}
