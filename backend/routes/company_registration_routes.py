"""Cadastro administrativo completo de empresas clientes."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from backend.auth import get_current_user, hash_password
from backend.db import get_db
from backend.models import (
    Client,
    ClientCompany,
    Company,
    CompanyAuditEvent,
    CompanyRegistrationDraft,
    Customer,
    CustomerManagedCompany,
    User,
)
from backend.routes.company import COMPANY_LOGO_DIR, COMPANY_LOGO_PUBLIC_PREFIX, is_internal_admin
from backend.services.company_access_control import normalize_account_email
from backend.services.password_reset_service import create_password_setup_token_for_account
from backend.services.transactional_email_service import send_password_setup_email


router = APIRouter(prefix="/api/admin/company-registration", tags=["company-registration"])


PLANS = {
    "consultorio": ("mono", 1),
    "clinica": ("up_to_4", 4),
    "clinica_plus": ("up_to_10", 10),
    "redes_clinicas": ("network", 30),
}


class CompanyRegistrationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    person_type: str = Field(default="PJ", pattern="^(PF|PJ)$")
    customer_id: Optional[int] = None
    document: str = Field(min_length=11, max_length=18)
    legal_name: str = Field(min_length=1, max_length=255)
    trade_name: str = Field(min_length=1, max_length=255)
    municipal_registration: Optional[str] = Field(default=None, max_length=40)
    postal_code: Optional[str] = Field(default=None, max_length=8)
    address: Optional[str] = Field(default=None, max_length=255)
    address_number: Optional[str] = Field(default=None, max_length=30)
    address_complement: Optional[str] = Field(default=None, max_length=120)
    province: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, min_length=2, max_length=2)
    fixed_phone: Optional[str] = Field(default=None, max_length=30)
    website: Optional[str] = Field(default=None, max_length=255)
    instagram: Optional[str] = Field(default=None, max_length=255)
    administrative_responsible_name: str = Field(min_length=1, max_length=255)
    administrative_responsible_email: EmailStr
    administrative_responsible_phone: str = Field(min_length=8, max_length=30)
    technical_responsible_professional_id: Optional[int] = None
    technical_responsible_cro: Optional[str] = Field(default=None, max_length=30)
    technical_responsible_cro_uf: Optional[str] = Field(default=None, min_length=2, max_length=2)
    business_hours: dict[str, Any] = Field(default_factory=dict)
    ai_whatsapp: Optional[str] = Field(default=None, max_length=30)
    accepts_insurance: bool = False
    accepted_insurance: list[str] = Field(default_factory=list)
    plan: str = Field(pattern="^(consultorio|clinica|clinica_plus|redes_clinicas)$")
    billing_interval: str = Field(default="monthly", pattern="^(monthly|yearly)$")
    is_founder_customer: bool = False
    trial_days: int = Field(default=7, ge=0, le=365)
    start_date: Optional[str] = None
    billing_email: Optional[EmailStr] = None
    preferred_payment_method: Optional[str] = Field(default=None, max_length=40)

    @field_validator("document", mode="before")
    @classmethod
    def normalize_document(cls, value: str) -> str:
        digits = "".join(char for char in str(value or "") if char.isdigit())
        if len(digits) not in {11, 14}:
            raise ValueError("Informe um CPF ou CNPJ válido")
        return digits

    @field_validator("state", "technical_responsible_cro_uf", mode="before")
    @classmethod
    def normalize_state(cls, value: Optional[str]) -> Optional[str]:
        return value.upper().strip() if value else value

    @field_validator("accepted_insurance")
    @classmethod
    def normalize_insurance(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class DraftOut(BaseModel):
    id: int
    payload: dict[str, Any]
    logo_url: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    completed_company_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)


ALLOWED_LOGO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_LOGO_BYTES = 5 * 1024 * 1024


def _require_platform_admin(user) -> None:
    if not is_internal_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores da plataforma")


def _require_company_admin(user) -> None:
    if is_internal_admin(user):
        return
    if isinstance(user, User) and user.role in {"admin", "clinic_admin"}:
        return
    raise HTTPException(status_code=403, detail="Acesso restrito ao administrador da empresa")


def _company_payload(company: Company) -> dict[str, Any]:
    return {
        "person_type": company.person_type or "PJ",
        "document": company.cnpj or "",
        "legal_name": company.name or "",
        "trade_name": company.name_company or company.name or "",
        "municipal_registration": company.municipal_registration,
        "postal_code": company.postal_code,
        "address": company.address,
        "address_number": company.address_number,
        "address_complement": company.address_complement,
        "province": company.province,
        "city": company.city,
        "state": company.state,
        "fixed_phone": company.fixed_phone,
        "website": company.website,
        "instagram": company.instagram,
        "administrative_responsible_name": company.administrative_responsible_name or "",
        "administrative_responsible_email": company.administrative_responsible_email or "",
        "administrative_responsible_phone": company.administrative_responsible_phone or "",
        "technical_responsible_professional_id": company.technical_responsible_professional_id,
        "technical_responsible_cro": company.technical_responsible_cro,
        "technical_responsible_cro_uf": company.technical_responsible_cro_uf,
        "business_hours": company.business_hours or {},
        "ai_whatsapp": company.ai_whatsapp,
        "accepts_insurance": bool(company.accepts_insurance),
        "accepted_insurance": company.accepted_insurance or [],
        "plan": "redes_clinicas" if company.professional_tier == "network" else "consultorio",
        "billing_interval": company.billing_interval or "monthly",
        "is_founder_customer": bool(company.is_founder_customer),
        "trial_days": 0,
        "billing_email": company.billing_email,
        "preferred_payment_method": company.preferred_payment_method,
    }


@router.get("/current", response_model=CompanyRegistrationPayload)
def get_current_registration(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_company_admin(user)
    company = db.query(Company).filter(Company.id == getattr(user, "company_id", None)).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return CompanyRegistrationPayload.model_validate(_company_payload(company))


@router.put("/current", response_model=CompanyRegistrationPayload)
def update_current_registration(
    payload: CompanyRegistrationPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_company_admin(user)
    company = db.query(Company).filter(Company.id == getattr(user, "company_id", None)).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    duplicate = (
        db.query(Company)
        .filter(Company.cnpj == payload.document, Company.id != company.id)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="CPF/CNPJ já está em uso")
    before = _company_payload(company)
    tier, max_professionals = PLANS[payload.plan]
    for field, value in {
        "name": payload.legal_name,
        "name_company": payload.trade_name,
        "cnpj": payload.document,
        "person_type": payload.person_type,
        "municipal_registration": payload.municipal_registration,
        "postal_code": payload.postal_code,
        "address": payload.address,
        "address_number": payload.address_number,
        "address_complement": payload.address_complement,
        "province": payload.province,
        "city": payload.city,
        "state": payload.state,
        "fixed_phone": payload.fixed_phone,
        "website": payload.website,
        "instagram": payload.instagram,
        "ai_whatsapp": payload.ai_whatsapp,
        "accepts_insurance": payload.accepts_insurance,
        "accepted_insurance": payload.accepted_insurance,
        "business_hours": payload.business_hours,
        "administrative_responsible_name": payload.administrative_responsible_name,
        "administrative_responsible_email": str(payload.administrative_responsible_email),
        "administrative_responsible_phone": payload.administrative_responsible_phone,
        "technical_responsible_professional_id": payload.technical_responsible_professional_id,
        "technical_responsible_cro": payload.technical_responsible_cro,
        "technical_responsible_cro_uf": payload.technical_responsible_cro_uf,
        "billing_email": str(payload.billing_email) if payload.billing_email else None,
        "preferred_payment_method": payload.preferred_payment_method,
        "billing_interval": payload.billing_interval,
        "is_founder_customer": payload.is_founder_customer,
        "professional_tier": tier,
        "max_professionals": max_professionals,
    }.items():
        setattr(company, field, value)
    actor_client_id, actor_user_id = _actor_ids(user)
    db.add(CompanyAuditEvent(
        company_id=company.id,
        actor_client_id=actor_client_id,
        actor_user_id=actor_user_id,
        action="updated",
        before_data=before,
        after_data=payload.model_dump(mode="json"),
    ))
    db.commit()
    db.refresh(company)
    return CompanyRegistrationPayload.model_validate(_company_payload(company))


def _actor_ids(user) -> tuple[Optional[int], Optional[int]]:
    if isinstance(user, Client):
        return int(user.id), None
    return getattr(user, "client_id", None), int(user.id) if isinstance(user, User) else None


def _draft_output(draft: CompanyRegistrationDraft) -> DraftOut:
    return DraftOut(
        id=int(draft.id),
        payload=draft.payload or {},
        logo_url=draft.logo_url,
        status=str(draft.status),
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        completed_company_id=int(draft.completed_company_id) if draft.completed_company_id else None,
    )


@router.get("/drafts", response_model=list[DraftOut])
def list_registration_drafts(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_platform_admin(user)
    drafts = (
        db.query(CompanyRegistrationDraft)
        .filter(CompanyRegistrationDraft.status == "draft")
        .order_by(CompanyRegistrationDraft.updated_at.desc())
        .all()
    )
    return [_draft_output(draft) for draft in drafts]


@router.post("/drafts", response_model=DraftOut, status_code=status.HTTP_201_CREATED)
def create_registration_draft(
    payload: CompanyRegistrationPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_platform_admin(user)
    client_id, user_id = _actor_ids(user)
    draft = CompanyRegistrationDraft(
        created_by_client_id=client_id,
        created_by_user_id=user_id,
        payload=payload.model_dump(mode="json"),
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _draft_output(draft)


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_registration_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_platform_admin(user)
    draft = db.query(CompanyRegistrationDraft).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado")
    return _draft_output(draft)


@router.put("/drafts/{draft_id}", response_model=DraftOut)
def update_registration_draft(
    draft_id: int,
    payload: CompanyRegistrationPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_platform_admin(user)
    draft = db.query(CompanyRegistrationDraft).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Este rascunho não pode mais ser editado")
    draft.payload = payload.model_dump(mode="json")
    db.commit()
    db.refresh(draft)
    return _draft_output(draft)


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_registration_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_platform_admin(user)
    draft = db.query(CompanyRegistrationDraft).filter_by(id=draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado")
    draft.status = "cancelled"
    db.commit()


@router.post("/drafts/{draft_id}/logo", response_model=DraftOut)
async def upload_registration_draft_logo(
    draft_id: int,
    logo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_platform_admin(user)
    draft = db.query(CompanyRegistrationDraft).filter_by(id=draft_id).first()
    if not draft or draft.status != "draft":
        raise HTTPException(status_code=404, detail="Rascunho ativo não encontrado")
    if logo.content_type not in ALLOWED_LOGO_TYPES:
        raise HTTPException(status_code=415, detail="A logo deve ser JPG, PNG, WEBP ou GIF")
    contents = await logo.read()
    if len(contents) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="A logo deve ter no máximo 5 MB")
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }[logo.content_type]
    filename = f"draft_{draft.id}_{uuid4().hex}{extension}"
    os.makedirs(COMPANY_LOGO_DIR, exist_ok=True)
    Path(COMPANY_LOGO_DIR, filename).write_bytes(contents)
    draft.logo_url = f"{COMPANY_LOGO_PUBLIC_PREFIX.rstrip('/')}/{filename}"
    db.commit()
    db.refresh(draft)
    return _draft_output(draft)


@router.post("/drafts/{draft_id}/create")
def create_company_from_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_platform_admin(user)
    draft = db.query(CompanyRegistrationDraft).filter_by(id=draft_id).first()
    if not draft or draft.status != "draft":
        raise HTTPException(status_code=404, detail="Rascunho ativo não encontrado")
    payload = CompanyRegistrationPayload.model_validate(draft.payload or {})
    document = payload.document
    if db.query(Company).filter(Company.cnpj == document).first():
        raise HTTPException(status_code=409, detail="CPF/CNPJ já está em uso")
    email = normalize_account_email(str(payload.administrative_responsible_email))
    if db.query(Client).filter(Client.email == email).first() or db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="O e-mail do administrador já está em uso")
    if payload.customer_id is not None:
        customer = db.query(Customer).filter(Customer.id == payload.customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente selecionado não encontrado")
        owner_company = db.query(Company).filter(Company.id == customer.company_id).first()
        if owner_company and owner_company.professional_tier == "network":
            used_units = (
                db.query(CustomerManagedCompany)
                .filter(
                    CustomerManagedCompany.owner_company_id == owner_company.id,
                    CustomerManagedCompany.lifecycle_status.in_(("active", "trialing")),
                )
                .count()
            )
            unit_limit = int(owner_company.network_unit_limit or 30)
            if used_units >= unit_limit:
                raise HTTPException(
                    status_code=409,
                    detail=f"A rede já atingiu o limite de {unit_limit} unidades.",
                )

    tier, max_professionals = PLANS[payload.plan]
    now = datetime.now(timezone.utc)
    company = Company(
        name=payload.legal_name,
        name_company=payload.trade_name,
        cnpj=document,
        logo_url=draft.logo_url,
        person_type=payload.person_type,
        municipal_registration=payload.municipal_registration,
        postal_code=payload.postal_code,
        address=payload.address,
        address_number=payload.address_number,
        address_complement=payload.address_complement,
        province=payload.province,
        city=payload.city,
        state=payload.state,
        fixed_phone=payload.fixed_phone,
        website=payload.website,
        instagram=payload.instagram,
        ai_whatsapp=payload.ai_whatsapp,
        accepts_insurance=payload.accepts_insurance,
        accepted_insurance=payload.accepted_insurance,
        business_hours=payload.business_hours,
        administrative_responsible_name=payload.administrative_responsible_name,
        administrative_responsible_email=email,
        administrative_responsible_phone=payload.administrative_responsible_phone,
        technical_responsible_professional_id=payload.technical_responsible_professional_id,
        technical_responsible_cro=payload.technical_responsible_cro,
        technical_responsible_cro_uf=payload.technical_responsible_cro_uf,
        billing_email=str(payload.billing_email) if payload.billing_email else email,
        preferred_payment_method=payload.preferred_payment_method,
        billing_interval=payload.billing_interval,
        is_founder_customer=payload.is_founder_customer,
        professional_tier=tier,
        max_professionals=max_professionals,
        network_unit_limit=30 if tier == "network" else None,
        registration_started_at=now,
    )
    db.add(company)
    db.flush()
    client = Client(
        email=email,
        password=hash_password(__import__("secrets").token_urlsafe(32)),
        company_id=company.id,
        ownership_company_id=company.id,
        is_active=True,
    )
    db.add(client)
    db.flush()
    db.add(ClientCompany(client_id=client.id, company_id=company.id))
    db.add(User(
        client_id=client.id,
        company_id=company.id,
        email=email,
        password=client.password,
        name=payload.administrative_responsible_name,
        role="clinic_admin",
        is_active=True,
    ))
    if payload.customer_id is not None:
        db.add(CustomerManagedCompany(
            owner_company_id=customer.company_id,
            customer_id=customer.id,
            managed_company_id=company.id,
            created_by_client_id=_actor_ids(user)[0],
            trial_days=payload.trial_days,
            trial_started_at=now if payload.trial_days else None,
            trial_ends_at=now + timedelta(days=payload.trial_days) if payload.trial_days else None,
            lifecycle_status="trialing" if payload.trial_days else "active",
        ))
    actor_client_id, actor_user_id = _actor_ids(user)
    db.add(CompanyAuditEvent(
        company_id=company.id,
        actor_client_id=actor_client_id,
        actor_user_id=actor_user_id,
        action="created",
        after_data=payload.model_dump(mode="json"),
        metadata_json={"source": "registration_draft", "draft_id": draft.id},
    ))
    draft.status = "created"
    draft.completed_company_id = company.id
    draft.completed_at = now
    db.commit()
    invitation_sent = False
    invitation_error = None
    try:
        setup = create_password_setup_token_for_account(db, account=client)
        result = send_password_setup_email(
            to_email=email,
            to_name=payload.administrative_responsible_name,
            workspace_name=payload.trade_name,
            setup_url=setup.reset_url,
            expires_minutes=setup.expires_minutes,
        )
        invitation_sent = bool(getattr(result, "sent", True))
    except (ValueError, RuntimeError) as exc:
        invitation_error = exc.__class__.__name__
    return {
        "company_id": int(company.id),
        "message": "Empresa criada com sucesso.",
        "invitation_sent": invitation_sent,
        "invitation_error": invitation_error,
    }
