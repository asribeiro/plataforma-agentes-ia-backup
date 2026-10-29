"""Consulta do log de acesso clinico — a contrapartida do LGPD (card F1-13).

Quem ve prontuario de toda a clinica e o Admin Clinica, porque ele e o
representante do controlador dos dados. A contrapartida obrigatoria e poder
responder, numa fiscalizacao ou a um pedido de titular: QUEM acessou, QUANDO,
QUAL paciente e em QUAL recurso.

Este router nao apaga nem edita log — log de auditoria que se edita nao serve
para auditar. So lista, e so dentro da propria empresa.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.services.papel_clinico import (
    exigir_admin_de_usuarios,
    listar_acessos,
)

logger = logging.getLogger("saas_business.clinic_audit")

router = APIRouter(prefix="/api/clinic/access-log", tags=["clinic-audit"])


class AcessoClinicoOut(BaseModel):
    id: int
    user_email: str
    professional_id: Optional[int] = None
    patient_id: Optional[int] = None
    resource: str
    action: str
    created_at: Optional[object] = None

    class Config:
        orm_mode = True


@router.get("", response_model=List[AcessoClinicoOut])
def consultar(
    patient_id: Optional[int] = Query(None, description="Filtra por paciente (contacts.id)"),
    user_email: Optional[str] = Query(None, description="Filtra por quem acessou"),
    limite: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    usuario=Depends(exigir_admin_de_usuarios),
):
    """Ultimos acessos a dado clinico da clinica do usuario logado."""
    company_id = getattr(usuario, "company_id", None)
    if not company_id:
        # Sem empresa nao existe recorte possivel: devolver tudo seria vazamento.
        return []
    return listar_acessos(
        db, company_id, limite=limite, patient_id=patient_id, user_email=user_email
    )
