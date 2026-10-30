"""Usuarios da clinica: papel e vinculo com o profissional (card F1-12).

Por que um modulo novo em vez de mexer em `users.py`: aquele arquivo e a API de
"master" (Client dono de varias empresas, `validate_master_access`). Aqui o
recorte e outro — o usuario logado e da CLINICA e so enxerga a propria empresa.
Misturar os dois escopos no mesmo router e como se cria vazamento entre
clinicas.

Regras que este arquivo faz valer (migration 0011 ja criou as colunas):

- papel tem de estar na lista (o CHECK `ck_users_role_valido` garante o mesmo no
  banco; aqui a mensagem explica antes de virar erro de constraint);
- `clinical_professional` e `service_professional` EXIGEM `professional_id` de
  um profissional ATIVO da MESMA empresa. Sem esse vinculo o sistema nao sabe de
  quem e o usuario logado e a regra "so os meus pacientes" fica impossivel;
- papel administrativo NAO aceita vinculo clinico (evita usuario com dois
  papeis na pratica);
- nao se remove o ultimo administrador da clinica: sem isso a clinica fica
  trancada pra fora da propria gestao.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import get_current_user, hash_password
from backend.db import get_db
from backend.models import Company, Professional, User
from backend.services.papel_clinico import (
    PAPEIS_COM_PROFISSIONAL_OBRIGATORIO,
    PAPEIS_QUE_ADMINISTRAM_USUARIOS,
    PAPEIS_QUE_VEEM_PRONTUARIO,
    PAPEIS_VALIDOS,
    exigir_admin_de_usuarios,
)

logger = logging.getLogger("saas_business.clinic_users")

router = APIRouter(prefix="/api/clinic/users", tags=["clinic-users"])

ROTULOS_DE_PAPEL = {
    "admin": "Administrador da conta",
    "clinic_admin": "Admin Clínica — administra a clínica e vê todo o prontuário",
    "clinical_professional": "Profissional Clínico — vê o prontuário dos próprios pacientes",
    "service_professional": "Profissional de Atendimento — agenda e contato, sem prontuário",
    "manager": "Gerente",
    "staff": "Atendimento (legado)",
}


# --------------------------------------------------------------------- schemas
class ClinicaUsuarioOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    role_rotulo: str
    professional_id: Optional[int] = None
    professional_nome: Optional[str] = None
    is_active: bool

    class Config:
        orm_mode = True


class EuClinicaOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    role_rotulo: str
    professional_id: Optional[int] = None
    professional_nome: Optional[str] = None
    pode_administrar_usuarios: bool
    ve_prontuario: bool


class ClinicaUsuarioIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: str
    professional_id: Optional[int] = None


class ClinicaUsuarioPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=160)
    role: Optional[str] = None
    professional_id: Optional[int] = None
    is_active: Optional[bool] = None


# --------------------------------------------------------------------- helpers
def _company_id(usuario) -> int:
    company_id = getattr(usuario, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não está vinculado a uma empresa",
        )
    return company_id


def _client_id(usuario) -> int:
    client_id = getattr(usuario, "client_id", None)
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não está vinculado a uma conta",
        )
    return client_id


def validar_papel_e_vinculo(
    db: Session,
    company_id: int,
    role: str,
    professional_id: Optional[int],
) -> Optional[int]:
    """Regra unica de papel + vinculo, usada no cadastro e na edicao.

    Devolve o professional_id que deve ser GRAVADO (None quando o papel nao usa
    vinculo). Levanta 422 para papel invalido e 409/404 para vinculo incoerente.
    """
    role = (role or "").strip()
    if role not in PAPEIS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f'Papel "{role}" não existe. Use um destes: {", ".join(PAPEIS_VALIDOS)}.'
            ),
        )

    if role in PAPEIS_COM_PROFISSIONAL_OBRIGATORIO:
        if not professional_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f'O papel "{role}" precisa estar vinculado a um profissional. '
                    "Sem esse vínculo o sistema não sabe de quem é o usuário "
                    "logado, e a separação entre profissionais não funciona. "
                    "Cadastre o profissional em Profissionais e escolha ele aqui."
                ),
            )
        prof = (
            db.query(Professional)
            .filter(
                Professional.id == professional_id,
                Professional.company_id == company_id,
            )
            .first()
        )
        if not prof:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profissional não encontrado nesta empresa",
            )
        if not prof.active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f'O profissional "{prof.name}" está inativo. Reative o cadastro '
                    "antes de vincular um usuário a ele."
                ),
            )
        return prof.id

    if professional_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f'O papel "{role}" não usa vínculo com profissional. '
                "Vínculo clínico existe para quem atende paciente "
                f"({', '.join(PAPEIS_COM_PROFISSIONAL_OBRIGATORIO)})."
            ),
        )
    return None


def _administradores_ativos(db: Session, company_id: int, excluir_id: int = 0) -> int:
    q = db.query(User).filter(
        User.company_id == company_id,
        User.is_active.is_(True),
        User.role.in_(list(PAPEIS_QUE_ADMINISTRAM_USUARIOS)),
    )
    if excluir_id:
        q = q.filter(User.id != excluir_id)
    return q.count()


def _saida(db: Session, u: User) -> ClinicaUsuarioOut:
    nome_prof = None
    if u.professional_id:
        nome_prof = (
            db.query(Professional.name).filter(Professional.id == u.professional_id).scalar()
        )
    return ClinicaUsuarioOut(
        id=u.id,
        name=u.name,
        email=u.email,
        role=u.role,
        role_rotulo=ROTULOS_DE_PAPEL.get(u.role, u.role),
        professional_id=u.professional_id,
        professional_nome=nome_prof,
        is_active=u.is_active,
    )


def _buscar(db: Session, user_id: int, company_id: int) -> User:
    obj = (
        db.query(User)
        .filter(User.id == user_id, User.company_id == company_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Usuário não encontrado nesta clínica")
    return obj


# --------------------------------------------------------------------- endpoints
@router.get("/papeis")
def listar_papeis(usuario=Depends(exigir_admin_de_usuarios)):
    """Papeis disponiveis com rotulo e se exigem vinculo com profissional."""
    return [
        {
            "role": papel,
            "rotulo": ROTULOS_DE_PAPEL.get(papel, papel),
            "exige_profissional": papel in PAPEIS_COM_PROFISSIONAL_OBRIGATORIO,
        }
        for papel in ("clinic_admin", "clinical_professional", "service_professional",
                      "admin", "manager", "staff")
    ]


@router.get("/eu", response_model=EuClinicaOut)
def quem_sou_eu(db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Papel do usuario logado, vinculo e o que o papel permite — para a TELA.

    Existe porque os papeis clinicos sao invisiveis no frontend hoje: o menu usa
    permissoes de equipe, nao papel clinico. Sem este endpoint a tela de Equipe
    so descobriria que nao pode administrar depois de tomar um 403, mostrando
    uma tela que nao funciona para quem entrou nela.
    """
    # mesma regra da dependencia: dono do workspace e admin da clinica dele.
    from backend.services.papel_clinico import _papel_do_usuario

    papel = _papel_do_usuario(usuario)
    nome_prof = None
    professional_id = getattr(usuario, "professional_id", None)
    if professional_id:
        nome_prof = (
            db.query(Professional.name)
            .filter(Professional.id == professional_id)
            .scalar()
        )
    return EuClinicaOut(
        id=getattr(usuario, "id", 0),
        name=getattr(usuario, "name", "") or "",
        email=getattr(usuario, "email", "") or "",
        role=papel,
        role_rotulo=ROTULOS_DE_PAPEL.get(papel, papel or "sem papel"),
        professional_id=professional_id,
        professional_nome=nome_prof,
        pode_administrar_usuarios=papel in PAPEIS_QUE_ADMINISTRAM_USUARIOS,
        ve_prontuario=papel in PAPEIS_QUE_VEEM_PRONTUARIO,
    )


@router.get("", response_model=List[ClinicaUsuarioOut])
def listar(
    incluir_inativos: bool = True,
    db: Session = Depends(get_db),
    usuario=Depends(exigir_admin_de_usuarios),
):
    company_id = _company_id(usuario)
    q = db.query(User).filter(User.company_id == company_id)
    if not incluir_inativos:
        q = q.filter(User.is_active.is_(True))
    return [_saida(db, u) for u in q.order_by(User.name.asc()).all()]


@router.post("", response_model=ClinicaUsuarioOut, status_code=status.HTTP_201_CREATED)
def criar(
    dados: ClinicaUsuarioIn,
    db: Session = Depends(get_db),
    usuario=Depends(exigir_admin_de_usuarios),
):
    company_id = _company_id(usuario)
    client_id = _client_id(usuario)
    email = dados.email.strip().lower()

    if db.query(User.id).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Já existe um usuário com o e-mail "{email}"',
        )

    professional_id = validar_papel_e_vinculo(
        db, company_id, dados.role, dados.professional_id
    )

    novo = User(
        client_id=client_id,
        company_id=company_id,
        name=dados.name.strip(),
        email=email,
        password=hash_password(dados.password),
        role=dados.role.strip(),
        professional_id=professional_id,
        is_active=True,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    logger.info("usuario da clinica criado id=%s papel=%s empresa=%s",
                novo.id, novo.role, company_id)
    return _saida(db, novo)


@router.patch("/{user_id}", response_model=ClinicaUsuarioOut)
def atualizar(
    user_id: int,
    dados: ClinicaUsuarioPatch,
    db: Session = Depends(get_db),
    usuario=Depends(exigir_admin_de_usuarios),
):
    company_id = _company_id(usuario)
    obj = _buscar(db, user_id, company_id)

    papel_novo = dados.role if dados.role is not None else obj.role
    vinculo_novo = (
        dados.professional_id
        if "professional_id" in getattr(dados, "model_fields_set", set())
        else obj.professional_id
    )

    # Nao deixar a clinica sem administrador: quem faz isso se tranca pra fora.
    if (papel_novo not in PAPEIS_QUE_ADMINISTRAM_USUARIOS) and (
        obj.role in PAPEIS_QUE_ADMINISTRAM_USUARIOS
    ):
        if _administradores_ativos(db, company_id, excluir_id=obj.id) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Este é o último administrador ativo da clínica. "
                    "Promova outro usuário antes de mudar o papel dele."
                ),
            )

    if dados.is_active is False and obj.role in PAPEIS_QUE_ADMINISTRAM_USUARIOS:
        if _administradores_ativos(db, company_id, excluir_id=obj.id) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Este é o último administrador ativo da clínica e não pode ser "
                    "desativado. Promova outro usuário antes."
                ),
            )

    professional_id = validar_papel_e_vinculo(db, company_id, papel_novo, vinculo_novo)

    if dados.name is not None:
        obj.name = dados.name.strip()
    obj.role = papel_novo.strip()
    obj.professional_id = professional_id
    if dados.is_active is not None:
        obj.is_active = dados.is_active

    db.commit()
    db.refresh(obj)
    logger.info("usuario da clinica atualizado id=%s papel=%s empresa=%s",
                obj.id, obj.role, company_id)
    return _saida(db, obj)
