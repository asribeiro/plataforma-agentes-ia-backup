"""Papeis clinicos: quem ve prontuario, quem so ve agenda, e o registro do acesso.

Card F1-13. A regra do dono (29/10) e curta e nao e preferencia de produto, e
responsabilidade legal:

- `service_professional` (Profissional de Atendimento) NAO acessa prontuario,
  anamnese, evolucao clinica, anexo de exame nem historico de procedimento
  executado. Ve agenda, contato, status do agendamento e confirmacao.
- `clinic_admin` (Admin Clinica) ve o prontuario de TODA a clinica porque e o
  representante do controlador dos dados — e cada acesso dele e REGISTRADO.
  O log e a contrapartida: sem ele, acesso autorizado fica indistinguivel de
  vazamento numa fiscalizacao (LGPD).

HONESTIDADE SOBRE O ESCOPO: hoje NAO existe endpoint de prontuario/anamnese/
evolucao neste stack. Este modulo entrega a base e a prova, e protege ZERO rota
ate o prontuario existir. O valor e o primeiro endpoint clinico nascer ja
protegido, em vez de virar retrofit de LGPD depois — e o teste com os quatro
papeis existe para provar que a guarda funciona ANTES de haver dado real exposto.

Como usar no primeiro endpoint clinico que existir:

    @router.get("/pacientes/{patient_id}/prontuario")
    def ler_prontuario(
        patient_id: int,
        db: Session = Depends(get_db),
        usuario = Depends(exigir_papel_clinico),
    ):
        registrar_acesso_clinico(db, usuario, resource="prontuario",
                                 action="read", patient_id=patient_id)
        ...
"""
import logging
from typing import Iterable, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client, ClinicalAccessLog, User

logger = logging.getLogger(__name__)

# Papeis que existem hoje (o CHECK do banco garante a mesma lista).
PAPEIS_VALIDOS = (
    "admin",
    "manager",
    "staff",
    "clinic_admin",
    "clinical_professional",
    "service_professional",
)

# Quem enxerga dado clinico. `admin` entra porque e o administrador da conta;
# `manager` NAO entra de proposito: gerente comercial nao tem motivo para ler
# prontuario, e ampliar acesso sem necessidade e o oposto de LGPD.
PAPEIS_QUE_VEEM_PRONTUARIO = ("admin", "clinic_admin", "clinical_professional")

# Quem administra usuarios da clinica (papel e vinculo com profissional).
PAPEIS_QUE_ADMINISTRAM_USUARIOS = ("admin", "clinic_admin")

# Papeis que SO existem amarrados a um profissional: sem o vinculo, o sistema
# nao sabe de quem e o usuario logado e "so os meus pacientes" fica impossivel.
PAPEIS_COM_PROFISSIONAL_OBRIGATORIO = ("clinical_professional", "service_professional")


def pode_ver_prontuario(papel: Optional[str]) -> bool:
    return (papel or "").strip() in PAPEIS_QUE_VEEM_PRONTUARIO


PAPEL_DO_DONO_DO_WORKSPACE = "clinic_admin"


def _papel_do_usuario(usuario) -> str:
    """Papel do usuario autenticado.

    O `get_current_user` devolve User (usuario da clinica) ou Client (dono da
    conta/workspace). O Client NAO tem coluna `role` — e por isso ficava sem
    papel nenhum, tomando 403 na administracao de usuarios e com o menu escondido.
    Dono da conta e o controlador dos dados da clinica dele: entra como
    `clinic_admin`, com o acesso auditado como qualquer outro.

    Todo o resto continua negando por padrao.
    """
    if isinstance(usuario, Client):
        return PAPEL_DO_DONO_DO_WORKSPACE
    return (getattr(usuario, "role", None) or "").strip()


def exigir_papel(*papeis: str):
    """Dependency: 403 se o usuario nao tiver um dos papeis pedidos."""
    permitidos = tuple(p for p in papeis if p)

    def _verificar(usuario=Depends(get_current_user)):
        papel = _papel_do_usuario(usuario)
        if papel not in permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Seu papel nesta clínica não permite acessar este recurso. "
                    f"Papéis com acesso: {', '.join(permitidos)}. "
                    "Se você precisa desse acesso, peça ao Admin Clínica."
                ),
            )
        return usuario

    return _verificar


exigir_papel_clinico = exigir_papel(*PAPEIS_QUE_VEEM_PRONTUARIO)
exigir_admin_de_usuarios = exigir_papel(*PAPEIS_QUE_ADMINISTRAM_USUARIOS)


def registrar_acesso_clinico(
    db: Session,
    usuario,
    resource: str,
    action: str = "read",
    patient_id: Optional[int] = None,
    professional_id: Optional[int] = None,
) -> ClinicalAccessLog:
    """Grava a linha de auditoria do acesso a dado clinico.

    FALHA FECHADA DE PROPOSITO: se o log nao puder ser gravado, a excecao sobe e
    a leitura nao acontece. Em auditoria de LGPD, acesso sem registro e pior do
    que acesso negado — e o contrario do padrao "nao deixar o log derrubar a
    feature", que vale para metricas, nao para dado de saude.
    """
    company_id = getattr(usuario, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não está vinculado a uma empresa",
        )

    registro = ClinicalAccessLog(
        company_id=company_id,
        user_id=getattr(usuario, "id", None),
        user_email=(getattr(usuario, "email", None) or "desconhecido"),
        professional_id=professional_id,
        patient_id=patient_id,
        resource=resource,
        action=action,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    logger.info(
        "acesso clinico registrado empresa=%s usuario=%s recurso=%s acao=%s paciente=%s",
        company_id, registro.user_email, resource, action, patient_id,
    )
    return registro


def listar_acessos(
    db: Session,
    company_id: int,
    limite: int = 200,
    patient_id: Optional[int] = None,
    user_email: Optional[str] = None,
) -> list:
    """Consulta do log para o Admin Clinica auditor (quem, quando, qual paciente)."""
    q = db.query(ClinicalAccessLog).filter(ClinicalAccessLog.company_id == company_id)
    if patient_id is not None:
        q = q.filter(ClinicalAccessLog.patient_id == patient_id)
    if user_email:
        q = q.filter(ClinicalAccessLog.user_email == user_email.strip().lower())
    return (
        q.order_by(ClinicalAccessLog.created_at.desc(), ClinicalAccessLog.id.desc())
        .limit(max(1, min(limite, 1000)))
        .all()
    )
