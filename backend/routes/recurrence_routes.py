"""Geração e remarcação de sessões recorrentes."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import (
    PatientAppointment,
    RecurrenceConflictTask,
    TreatmentProcedure,
)
from backend.services.papel_clinico import _papel_do_usuario, configurar_contexto_clinico
from backend.services.recurrence_service import generate_occurrences

router = APIRouter(prefix="/api/recurrence", tags=["treatment-recurrence"])
CLINICAL_ROLES = {"admin", "clinic_admin", "clinical_professional"}


class GenerateSessionsRequest(BaseModel):
    start_at: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    window_days: int = Field(default=90, ge=1, le=365)


class GeneratedSessionOut(BaseModel):
    appointment_id: str
    starts_at: datetime
    status: str
    conflict_task_id: int | None = None


class RecurrenceConflictTaskOut(BaseModel):
    id: int
    patient_id: str
    appointment_id: str
    status: str
    title: str
    created_at: datetime

    class Config:
        from_attributes = True


class RecurrenceConflictTaskUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|resolved|dismissed)$")


def _require_clinical_role(usuario):
    if _papel_do_usuario(usuario) not in CLINICAL_ROLES:
        raise HTTPException(status_code=403, detail="Seu papel não pode gerar recorrências")


@router.get("/tasks", response_model=list[RecurrenceConflictTaskOut])
def list_recurrence_tasks(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    query = db.query(RecurrenceConflictTask).filter(
        RecurrenceConflictTask.clinic_id == clinic_id
    )
    if status_filter:
        query = query.filter(RecurrenceConflictTask.status == status_filter)
    return query.order_by(RecurrenceConflictTask.created_at.desc()).limit(200).all()


@router.patch("/tasks/{task_id}", response_model=RecurrenceConflictTaskOut)
def update_recurrence_task(
    task_id: int,
    payload: RecurrenceConflictTaskUpdate,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    task = db.query(RecurrenceConflictTask).filter(
        RecurrenceConflictTask.id == task_id,
        RecurrenceConflictTask.clinic_id == clinic_id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa de conflito não encontrada")
    task.status = payload.status
    db.commit()
    db.refresh(task)
    return task


def _has_conflict(db, clinic_id, professional_id, starts_at, duration_minutes):
    end_at = starts_at + timedelta(minutes=duration_minutes)
    candidates = db.query(PatientAppointment).filter(
        PatientAppointment.clinic_id == clinic_id,
        PatientAppointment.professional_id == professional_id,
        PatientAppointment.starts_at < end_at,
        PatientAppointment.status.notin_(("cancelled", "cancelled_by_patient", "cancelled_by_clinic", "no_show")),
    ).all()
    return any(
        appointment.starts_at < end_at
        and appointment.starts_at + timedelta(minutes=appointment.duration_minutes) > starts_at
        for appointment in candidates
    )


@router.post("/procedures/{procedure_id}/generate", response_model=list[GeneratedSessionOut])
def generate_sessions(
    procedure_id: str,
    payload: GenerateSessionsRequest,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    procedure = db.query(TreatmentProcedure).filter(
        TreatmentProcedure.id == procedure_id,
        TreatmentProcedure.clinic_id == clinic_id,
    ).first()
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedimento não encontrado")
    if not procedure.recurrence_frequency:
        raise HTTPException(status_code=422, detail="Procedimento não possui recorrência configurada")
    treatment = procedure.treatment
    occurrences = generate_occurrences(
        payload.start_at,
        procedure.recurrence_frequency,
        interval=procedure.recurrence_interval or 1,
        sessions=procedure.recurrence_sessions,
        end_at=datetime.combine(procedure.recurrence_end_date, payload.start_at.time()) if procedure.recurrence_end_date else None,
        window_days=payload.window_days,
    )
    result = []
    for starts_at in occurrences:
        existing = db.query(PatientAppointment).filter(
            PatientAppointment.clinic_id == clinic_id,
            PatientAppointment.treatment_procedure_id == procedure.id,
            PatientAppointment.starts_at == starts_at,
        ).first()
        if existing:
            continue
        conflict = _has_conflict(db, clinic_id, treatment.professional_id, starts_at, payload.duration_minutes)
        appointment = PatientAppointment(
            clinic_id=clinic_id,
            patient_id=treatment.patient_id,
            professional_id=treatment.professional_id,
            treatment_procedure_id=procedure.id,
            starts_at=starts_at,
            duration_minutes=payload.duration_minutes,
            source="treatment_recurrence",
            status="pending_confirmation" if conflict else "scheduled",
        )
        db.add(appointment)
        db.flush()
        task = None
        if conflict:
            task = RecurrenceConflictTask(
                clinic_id=clinic_id,
                patient_id=treatment.patient_id,
                appointment_id=appointment.id,
                title="Confirmar horário conflitante de procedimento recorrente",
            )
            db.add(task)
            db.flush()
        result.append(
            GeneratedSessionOut(
                appointment_id=appointment.id,
                starts_at=starts_at,
                status=appointment.status,
                conflict_task_id=task.id if task else None,
            )
        )
    db.commit()
    return result
