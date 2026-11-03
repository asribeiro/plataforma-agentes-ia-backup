"""API administrativa de pacientes do módulo de prontuário."""

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import (
    ClinicalNote,
    Patient,
    PatientAppointment,
    PatientTimelineEvent,
    SatisfactionSurvey,
    Treatment,
    Lead,
)
from backend.services.papel_clinico import configurar_contexto_clinico
from backend.services.papel_clinico import _papel_do_usuario

router = APIRouter(prefix="/api/patients", tags=["patient-record"])


_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


def _digits(value: Optional[str]) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_name(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().split())


def _validate_cpf_digits(value: str) -> bool:
    digits = _digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False

    def calc_digit(nums: list[int], weight_start: int) -> int:
        total = sum(num * weight for num, weight in zip(nums, range(weight_start, weight_start - len(nums), -1)))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    numbers = [int(d) for d in digits]
    first = calc_digit(numbers[:9], 10)
    second = calc_digit(numbers[:10], 11)
    return numbers[9] == first and numbers[10] == second


class PatientCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    cpf: Optional[str] = Field(None, min_length=11, max_length=14)
    birth_date: Optional[date] = None
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=255)
    insurance: Optional[str] = Field(None, max_length=160)
    source: Optional[str] = Field(None, max_length=80)
    lead_id: Optional[int] = None
    lgpd_consent_at: Optional[date] = None
    lgpd_consent_version: Optional[str] = Field(None, max_length=40)

    @validator("name")
    def validate_name(cls, value):
        normalized = _normalize_name(value)
        if len(normalized) < 2:
            raise ValueError("nome deve ter ao menos 2 caracteres")
        if len(normalized) > 255:
            raise ValueError("nome deve ter no máximo 255 caracteres")
        return normalized

    @validator("cpf")
    def normalize_cpf(cls, value):
        if value is None:
            return value

        digits = _digits(value)
        if len(digits) != 11:
            raise ValueError("CPF deve conter 11 dígitos")
        if not _validate_cpf_digits(digits):
            raise ValueError("CPF inválido")
        return digits

    @validator("phone")
    def normalize_phone(cls, value):
        if value is None:
            return value

        digits = _digits(value)
        if len(digits) < 10 or len(digits) > 11:
            raise ValueError("telefone deve conter DDD + número válido")
        if len(digits) == 11 and digits[2] == "9":
            return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"

    @validator("email")
    def validate_email(cls, value):
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            return None
        if not _EMAIL_RE.fullmatch(normalized):
            raise ValueError("e-mail inválido")
        return normalized.lower()

    @validator("insurance", "source")
    def normalize_optional_text(cls, value):
        if value is None:
            return value
        return " ".join(value.strip().split())[:160] if value == value.strip() else " ".join(value.strip().split())[:160]

    @validator("lgpd_consent_at")
    def require_consent_version(cls, value, values):
        if value is not None and not values.get("lgpd_consent_version"):
            raise ValueError("versão do termo LGPD é obrigatória com o consentimento")
        return value


class PatientListItem(BaseModel):
    id: str
    name: str
    cpf: Optional[str]
    birth_date: Optional[date]
    phone: Optional[str]
    email: Optional[str]
    insurance: Optional[str]
    lifecycle_status: str
    last_appointment_at: Optional[object]
    next_appointment_at: Optional[object]
    no_show_count: int
    total_appointments: int

    class Config:
        orm_mode = True


class PatientAppointmentItem(BaseModel):
    id: str
    starts_at: object
    duration_minutes: int
    source: str
    status: str
    professional_id: int
    note_text: Optional[str] = None


class PatientTimelineItem(BaseModel):
    id: str
    event_type: str
    payload: dict
    occurred_at: object


class PatientDetail(BaseModel):
    id: str
    name: str
    cpf: Optional[str]
    birth_date: Optional[date]
    phone: Optional[str]
    email: Optional[str]
    insurance: Optional[str]
    source: Optional[str]
    lifecycle_status: str
    lgpd_consent_at: Optional[object]
    lgpd_consent_version: Optional[str]
    last_appointment_at: Optional[object]
    next_appointment_at: Optional[object]
    total_appointments: int
    no_show_count: int
    appointments: list[PatientAppointmentItem]
    timeline: list[PatientTimelineItem]


def _patient_metrics(db: Session):
    last_appointment = (
        db.query(func.max(PatientAppointment.starts_at))
        .filter(
            PatientAppointment.patient_id == Patient.id,
            PatientAppointment.clinic_id == Patient.clinic_id,
            PatientAppointment.status == "attended",
        )
        .correlate(Patient)
        .scalar_subquery()
    )
    next_appointment = (
        db.query(func.min(PatientAppointment.starts_at))
        .filter(
            PatientAppointment.patient_id == Patient.id,
            PatientAppointment.clinic_id == Patient.clinic_id,
            PatientAppointment.starts_at >= func.now(),
            PatientAppointment.status.in_(("scheduled", "confirmed")),
        )
        .correlate(Patient)
        .scalar_subquery()
    )
    no_show_count = (
        db.query(func.count(PatientAppointment.id))
        .filter(
            PatientAppointment.patient_id == Patient.id,
            PatientAppointment.clinic_id == Patient.clinic_id,
            PatientAppointment.status == "no_show",
        )
        .correlate(Patient)
        .scalar_subquery()
    )
    total_appointments = (
        db.query(func.count(PatientAppointment.id))
        .filter(
            PatientAppointment.patient_id == Patient.id,
            PatientAppointment.clinic_id == Patient.clinic_id,
        )
        .correlate(Patient)
        .scalar_subquery()
    )
    return last_appointment, next_appointment, no_show_count, total_appointments


@router.get("", response_model=list[PatientListItem])
def list_patients(
    search: Optional[str] = Query(None, min_length=1, max_length=120),
    lifecycle_status: Optional[str] = Query(None, max_length=30),
    insurance: Optional[str] = Query(None, max_length=160),
    professional_id: Optional[int] = Query(None, ge=1),
    without_return: bool = False,
    at_risk: bool = False,
    low_nps: bool = False,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    last_appointment, next_appointment, no_show_count, total_appointments = _patient_metrics(db)
    query = db.query(
        Patient,
        last_appointment.label("last_appointment_at"),
        next_appointment.label("next_appointment_at"),
        no_show_count.label("no_show_count"),
        total_appointments.label("total_appointments"),
    ).filter(Patient.clinic_id == clinic_id)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(Patient.name.ilike(term), Patient.phone.ilike(term), Patient.cpf.ilike(term)))
    if lifecycle_status:
        query = query.filter(Patient.lifecycle_status == lifecycle_status)
    if insurance:
        query = query.filter(Patient.insurance == insurance)
    if professional_id:
        query = query.filter(
            exists().where(
                and_(
                    Treatment.patient_id == Patient.id,
                    Treatment.clinic_id == clinic_id,
                    Treatment.professional_id == professional_id,
                )
            )
        )
    if without_return:
        query = query.filter(next_appointment.is_(None))
    if at_risk:
        query = query.filter(Patient.lifecycle_status == "at_risk")
    if low_nps:
        query = query.filter(
            exists().where(
                and_(
                    SatisfactionSurvey.patient_id == Patient.id,
                    SatisfactionSurvey.clinic_id == clinic_id,
                    SatisfactionSurvey.nps_score <= 6,
                )
            )
        )

    return [
        PatientListItem(
            id=patient.id,
            name=patient.name,
            cpf=patient.cpf,
            birth_date=patient.birth_date,
            phone=patient.phone,
            email=patient.email,
            insurance=patient.insurance,
            lifecycle_status=patient.lifecycle_status,
            last_appointment_at=last_at,
            next_appointment_at=next_at,
            no_show_count=int(no_shows or 0),
            total_appointments=int(total or 0),
        )
        for patient, last_at, next_at, no_shows, total in query.order_by(Patient.name.asc()).all()
    ]


@router.post("", response_model=PatientListItem, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    if payload.lgpd_consent_at and not payload.lgpd_consent_version:
        raise HTTPException(status_code=422, detail="versão do termo LGPD é obrigatória")
    if payload.lead_id is not None:
        lead_exists = db.query(Lead.id).filter(
            Lead.id == payload.lead_id,
            Lead.company_id == clinic_id,
        ).first()
        if lead_exists is None:
            raise HTTPException(status_code=422, detail="lead não pertence à clínica")
    patient = Patient(clinic_id=clinic_id, **payload.dict())
    db.add(patient)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="CPF já cadastrado nesta clínica") from exc
    db.refresh(patient)
    return PatientListItem(
        id=patient.id,
        name=patient.name,
        cpf=patient.cpf,
        birth_date=patient.birth_date,
        phone=patient.phone,
        email=patient.email,
        insurance=patient.insurance,
        lifecycle_status=patient.lifecycle_status,
        last_appointment_at=None,
        next_appointment_at=None,
        no_show_count=0,
        total_appointments=0,
    )


@router.get("/{patient_id}", response_model=PatientDetail)
def get_patient(
    patient_id: str,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
    ).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    last_at, next_at, no_shows, total = (
        value
        for value in _patient_metrics(db)
    )
    metrics = db.query(last_at, next_at, no_shows, total).filter(Patient.id == patient.id).one()
    appointments = db.query(PatientAppointment).filter(
        PatientAppointment.patient_id == patient.id,
        PatientAppointment.clinic_id == clinic_id,
    ).order_by(PatientAppointment.starts_at.desc()).all()
    notes = {
        note.appointment_id: note
        for note in db.query(ClinicalNote).filter(
            ClinicalNote.patient_id == patient.id,
            ClinicalNote.clinic_id == clinic_id,
        ).all()
    }
    role = _papel_do_usuario(usuario)
    appointment_items = []
    for appointment in appointments:
        note = notes.get(appointment.id) if role in ("admin", "clinic_admin", "clinical_professional") else None
        appointment_items.append(
            PatientAppointmentItem(
                id=appointment.id,
                starts_at=appointment.starts_at,
                duration_minutes=appointment.duration_minutes,
                source=appointment.source,
                status=appointment.status,
                professional_id=appointment.professional_id,
                note_text=note.note_text if note else None,
            )
        )
    timeline = db.query(PatientTimelineEvent).filter(
        PatientTimelineEvent.patient_id == patient.id,
        PatientTimelineEvent.clinic_id == clinic_id,
    ).order_by(PatientTimelineEvent.occurred_at.desc()).all()
    return PatientDetail(
        id=patient.id,
        name=patient.name,
        cpf=patient.cpf,
        birth_date=patient.birth_date,
        phone=patient.phone,
        email=patient.email,
        insurance=patient.insurance,
        source=patient.source,
        lifecycle_status=patient.lifecycle_status,
        lgpd_consent_at=patient.lgpd_consent_at,
        lgpd_consent_version=patient.lgpd_consent_version,
        last_appointment_at=metrics[0],
        next_appointment_at=metrics[1],
        no_show_count=int(metrics[2] or 0),
        total_appointments=int(metrics[3] or 0),
        appointments=appointment_items,
        timeline=[
            PatientTimelineItem(
                id=event.id,
                event_type=event.event_type,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
            for event in timeline
        ],
    )
