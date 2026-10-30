"""backend/routes/admin_billing_routes.py

Cobranca da plataforma: planos, assinatura por empresa e faturas mensais.

O QUE ESTE MODULO NAO FAZ: nao cobra. O dono decidiu (30/10) que o registro e manual
e a cobranca real sai por parceiro com plataforma de pagamento. Entao aqui nao ha
token de adquirente, nao ha webhook e nao ha conciliacao — ha o combinado (plano e
assinatura) e o quitado (faturas). Quando o parceiro entrar, ele consome estes dados
em vez de inventar outro cadastro.

DUAS REGRAS QUE PARECEM DETALHE E SAO O PONTO:

1. `Fatura.valor_centavos` e SNAPSHOT. A fatura guarda o preco da emissao, nao o preco
   do catalogo de hoje. Sem isso, reajustar um plano reescreveria o passado e o
   historico deixaria de bater com o que o cartao do cliente foi debitado.
2. Plano sem preco nao emite fatura. `preco_centavos` nulo significa "ainda nao
   combinado"; emitir com zero criaria uma fatura de valor nenhum, que parece paga e
   nao e. A resposta e 400 com o motivo, nunca um numero inventado.

Uma assinatura ATIVA por empresa: garantida por indice parcial no banco (0013). Este
modulo respeita isso encerrando a anterior em vez de criar a segunda.
"""
import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import Company, CompanyAssinatura, Fatura, Plano
from backend.routes.company import require_internal_admin

logger = logging.getLogger(__name__)

router = APIRouter()

COMPETENCIA = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PlanoOut(BaseModel):
    id: int
    nome: str
    tier: str
    preco_centavos: Optional[int] = None
    ciclo: str
    ativo: bool

    class Config:
        from_attributes = True


class PlanoPatch(BaseModel):
    nome: Optional[str] = Field(default=None, max_length=80)
    preco_centavos: Optional[int] = Field(default=None, ge=0)
    ativo: Optional[bool] = None


class AssinaturaOut(BaseModel):
    id: int
    plano_id: int
    plano_nome: str
    status: str
    dia_vencimento: int
    inicio: date
    observacao: Optional[str] = None


class FaturaOut(BaseModel):
    id: int
    competencia: str
    valor_centavos: int
    vencimento: date
    status: str
    pago_em: Optional[datetime] = None
    observacao: Optional[str] = None


class CobrancaOut(BaseModel):
    company_id: int
    company_nome: str
    assinatura: Optional[AssinaturaOut] = None
    faturas: list[FaturaOut] = []
    total_aberto_centavos: int = 0
    total_pago_centavos: int = 0


class AssinaturaIn(BaseModel):
    plano_id: int
    dia_vencimento: int = Field(default=1, ge=1, le=28)
    status: str = "ativa"
    observacao: Optional[str] = None

    @field_validator("status")
    @classmethod
    def valida_status(cls, v: str) -> str:
        if v not in ("ativa", "suspensa", "encerrada"):
            raise ValueError("Status deve ser ativa, suspensa ou encerrada")
        return v


class FaturaIn(BaseModel):
    competencia: Optional[str] = None
    vencimento: Optional[date] = None
    observacao: Optional[str] = None

    @field_validator("competencia")
    @classmethod
    def valida_competencia(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not COMPETENCIA.match(v):
            raise ValueError("Competencia deve estar no formato AAAA-MM")
        return v


class FaturaPatch(BaseModel):
    status: str
    observacao: Optional[str] = None

    @field_validator("status")
    @classmethod
    def valida_status(cls, v: str) -> str:
        if v not in ("aberta", "paga", "cancelada"):
            raise ValueError("Status deve ser aberta, paga ou cancelada")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _empresa(db: Session, company_id: int) -> Company:
    empresa = db.query(Company).filter(Company.id == company_id).first()
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada")
    return empresa


def _plano(db: Session, plano_id: int) -> Plano:
    plano = db.query(Plano).filter(Plano.id == plano_id).first()
    if plano is None:
        raise HTTPException(status_code=404, detail="Plano nao encontrado")
    return plano


def _ativa(db: Session, company_id: int) -> Optional[CompanyAssinatura]:
    return (
        db.query(CompanyAssinatura)
        .filter(
            CompanyAssinatura.company_id == company_id,
            CompanyAssinatura.status == "ativa",
        )
        .first()
    )


def _saida_assinatura(db: Session, assinatura: CompanyAssinatura) -> AssinaturaOut:
    plano = db.query(Plano).filter(Plano.id == assinatura.plano_id).first()
    return AssinaturaOut(
        id=assinatura.id,
        plano_id=assinatura.plano_id,
        plano_nome=plano.nome if plano else "plano removido",
        status=assinatura.status,
        dia_vencimento=assinatura.dia_vencimento,
        inicio=assinatura.inicio,
        observacao=assinatura.observacao,
    )


def _saida_fatura(fatura: Fatura) -> FaturaOut:
    return FaturaOut(
        id=fatura.id,
        competencia=fatura.competencia,
        valor_centavos=fatura.valor_centavos,
        vencimento=fatura.vencimento,
        status=fatura.status,
        pago_em=fatura.pago_em,
        observacao=fatura.observacao,
    )


def _vencimento(competencia: str, dia: int) -> date:
    """Vencimento dentro da competencia, com dia limitado ao ultimo do mes.

    O CHECK do banco limita o dia a 28 na assinatura, mas a fatura pode receber um
    vencimento explicito — e fevereiro nao tem 30.
    """
    ano, mes = int(competencia.split("-")[0]), int(competencia.split("-")[1])
    if mes == 12:
        proximo = date(ano + 1, 1, 1)
    else:
        proximo = date(ano, mes + 1, 1)
    ultimo_dia = (proximo - date.resolution).day
    return date(ano, mes, min(dia, ultimo_dia))


# ---------------------------------------------------------------------------
# Planos
# ---------------------------------------------------------------------------
@router.get("/planos", response_model=list[PlanoOut], tags=["admin-cobranca"])
def listar_planos(
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    return db.query(Plano).order_by(Plano.id).all()


@router.put("/planos/{plano_id}", response_model=PlanoOut, tags=["admin-cobranca"])
def atualizar_plano(
    plano_id: int,
    dados: PlanoPatch,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    plano = _plano(db, plano_id)
    # `model_fields_set` distingue "nao mandou" de "mandou null": preco nulo e uma
    # informacao (preco retirado do catalogo), ausencia nao e.
    campos = dados.model_fields_set
    if "nome" in campos and dados.nome:
        plano.nome = dados.nome
    if "preco_centavos" in campos:
        plano.preco_centavos = dados.preco_centavos
    if "ativo" in campos and dados.ativo is not None:
        plano.ativo = dados.ativo
    db.commit()
    db.refresh(plano)
    logger.info("Plano %s atualizado por %s", plano.id, getattr(usuario, "email", "?"))
    return plano


# ---------------------------------------------------------------------------
# Cobranca por empresa
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/cobranca", response_model=CobrancaOut, tags=["admin-cobranca"])
def ler_cobranca(
    company_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    empresa = _empresa(db, company_id)
    assinatura = _ativa(db, company_id)
    faturas = (
        db.query(Fatura)
        .filter(Fatura.company_id == company_id)
        .order_by(Fatura.competencia.desc())
        .all()
    )
    aberto = sum(f.valor_centavos for f in faturas if f.status == "aberta")
    pago = sum(f.valor_centavos for f in faturas if f.status == "paga")
    return CobrancaOut(
        company_id=empresa.id,
        company_nome=empresa.name,
        assinatura=_saida_assinatura(db, assinatura) if assinatura else None,
        faturas=[_saida_fatura(f) for f in faturas],
        total_aberto_centavos=aberto,
        total_pago_centavos=pago,
    )


@router.put("/companies/{company_id}/cobranca", response_model=CobrancaOut, tags=["admin-cobranca"])
def definir_cobranca(
    company_id: int,
    dados: AssinaturaIn,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    """Define plano e condicoes. Encerra a assinatura ativa anterior quando muda.

    Uma ativa por empresa e regra do banco (indice parcial). Criar a segunda
    estouraria IntegrityError; encerrar a anterior e o comportamento correto e
    deixa o historico.
    """
    empresa = _empresa(db, company_id)
    plano = _plano(db, dados.plano_id)
    if plano.ativo is False:
        raise HTTPException(status_code=409, detail="Plano inativo nao pode ser contratado")

    atual = _ativa(db, company_id)
    if atual is not None:
        if atual.plano_id == plano.id and dados.status == "ativa":
            atual.dia_vencimento = dados.dia_vencimento
            if dados.observacao is not None:
                atual.observacao = dados.observacao
            db.commit()
        else:
            atual.status = "encerrada"
            db.add(
                CompanyAssinatura(
                    company_id=company_id,
                    plano_id=plano.id,
                    status=dados.status,
                    dia_vencimento=dados.dia_vencimento,
                    inicio=date.today(),
                    observacao=dados.observacao,
                )
            )
            db.commit()
    else:
        db.add(
            CompanyAssinatura(
                company_id=company_id,
                plano_id=plano.id,
                status=dados.status,
                dia_vencimento=dados.dia_vencimento,
                inicio=date.today(),
                observacao=dados.observacao,
            )
        )
        db.commit()

    logger.info(
        "Cobranca da empresa %s definida (%s) por %s",
        company_id,
        plano.nome,
        getattr(usuario, "email", "?"),
    )
    return ler_cobranca(company_id=company_id, db=db, usuario=usuario)


# ---------------------------------------------------------------------------
# Faturas
# ---------------------------------------------------------------------------
@router.post(
    "/companies/{company_id}/faturas",
    response_model=FaturaOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-cobranca"],
)
def emitir_fatura(
    company_id: int,
    dados: FaturaIn,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    """Emite a fatura da competencia com o valor do plano vigente.

    Recusa plano sem preco: valor zero pareceria fatura gratuita e esconderia o
    problema. Recusa competencia repetida: uma por mes por empresa (constraint).
    """
    empresa = _empresa(db, company_id)
    assinatura = _ativa(db, company_id)
    if assinatura is None:
        raise HTTPException(
            status_code=409,
            detail="Empresa sem assinatura ativa: defina o plano antes de emitir fatura",
        )
    plano = _plano(db, assinatura.plano_id)
    if plano.preco_centavos is None:
        raise HTTPException(
            status_code=400,
            detail=f"Plano {plano.nome} esta sem preco definido; informe o valor antes de emitir",
        )

    hoje = date.today()
    competencia = dados.competencia or f"{hoje.year:04d}-{hoje.month:02d}"
    existente = (
        db.query(Fatura)
        .filter(Fatura.company_id == company_id, Fatura.competencia == competencia)
        .first()
    )
    if existente is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Ja existe fatura da competencia {competencia} para esta empresa",
        )

    vencimento = dados.vencimento or _vencimento(competencia, assinatura.dia_vencimento)
    fatura = Fatura(
        company_id=company_id,
        assinatura_id=assinatura.id,
        competencia=competencia,
        valor_centavos=plano.preco_centavos,  # snapshot
        vencimento=vencimento,
        status="aberta",
        observacao=dados.observacao,
    )
    db.add(fatura)
    db.commit()
    db.refresh(fatura)
    logger.info(
        "Fatura %s (%s) emitida para empresa %s por %s",
        fatura.id,
        competencia,
        company_id,
        getattr(usuario, "email", "?"),
    )
    return _saida_fatura(fatura)


@router.patch("/faturas/{fatura_id}", response_model=FaturaOut, tags=["admin-cobranca"])
def atualizar_fatura(
    fatura_id: int,
    dados: FaturaPatch,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    fatura = db.query(Fatura).filter(Fatura.id == fatura_id).first()
    if fatura is None:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    fatura.status = dados.status
    if dados.status == "paga":
        fatura.pago_em = datetime.now(timezone.utc)
    else:
        # Voltar para aberta/cancelada nao pode deixar data de pagamento mentindo.
        fatura.pago_em = None
    if dados.observacao is not None:
        fatura.observacao = dados.observacao
    db.commit()
    db.refresh(fatura)
    logger.info(
        "Fatura %s -> %s por %s", fatura.id, fatura.status, getattr(usuario, "email", "?")
    )
    return _saida_fatura(fatura)
