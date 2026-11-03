"""Planos de tratamento e procedimentos do prontuário clínico."""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Patient, PatientAppointment, Professional, Treatment, TreatmentProcedure, User
from backend.services.papel_clinico import _papel_do_usuario, configurar_contexto_clinico

router = APIRouter(prefix="/api/treatments", tags=["treatments"])
CLINICAL_ROLES = {"admin", "clinic_admin", "clinical_professional"}
TREATMENT_STATUSES = {"proposed", "approved", "in_progress", "completed", "abandoned"}
RECURRENCE_FREQUENCIES = {"weekly", "biweekly", "monthly", "semiannual", "custom"}


def _professional(db: Session, clinic_id: int, professional_id: int):
    professional = (
        db.query(Professional)
        .filter(Professional.id == professional_id, Professional.company_id == clinic_id, Professional.active.is_(True))
        .first()
    )
    if professional is None:
        raise HTTPException(status_code=404, detail="Profissional não encontrado ou inativo")

    user = (
        db.query(User)
        .filter(
            User.company_id == clinic_id,
            User.professional_id == professional_id,
            User.is_active.is_(True),
            User.role.in_({"clinic_admin", "clinical_professional"}),
        )
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=403,
            detail="O profissional selecionado precisa estar cadastrado como usuário do sistema com perfil de Profissional de atendimento ou Admin da Clínica. Verifique em Configurações → Minha Empresa → Administração de usuários.",
        )
    return professional


class TreatmentCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    professional_id: int = Field(..., ge=1)
    total_value: Decimal = Field(default=Decimal("0"), ge=0)
    start_date: Optional[date] = None
    expected_end_date: Optional[date] = None


class TreatmentProcedureCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    tooth_region: Optional[str] = Field(None, max_length=120)
    value: Decimal = Field(default=Decimal("0"), ge=0)
    recurrence_frequency: Optional[str] = None
    recurrence_interval: Optional[int] = Field(None, ge=1, le=365)
    recurrence_sessions: Optional[int] = Field(None, ge=1, le=500)
    recurrence_end_date: Optional[date] = None

    @field_validator("recurrence_frequency")
    def validate_frequency(cls, value):
        if value is not None and value not in RECURRENCE_FREQUENCIES:
            raise ValueError(f"frequência deve ser uma destas: {', '.join(sorted(RECURRENCE_FREQUENCIES))}")
        return value

    @model_validator(mode="after")
    def validate_recurrence_target(self):
        if self.recurrence_end_date is not None and self.recurrence_sessions:
            raise ValueError("recorrência deve informar sessões ou data final, não ambos")
        return self


class TreatmentProcedureOut(BaseModel):
    id: str
    name: str
    status: str
    recurrence_frequency: Optional[str]
    recurrence_sessions: Optional[int]
    recurrence_end_date: Optional[date]
    sessions_completed: int
    sessions_planned: Optional[int]


class TreatmentOut(BaseModel):
    id: str
    patient_id: str
    professional_id: int
    title: str
    description: Optional[str]
    status: str
    total_value: Decimal
    start_date: Optional[date]
    expected_end_date: Optional[date]
    procedures: list[TreatmentProcedureOut]


def _require_clinical_role(usuario):
    if _papel_do_usuario(usuario) not in CLINICAL_ROLES:
        raise HTTPException(status_code=403, detail="Seu papel não pode administrar planos de tratamento")


def _patient(db: Session, clinic_id: int, patient_id: str):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
    ).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    return patient


def _treatment_output(db: Session, treatment: Treatment) -> TreatmentOut:
    procedures = []
    for procedure in treatment.procedures:
        completed = db.query(func.count(PatientAppointment.id)).filter(
            PatientAppointment.clinic_id == treatment.clinic_id,
            PatientAppointment.treatment_procedure_id == procedure.id,
            PatientAppointment.status == "attended",
        ).scalar() or 0
        procedures.append(
            TreatmentProcedureOut(
                id=procedure.id,
                name=procedure.name,
                status=procedure.status,
                recurrence_frequency=procedure.recurrence_frequency,
                recurrence_sessions=procedure.recurrence_sessions,
                recurrence_end_date=procedure.recurrence_end_date,
                sessions_completed=int(completed),
                sessions_planned=procedure.recurrence_sessions,
            )
        )
    return TreatmentOut(
        id=treatment.id,
        patient_id=treatment.patient_id,
        professional_id=treatment.professional_id,
        title=treatment.title,
        description=treatment.description,
        status=treatment.status,
        total_value=treatment.total_value,
        start_date=treatment.start_date,
        expected_end_date=treatment.expected_end_date,
        procedures=procedures,
    )


@router.post("/patients/{patient_id}", response_model=TreatmentOut, status_code=status.HTTP_201_CREATED)
def create_treatment(
    patient_id: str,
    payload: TreatmentCreate,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    _patient(db, clinic_id, patient_id)
    _professional(db, clinic_id, payload.professional_id)
    treatment = Treatment(clinic_id=clinic_id, patient_id=patient_id, **payload.model_dump())
    db.add(treatment)
    db.commit()
    db.refresh(treatment)
    return _treatment_output(db, treatment)


@router.get("/patients/{patient_id}", response_model=list[TreatmentOut])
def list_treatments(
    patient_id: str,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _patient(db, clinic_id, patient_id)
    treatments = db.query(Treatment).filter(
        Treatment.patient_id == patient_id,
        Treatment.clinic_id == clinic_id,
    ).order_by(Treatment.created_at.desc()).all()
    return [_treatment_output(db, treatment) for treatment in treatments]


@router.post("/{treatment_id}/procedures", response_model=TreatmentOut, status_code=status.HTTP_201_CREATED)
def create_treatment_procedure(
    treatment_id: str,
    payload: TreatmentProcedureCreate,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    treatment = db.query(Treatment).filter(
        Treatment.id == treatment_id,
        Treatment.clinic_id == clinic_id,
    ).first()
    if treatment is None:
        raise HTTPException(status_code=404, detail="Plano de tratamento não encontrado")
    if payload.recurrence_frequency and not (
        payload.recurrence_sessions or payload.recurrence_end_date
    ):
        raise HTTPException(
            status_code=422,
            detail="procedimento recorrente exige número de sessões ou data final",
        )
    procedure = TreatmentProcedure(
        clinic_id=clinic_id,
        treatment_id=treatment.id,
        **payload.model_dump(),
    )
    db.add(procedure)
    db.commit()
    db.refresh(treatment)
    return _treatment_output(db, treatment)
