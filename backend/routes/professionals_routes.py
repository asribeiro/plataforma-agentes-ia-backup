"""CRUD de profissionais e vínculo com procedimentos.

F1-08, parte 2. Escopo por company_id do usuário autenticado.

PONTO CRÍTICO DE SEGURANÇA: a tabela professional_services não tem company_id.
Ela tem professional_id e service_id. Isso significa que o isolamento entre
clínicas NÃO pode vir de um filtro na própria tabela de vínculo — tem que ser
garantido verificando que o profissional E o procedimento pertencem à empresa
de quem está chamando. Se isso falhar, uma clínica vincula procedimento de
outra, e o dado vaza.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Company, Professional, ProfessionalService, Service
from backend.utils.patch_utils import aplicar_patch

logger = logging.getLogger("saas_business.professionals")

router = APIRouter(prefix="/api/professionals", tags=["professionals"])


# --------------------------------------------------------------------------
# Escopo multiempresa
# --------------------------------------------------------------------------
def _company_do_usuario(usuario) -> int:
    company_id = getattr(usuario, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não está vinculado a uma empresa",
        )
    return int(company_id)


def _limite_de_profissionais(company_id: int, db: Session) -> int:
    """Quantos profissionais a modalidade da empresa comporta (migration 0011).

    A regra vem do NUMERO (`companies.max_professionals`), nunca do rotulo
    (`professional_tier`): mudar a faixa comercial de "5 a 10" para "5 a 12"
    altera a coluna, nao este codigo.
    """
    valor = (
        db.query(Company.max_professionals)
        .filter(Company.id == company_id)
        .scalar()
    )
    return int(valor) if valor is not None else 1


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class ProfessionalIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    email: str = Field(..., min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=30)
    cro: Optional[str] = Field(None, max_length=30)


class ProfessionalPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=160)
    email: Optional[str] = Field(None, min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=30)
    cro: Optional[str] = Field(None, max_length=30)
    active: Optional[bool] = None


class ProfessionalOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    cro: Optional[str] = None
    active: bool
    services: int = 0

    class Config:
        from_attributes = True


class VinculoIn(BaseModel):
    """Lista completa de procedimentos que o profissional atende.

    Substitui o conjunto atual. Enviar lista vazia significa 'este
    profissional não atende nada', que é um estado válido.
    """

    service_ids: List[int] = Field(default_factory=list)


class VinculoOut(BaseModel):
    professional_id: int
    service_ids: List[int]
    total: int


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _buscar(professional_id: int, company_id: int, db: Session) -> Professional:
    obj = (
        db.query(Professional)
        .filter(Professional.id == professional_id, Professional.company_id == company_id)
        .first()
    )
    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profissional não encontrado"
        )
    return obj


def _contar_servicos(professional_id: int, db: Session) -> int:
    return (
        db.query(ProfessionalService)
        .filter(ProfessionalService.professional_id == professional_id)
        .count()
    )


def _saida(p: Professional, db: Session) -> ProfessionalOut:
    return ProfessionalOut(
        id=p.id,
        name=p.name,
        email=p.email,
        phone=p.phone,
        cro=p.cro,
        active=p.active,
        services=_contar_servicos(p.id, db),
    )


def _email_em_uso(email: str, company_id: int, db: Session, ignorar_id: int = 0) -> bool:
    q = db.query(Professional).filter(
        Professional.company_id == company_id,
        func.lower(Professional.email) == email.strip().lower(),
    )
    if ignorar_id:
        q = q.filter(Professional.id != ignorar_id)
    return db.query(q.exists()).scalar()


def _verificar_limite_de_profissionais(company_id: int, db: Session) -> None:
    """Bloqueia o cadastro quando a clínica já atingiu o limite da modalidade.

    A mensagem precisa dizer o que fazer, não apenas negar: quem tenta cadastrar
    o profissional excedente é justamente quem pede a mudança de modalidade —
    e quem muda a modalidade é o admin da plataforma, não o cliente.
    """
    limite = _limite_de_profissionais(company_id, db)
    existentes = (
        db.query(Professional)
        .filter(Professional.company_id == company_id, Professional.active.is_(True))
        .count()
    )
    if existentes < limite:
        return

    if limite <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Esta clínica está na modalidade monoprofissional (1 profissional). "
                "A modalidade é definida pelo administrador da plataforma — peça a "
                "mudança para 'clínica pequena' (até 4) ou 'clínica média' (até 10). "
                "Nenhum cadastro existente é apagado por isso."
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Limite da modalidade atingido: {existentes} de {limite} profissionais "
            f"ativos. Para cadastrar mais, peça ao administrador da plataforma a "
            f"mudança de modalidade. Desativar um profissional que saiu também "
            f"libera a vaga."
        ),
    )


# --------------------------------------------------------------------------
# Endpoints — profissionais
# --------------------------------------------------------------------------
@router.get("", response_model=List[ProfessionalOut])
def listar(
    incluir_inativos: bool = False,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)
    q = db.query(Professional).filter(Professional.company_id == company_id)
    if not incluir_inativos:
        q = q.filter(Professional.active.is_(True))
    return [_saida(p, db) for p in q.order_by(Professional.name.asc()).all()]


@router.post("", response_model=ProfessionalOut, status_code=status.HTTP_201_CREATED)
def criar(
    dados: ProfessionalIn,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)
    _verificar_limite_de_profissionais(company_id, db)

    if _email_em_uso(dados.email, company_id, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Já existe um profissional com o e-mail "{dados.email}"',
        )

    novo = Professional(
        company_id=company_id,
        name=dados.name.strip(),
        email=dados.email.strip().lower(),
        phone=dados.phone,
        cro=dados.cro,
        active=True,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    logger.info("profissional criado id=%s empresa=%s", novo.id, company_id)
    return _saida(novo, db)


@router.get("/{professional_id}", response_model=ProfessionalOut)
def detalhar(
    professional_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    return _saida(_buscar(professional_id, _company_do_usuario(usuario), db), db)


@router.put("/{professional_id}", response_model=ProfessionalOut)
def atualizar(
    professional_id: int,
    dados: ProfessionalPatch,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)
    obj = _buscar(professional_id, company_id, db)

    if dados.email is not None:
        if _email_em_uso(dados.email, company_id, db, ignorar_id=obj.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'Já existe um profissional com o e-mail "{dados.email}"',
            )
        obj.email = dados.email.strip().lower()

    if dados.name is not None:
        obj.name = dados.name.strip()

    # telefone e CRO sao anulaveis: null explicito APAGA (corrigir cadastro
    # errado), campo ausente PRESERVA. `active` nao aceita null.
    aplicar_patch(obj, dados, ("phone", "cro", "active"), anulaveis=("phone", "cro"))

    db.commit()
    db.refresh(obj)
    return _saida(obj, db)


@router.delete("/{professional_id}", status_code=status.HTTP_200_OK)
def desativar(
    professional_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    obj = _buscar(professional_id, _company_do_usuario(usuario), db)
    obj.active = False
    db.commit()
    return {"ok": True, "id": obj.id, "active": False,
            "mensagem": "Profissional desativado. O histórico é preservado."}


# --------------------------------------------------------------------------
# Endpoints — vínculo profissional x procedimento
# --------------------------------------------------------------------------
@router.get("/{professional_id}/services", response_model=VinculoOut)
def listar_vinculos(
    professional_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    company_id = _company_do_usuario(usuario)
    _buscar(professional_id, company_id, db)  # garante que é da empresa
    ids = [
        r[0]
        for r in db.query(ProfessionalService.service_id)
        .filter(ProfessionalService.professional_id == professional_id)
        .all()
    ]
    return VinculoOut(professional_id=professional_id, service_ids=sorted(ids), total=len(ids))


@router.put("/{professional_id}/services", response_model=VinculoOut)
def definir_vinculos(
    professional_id: int,
    dados: VinculoIn,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    """Substitui a lista de procedimentos que o profissional atende.

    AS DUAS VERIFICAÇÕES QUE IMPEDEM VAZAMENTO ENTRE CLÍNICAS:
      1. o profissional é desta empresa (_buscar filtra por company_id)
      2. CADA procedimento informado é desta empresa (query abaixo filtra
         Service.company_id). Sem a segunda, uma clínica poderia vincular o
         procedimento de outra apenas sabendo o id.
    """
    company_id = _company_do_usuario(usuario)
    _buscar(professional_id, company_id, db)

    desejados = sorted({int(s) for s in dados.service_ids})

    if desejados:
        validos = {
            r[0]
            for r in db.query(Service.id)
            .filter(Service.id.in_(desejados), Service.company_id == company_id)
            .all()
        }
        invalidos = [s for s in desejados if s not in validos]
        if invalidos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Procedimento(s) inexistente(s) nesta empresa: {invalidos}",
            )

    # substitui o conjunto atual
    db.query(ProfessionalService).filter(
        ProfessionalService.professional_id == professional_id
    ).delete(synchronize_session=False)

    for sid in desejados:
        db.add(ProfessionalService(professional_id=professional_id, service_id=sid))

    db.commit()
    logger.info(
        "vinculos atualizados profissional=%s empresa=%s total=%s",
        professional_id, company_id, len(desejados),
    )
    return VinculoOut(
        professional_id=professional_id, service_ids=desejados, total=len(desejados)
    )
