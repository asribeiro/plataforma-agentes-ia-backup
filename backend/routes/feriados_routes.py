"""Feriados: API do cadastro global e da liberação por clínica.

Divisão de poder (decisão do dono do produto, 31/10/2026):

- cadastrar/importar/apagar FERIADO é do admin da PLATAFORMA (o dia é global, vale para todas
  as clínicas);
- liberar PROFISSIONAL naquele feriado é do ADMIN DA CLÍNICA, e só da própria clínica.

A tela do admin da clínica lê `GET /api/feriados?ano=AAAA`, que já devolve, para cada feriado:
quem da clínica está liberado, quais profissionais existem e quantos pacientes já estão marcados
naquele dia (feriado não cancela nada sozinho — o admin decide com o número na mão).
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Feriado, Professional
from backend.routes.admin_platform_routes import require_internal_admin
from backend.routes.company import is_internal_admin
from backend.services import feriados as servico
from backend.services.papel_clinico import (
    PAPEIS_QUE_ADMINISTRAM_USUARIOS,
    exigir_admin_de_usuarios,
)

logger = logging.getLogger("saas_business.feriados_routes")

router = APIRouter(prefix="/api/feriados", tags=["Feriados"])

TIPOS_VALIDOS = ("nacional", "estadual", "municipal", "pontual")


class FeriadoEntrada(BaseModel):
    data: str = Field(..., description="Data do feriado, AAAA-MM-DD")
    nome: str = Field(..., min_length=2, max_length=120)
    tipo: str = Field("municipal", description="nacional | estadual | municipal | pontual")
    uf: Optional[str] = Field(None, max_length=2)
    cidade: Optional[str] = Field(None, max_length=120)
    recorrente: bool = Field(False, description="repete todo ano no mesmo dia e mês")


class LiberacoesEntrada(BaseModel):
    professional_ids: List[int] = Field(default_factory=list)


def _empresa_do_usuario(usuario) -> Optional[int]:
    return getattr(usuario, "company_id", None) or getattr(usuario, "clinic_id", None)


@router.get("")
def listar_feriados(
    ano: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
) -> Dict[str, Any]:
    """Feriados do ano com o estado da clínica do usuário."""
    empresa_id = _empresa_do_usuario(usuario)
    lista = servico.feriados_do_ano(db, ano)
    liberacoes = servico.liberacoes_por_feriado(
        db, empresa_id, [item.id for item in lista]
    ) if empresa_id else {}
    avisos = servico.agendamentos_por_dia(db, [item.data for item in lista], company_id=empresa_id)

    profissionais = []
    if empresa_id:
        profissionais = [
            {"id": item.id, "name": item.name}
            for item in db.query(Professional)
            .filter(Professional.company_id == empresa_id, Professional.active.is_(True))
            .order_by(Professional.name)
            .all()
        ]

    papel = getattr(usuario, "role", None)
    return {
        "ano": ano,
        "company_id": empresa_id,
        # a tela usa isto para mostrar/ativar controles; quem manda continua sendo o guard da rota
        "admin_plataforma": bool(is_internal_admin(usuario)),
        "pode_configurar": papel in PAPEIS_QUE_ADMINISTRAM_USUARIOS,
        "profissionais": profissionais,
        "feriados": [
            {
                "id": item.id,
                "data": item.data.isoformat(),
                "nome": item.nome,
                "tipo": item.tipo,
                "uf": item.uf,
                "cidade": item.cidade,
                "recorrente": bool(item.recorrente),
                "origem": item.origem,
                "liberados": liberacoes.get(int(item.id), []),
                "agendamentos_no_dia": avisos.get(item.data.isoformat(), {}).get("total", 0),
            }
            for item in lista
        ],
    }


@router.post("", dependencies=[Depends(require_internal_admin)])
def criar_feriado(dados: FeriadoEntrada, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Cadastro manual (municipal, pontual, ou correção do importado). Admin da plataforma."""
    try:
        dia = date.fromisoformat(dados.data[:10])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"data inválida: {dados.data}") from exc

    if dados.tipo not in TIPOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"tipo inválido: {dados.tipo}")

    ja_existe = (
        db.query(Feriado)
        .filter(Feriado.data == dia, Feriado.nome == dados.nome.strip())
        .first()
    )
    if ja_existe:
        return {"ok": True, "ja_existia": True, "feriado_id": ja_existe.id}

    feriado = Feriado(
        data=dia,
        nome=dados.nome.strip(),
        tipo=dados.tipo,
        uf=(dados.uf or "").upper() or None,
        cidade=(dados.cidade or "").strip() or None,
        recorrente=bool(dados.recorrente),
        origem="manual",
    )
    db.add(feriado)
    db.commit()
    db.refresh(feriado)
    logger.info("[Feriados] criado %s (%s) por admin da plataforma", feriado.data, feriado.nome)
    return {"ok": True, "feriado_id": feriado.id, "data": feriado.data.isoformat()}


@router.post("/importar", dependencies=[Depends(require_internal_admin)])
def importar_feriados(
    ano: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Importa os nacionais do ano (BrasilAPI). Idempotente; falha é declarada."""
    resultado = servico.importar_nacionais(db, ano)
    if not resultado.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=f"não consegui importar os feriados de {ano}: {resultado.get('erro')}",
        )
    return resultado


@router.delete("/{feriado_id}", dependencies=[Depends(require_internal_admin)])
def apagar_feriado(feriado_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    feriado = db.query(Feriado).filter(Feriado.id == feriado_id).first()
    if feriado is None:
        raise HTTPException(status_code=404, detail="feriado não encontrado")
    db.delete(feriado)
    db.commit()
    logger.info("[Feriados] apagado %s (%s)", feriado_id, feriado.nome)
    return {"ok": True, "apagado": feriado_id}


@router.put("/{feriado_id}/liberacoes")
def definir_liberacoes(
    feriado_id: int,
    dados: LiberacoesEntrada,
    db: Session = Depends(get_db),
    usuario=Depends(exigir_admin_de_usuarios),
) -> Dict[str, Any]:
    """Quem da MINHA clínica trabalha nesse feriado. Admin da clínica."""
    empresa_id = _empresa_do_usuario(usuario)
    if not empresa_id:
        raise HTTPException(status_code=403, detail="usuário sem clínica vinculada")

    feriado = db.query(Feriado).filter(Feriado.id == feriado_id).first()
    if feriado is None:
        raise HTTPException(status_code=404, detail="feriado não encontrado")

    resultado = servico.definir_liberacoes(
        db,
        feriado=feriado,
        company_id=int(empresa_id),
        professional_ids=dados.professional_ids,
        created_by=getattr(usuario, "id", None),
    )
    if not resultado.get("ok"):
        raise HTTPException(status_code=422, detail=resultado)
    return resultado
