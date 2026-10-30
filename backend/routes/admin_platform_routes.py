"""backend/routes/admin_platform_routes.py

Painel da plataforma (admin master): ver e administrar TODOS os clientes.

O que existia antes: o admin master (allowlist ADMIN_EMAILS) conseguia trocar a
modalidade da empresa em que ele ESTAVA — `PUT /api/company/flag` le
`usuario.company_id`. Nao havia como listar as empresas da plataforma. A area
`/customers` e a carteira do workspace (pacientes/faturas do cliente), nao a lista
de clientes da plataforma.

Decisoes:

- `GET /eu` nao exige ser admin: ele responde `admin_plataforma: false` para quem
  nao e. O MENU precisa perguntar sem tomar 403 — um 403 no boot do layout viraria
  toast de erro para todo usuario comum.
- `POST /companies/{id}/entrar` e a unica porta de troca de contexto do admin
  master: cria o vinculo (`client_companies`) se faltar e move `company_id`. Sem o
  vinculo criado, `PUT /api/client-companies/{id}/select` responderia 404 e o
  painel seria uma lista onde nada abre.
- Modalidade usa `aplicar_modalidade` (mesma funcao do `PUT /flag`): as regras de
  rebaixamento e de confirmacao nao podem ter duas versoes.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import (
    Agenda,
    Agendamento,
    Client,
    ClientCompany,
    Company,
    CustomerManagedCompany,
    Professional,
    User,
)
from backend.routes.company import is_internal_admin, require_internal_admin
from backend.routes.company_flag_routes import ModalidadeIn, ModalidadeOut, aplicar_modalidade

logger = logging.getLogger("saas_business.admin_platform")

router = APIRouter(prefix="/api/admin", tags=["admin-plataforma"])


class SouAdminOut(BaseModel):
    admin_plataforma: bool
    email: str
    company_id: Optional[int] = None


class EmpresaDoPainel(BaseModel):
    id: int
    nome: str
    nome_exibido: Optional[str] = None
    cnpj: Optional[str] = None
    logo_url: Optional[str] = None
    professional_tier: str
    max_professionals: int
    profissionais_ativos: int
    profissionais_total: int
    usuarios_ativos: int
    usuarios_total: int
    agendas_ativas: int
    agendamentos_total: int
    vinculada_ao_meu_login: bool
    empresa_atual: bool
    network_unit_limit: Optional[int] = None
    network_units_used: int = 0


class PainelOut(BaseModel):
    total_empresas: int
    empresa_atual_id: Optional[int] = None
    empresas: list[EmpresaDoPainel]


class LimiteUnidadesRedeIn(BaseModel):
    limite: int = Field(ge=1, le=100000)


class LimiteUnidadesRedeOut(BaseModel):
    company_id: int
    limite: int
    unidades_utilizadas: int
    unidades_disponiveis: int


def _contagens(db: Session) -> dict:
    """Uma consulta por metrica, agregada por empresa — nao uma por empresa.

    Com 1 cliente hoje o custo e irrelevante; com 50, um loop de N consultas por
    metrica viraria 250 consultas numa tela que abre no login do admin.
    """
    def por_empresa(query):
        return {int(k): int(v) for k, v in query.all() if k is not None}

    return {
        "prof_ativos": por_empresa(
            db.query(Professional.company_id, func.count(Professional.id))
            .filter(Professional.active.is_(True))
            .group_by(Professional.company_id)
        ),
        "prof_total": por_empresa(
            db.query(Professional.company_id, func.count(Professional.id))
            .group_by(Professional.company_id)
        ),
        "user_ativos": por_empresa(
            db.query(User.company_id, func.count(User.id))
            .filter(User.is_active.is_(True))
            .group_by(User.company_id)
        ),
        "user_total": por_empresa(
            db.query(User.company_id, func.count(User.id)).group_by(User.company_id)
        ),
        "agendas_ativas": por_empresa(
            db.query(Agenda.company_id, func.count(Agenda.id))
            .filter(Agenda.active.is_(True))
            .group_by(Agenda.company_id)
        ),
        # Agendamento nao tem company_id: a empresa vem pela agenda dele.
        "agendamentos": por_empresa(
            db.query(Agenda.company_id, func.count(Agendamento.id))
            .join(Agendamento, Agendamento.agenda_id == Agenda.id)
            .group_by(Agenda.company_id)
        ),
        "network_units": por_empresa(
            db.query(CustomerManagedCompany.owner_company_id, func.count(CustomerManagedCompany.id))
            .filter(CustomerManagedCompany.lifecycle_status.in_(("active", "trialing")))
            .group_by(CustomerManagedCompany.owner_company_id)
        ),
    }


@router.get("/eu", response_model=SouAdminOut)
def sou_admin_da_plataforma(usuario=Depends(get_current_user)):
    """Diz se o usuario logado e o admin master. NUNCA 403: o menu pergunta isto."""
    return SouAdminOut(
        admin_plataforma=is_internal_admin(usuario),
        email=getattr(usuario, "email", "") or "",
        company_id=getattr(usuario, "company_id", None),
    )


@router.get("/companies", response_model=PainelOut)
def listar_empresas(
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    """Todas as empresas da plataforma, com os numeros que decidem a modalidade."""
    empresas = db.query(Company).order_by(Company.id.asc()).all()
    c = _contagens(db)

    meus_vinculos = set()
    if isinstance(usuario, Client):
        meus_vinculos = {
            int(cid)
            for (cid,) in db.query(ClientCompany.company_id)
            .filter(ClientCompany.client_id == usuario.id)
            .all()
        }

    atual = getattr(usuario, "company_id", None)
    atual = int(atual) if atual is not None else None

    lista = []
    for e in empresas:
        eid = int(e.id)
        lista.append(
            EmpresaDoPainel(
                id=eid,
                nome=e.name or "",
                nome_exibido=e.name_company,
                cnpj=e.cnpj,
                logo_url=e.logo_url,
                professional_tier=str(e.professional_tier or ""),
                max_professionals=int(e.max_professionals or 0),
                profissionais_ativos=c["prof_ativos"].get(eid, 0),
                profissionais_total=c["prof_total"].get(eid, 0),
                usuarios_ativos=c["user_ativos"].get(eid, 0),
                usuarios_total=c["user_total"].get(eid, 0),
                agendas_ativas=c["agendas_ativas"].get(eid, 0),
                agendamentos_total=c["agendamentos"].get(eid, 0),
                vinculada_ao_meu_login=eid in meus_vinculos,
                empresa_atual=(eid == atual),
                network_unit_limit=int(e.network_unit_limit) if e.network_unit_limit is not None else None,
                network_units_used=c["network_units"].get(eid, 0),
            )
        )

    return PainelOut(
        total_empresas=len(lista),
        empresa_atual_id=atual,
        empresas=lista,
    )


@router.post("/companies/{company_id}/entrar")
def entrar_na_empresa(
    company_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    """Troca o contexto do admin master para a empresa escolhida.

    Cria o vinculo `client_companies` quando falta. Sem isso o painel listaria as
    empresas e nenhuma abriria — `PUT /api/client-companies/{id}/select` exige o
    vinculo e responde 404.
    """
    empresa = db.query(Company).filter(Company.id == company_id).first()
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada."
        )

    if not isinstance(usuario, Client):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Trocar de empresa é uma ação do dono da conta (admin master). "
                "Usuário de equipe pertence à empresa dele."
            ),
        )

    vinculo = (
        db.query(ClientCompany)
        .filter(ClientCompany.client_id == usuario.id)
        .filter(ClientCompany.company_id == company_id)
        .first()
    )
    criou_vinculo = False
    if not vinculo:
        db.add(ClientCompany(client_id=usuario.id, company_id=company_id))
        criou_vinculo = True

    anterior = getattr(usuario, "company_id", None)
    usuario.company_id = company_id
    db.add(usuario)
    db.commit()

    logger.info(
        "admin master trocou de empresa: %s -> %s por=%s vinculo_criado=%s",
        anterior, company_id, getattr(usuario, "email", "?"), criou_vinculo,
    )

    return {
        "status": "success",
        "company_id": int(empresa.id),
        "nome": empresa.name_company or empresa.name,
        "company_logo_url": empresa.logo_url or "",
        "vinculo_criado": criou_vinculo,
        "message": (
            f"Contexto alterado para {empresa.name_company or empresa.name}. "
            "Recarregue para ver os dados desta empresa."
        ),
    }


@router.get("/companies/{company_id}/network-limit", response_model=LimiteUnidadesRedeOut)
def ler_limite_unidades_rede(
    company_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    empresa = db.query(Company).filter(Company.id == company_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    utilizadas = (
        db.query(CustomerManagedCompany)
        .filter(
            CustomerManagedCompany.owner_company_id == company_id,
            CustomerManagedCompany.lifecycle_status.in_(("active", "trialing")),
        )
        .count()
    )
    limite = int(empresa.network_unit_limit or 30)
    return LimiteUnidadesRedeOut(
        company_id=company_id,
        limite=limite,
        unidades_utilizadas=utilizadas,
        unidades_disponiveis=max(0, limite - utilizadas),
    )


@router.put("/companies/{company_id}/network-limit", response_model=LimiteUnidadesRedeOut)
def atualizar_limite_unidades_rede(
    company_id: int,
    dados: LimiteUnidadesRedeIn,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    empresa = db.query(Company).filter(Company.id == company_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    utilizadas = (
        db.query(CustomerManagedCompany)
        .filter(
            CustomerManagedCompany.owner_company_id == company_id,
            CustomerManagedCompany.lifecycle_status.in_(("active", "trialing")),
        )
        .count()
    )
    if dados.limite < utilizadas:
        raise HTTPException(
            status_code=409,
            detail=f"O limite não pode ser menor que as {utilizadas} unidades já cadastradas.",
        )
    empresa.network_unit_limit = dados.limite
    db.commit()
    return LimiteUnidadesRedeOut(
        company_id=company_id,
        limite=dados.limite,
        unidades_utilizadas=utilizadas,
        unidades_disponiveis=dados.limite - utilizadas,
    )


@router.put("/companies/{company_id}/modalidade", response_model=ModalidadeOut)
def definir_modalidade_da_empresa(
    company_id: int,
    dados: ModalidadeIn,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    """Modalidade de QUALQUER empresa, sem trocar de contexto.

    A regra (rebaixamento bloqueado, reducao com confirmacao) vem de
    `aplicar_modalidade` — a mesma do `PUT /api/company/flag`.
    """
    return aplicar_modalidade(
        db,
        int(company_id),
        dados.professional_tier,
        bool(dados.confirmar),
        usuario,
    )
