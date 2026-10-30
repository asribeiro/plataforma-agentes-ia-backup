"""Modalidade da clinica (F1-08, parte 3 — reescrita pela decisao de 29/10).

Substitui o interruptor booleano `multi_professional_enabled` da migration 0010
pelas duas colunas da 0011:

    professional_tier    'mono' | 'up_to_4' | 'up_to_10'   (rotulo comercial)
    max_professionals    inteiro                            (regra de negocio)

QUEM DECIDE: somente o admin da plataforma (allowlist ADMIN_EMAILS, a mesma do
`require_internal_admin` do company.py). O cliente VE a modalidade e o limite,
mas nao edita. Isso e requisito comercial: a modalidade e o que separa o plano
vendido, nao uma preferencia da clinica.

REBAIXAMENTO: bloqueado quando a clinica tem mais profissionais ativos do que o
novo limite comporta. A mensagem diz quantos existem e quantos precisam sair —
negar sem dizer o numero deixa o admin sem acao possivel. A regra do documento
("bloqueia com 5 ou mais") e um caso particular desta: com 7 ativos, tanto mono
quanto up_to_4 sao bloqueados; com 3 ativos, up_to_4 e permitido e mono nao.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Company, Professional
from backend.routes.company import is_internal_admin, require_internal_admin

logger = logging.getLogger("saas_business.company_flag")

router = APIRouter(prefix="/api/company", tags=["company"])

# Uma modalidade, um limite. O limite e derivado do tier na escrita e lido
# direto da coluna na leitura: se a faixa comercial mudar, muda so este mapa.
LIMITE_POR_TIER = {"mono": 1, "up_to_4": 4, "up_to_10": 10, "network": 30}
TIER_POR_LIMITE = {1: "mono", 4: "up_to_4", 10: "up_to_10", 30: "network"}

ROTULO_TIER = {
    "mono": "Monoprofissional (1 profissional)",
    "up_to_4": "Clinica pequena (1 a 4 profissionais)",
    "up_to_10": "Clinica media (5 a 10 profissionais)",
    "network": "Redes de Clínicas (até 30 unidades)",
}


def _company_do_usuario(usuario) -> int:
    company_id = getattr(usuario, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não está vinculado a uma empresa",
        )
    return int(company_id)


class ModalidadeOut(BaseModel):
    professional_tier: str
    max_professionals: int
    rotulo: str
    profissionais_ativos: int
    # o cadastro novo cabe? a tela usa isso para desabilitar o botao "Adicionar"
    pode_adicionar: bool
    # false para o cliente: modalidade e definida pelo admin da plataforma
    pode_editar: bool
    orientacao: str


class ModalidadeIn(BaseModel):
    professional_tier: str
    # baixar o limite exige confirmar=true: reduz o teto e pode bloquear
    # cadastro em andamento
    confirmar: Optional[bool] = False


def _ativos(company_id: int, db: Session) -> int:
    return (
        db.query(Professional)
        .filter(Professional.company_id == company_id, Professional.active.is_(True))
        .count()
    )


def _orientacao(tier: str) -> str:
    if tier == "mono":
        return (
            "Clínica monoprofissional: o agente não pergunta o profissional e usa a "
            "agenda do único cadastrado. Procedimentos continuam cadastráveis."
        )
    return (
        "O agente oferece os profissionais que atendem o procedimento e consulta a "
        "agenda do escolhido."
    )


def _montar(company_id: int, db: Session, usuario) -> ModalidadeOut:
    linha = (
        db.query(Company.professional_tier, Company.max_professionals)
        .filter(Company.id == company_id)
        .first()
    )
    if linha is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada"
        )
    tier, limite = str(linha[0]), int(linha[1])
    ativos = _ativos(company_id, db)
    return ModalidadeOut(
        professional_tier=tier,
        max_professionals=limite,
        rotulo=ROTULO_TIER.get(tier, tier),
        profissionais_ativos=ativos,
        pode_adicionar=ativos < limite,
        pode_editar=is_internal_admin(usuario),
        orientacao=_orientacao(tier),
    )


@router.get("/flag", response_model=ModalidadeOut)
def ler_modalidade(db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Leitura da modalidade. O caminho /flag e mantido para nao quebrar quem ja
    chama (frontend/src/services/clinicApi.ts), mas o conteudo mudou."""
    return _montar(_company_do_usuario(usuario), db, usuario)


def aplicar_modalidade(
    db: Session,
    company_id: int,
    tier_pedido: Optional[str],
    confirmar: bool,
    usuario,
) -> ModalidadeOut:
    """Regra UNICA de troca de modalidade.

    Usada por `PUT /api/company/flag` (empresa em que o admin esta) e por
    `PUT /api/admin/companies/{id}/modalidade` (empresa escolhida no painel).
    Extraida para nao existirem duas versoes da regra: rebaixamento bloqueado com
    profissionais ativos e reducao exigindo confirmacao explicita.
    """
    tier = (tier_pedido or "").strip().lower()

    if tier not in LIMITE_POR_TIER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Modalidade '{tier_pedido}' inválida. "
                f"Use uma de: {', '.join(sorted(LIMITE_POR_TIER))}"
            ),
        )

    novo_limite = LIMITE_POR_TIER[tier]
    atual = (
        db.query(Company.max_professionals).filter(Company.id == company_id).scalar()
    )
    if atual is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada"
        )
    ativos = _ativos(company_id, db)

    # Rebaixamento: nunca deixar o limite abaixo de quem ja trabalha na clinica.
    if ativos > novo_limite:
        excedente = ativos - novo_limite
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A clínica tem {ativos} profissionais ativos e a modalidade "
                f"'{tier}' comporta {novo_limite}. Desative {excedente} "
                f"profissional(is) antes de rebaixar — nenhum cadastro é apagado "
                f"por esta mudança. Nada foi alterado."
            ),
        )

    # Reduzir o limite (sem excedente ainda) pede confirmacao explicita: e uma
    # decisao comercial, nao um ajuste de tela.
    if novo_limite < int(atual) and not confirmar:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Reduzir o limite de {int(atual)} para {novo_limite} bloqueia "
                f"novos cadastros a partir de agora ({ativos} ativo(s) hoje). "
                f"Reenvie com confirmar=true para aplicar."
            ),
        )

    db.query(Company).filter(Company.id == company_id).update(
        {Company.professional_tier: tier, Company.max_professionals: novo_limite}
    )
    db.commit()
    logger.info(
        "modalidade empresa=%s tier=%s limite=%s por=%s",
        company_id, tier, novo_limite, getattr(usuario, "email", "?"),
    )
    return _montar(company_id, db, usuario)


@router.put("/flag", response_model=ModalidadeOut)
def definir_modalidade(
    dados: ModalidadeIn,
    db: Session = Depends(get_db),
    usuario=Depends(require_internal_admin),
):
    """Troca a modalidade da clinica em que o admin esta logado.

    Exclusivo do admin da plataforma; a regra vive em `aplicar_modalidade`.
    """
    return aplicar_modalidade(
        db,
        _company_do_usuario(usuario),
        dados.professional_tier,
        bool(dados.confirmar),
        usuario,
    )
