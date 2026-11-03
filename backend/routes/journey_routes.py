"""Ciclo de vida, no-show e reativação de pacientes."""

from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import (
    ModuleSetting,
    Patient,
    PatientAppointment,
    PatientTimelineEvent,
    Treatment,
    TreatmentProcedure,
)
from backend.services.journey_service import (
    calculate_lifecycle_status,
    has_two_consecutive_no_shows,
)
from backend.services.papel_clinico import configurar_contexto_clinico

router = APIRouter(prefix="/api/journey", tags=["patient-journey"])


class NoShowJobResult(BaseModel):
    marked_no_shows: int
    patients_updated: int


class ReactivationPatientOut(BaseModel):
    patient_id: str
    name: str
    last_attended_at: datetime | None
    lifecycle_status: str


def _settings(db: Session, clinic_id: int):
    settings = db.query(ModuleSetting).filter(ModuleSetting.clinic_id == clinic_id).first()
    return settings or ModuleSetting(
        clinic_id=clinic_id,
        noshow_minutes=30,
        inactive_months=6,
        recurrence_window_days=90,
        survey_delay_hours=2,
        survey_expiration_hours=72,
        google_review_enabled=False,
    )


def _recalculate_patient(db: Session, patient: Patient, clinic_id: int, inactive_months: int):
    appointments = db.query(PatientAppointment).filter(
        PatientAppointment.patient_id == patient.id,
        PatientAppointment.clinic_id == clinic_id,
    ).order_by(PatientAppointment.starts_at.asc()).all()
    statuses = [appointment.status for appointment in appointments]
    latest_attended = next(
        (appointment.starts_at for appointment in reversed(appointments) if appointment.status == "attended"),
        None,
    )
    active_treatment = db.query(Treatment.id).filter(
        Treatment.patient_id == patient.id,
        Treatment.clinic_id == clinic_id,
        Treatment.status.in_(("approved", "in_progress")),
    ).first() is not None
    recurring = db.query(TreatmentProcedure.id).join(
        Treatment, Treatment.id == TreatmentProcedure.treatment_id
    ).filter(
        TreatmentProcedure.clinic_id == clinic_id,
        TreatmentProcedure.recurrence_frequency.isnot(None),
        TreatmentProcedure.status == "active",
        Treatment.patient_id == patient.id,
    ).first() is not None
    scheduled = any(
        appointment.status in {"scheduled", "confirmed"} and appointment.starts_at >= datetime.now(timezone.utc)
        for appointment in appointments
    )
    inactive_before = datetime.now(timezone.utc) - relativedelta(months=inactive_months)
    is_inactive = latest_attended is None or latest_attended < inactive_before
    patient.lifecycle_status = calculate_lifecycle_status(
        has_risk=has_two_consecutive_no_shows(statuses),
        has_active_treatment=active_treatment,
        has_recurring_procedure=recurring,
        has_scheduled_appointment=scheduled,
        is_inactive=is_inactive,
        has_lead=patient.lead_id is not None,
    )


@router.post("/process-no-shows", response_model=NoShowJobResult)
def process_no_shows(
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    settings = _settings(db, clinic_id)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.noshow_minutes)
    appointments = db.query(PatientAppointment).filter(
        PatientAppointment.clinic_id == clinic_id,
        PatientAppointment.status.in_(("scheduled", "confirmed")),
        PatientAppointment.starts_at <= cutoff,
    ).all()
    changed_patients = set()
    for appointment in appointments:
        appointment.status = "no_show"
        changed_patients.add(appointment.patient_id)
        db.add(
            PatientTimelineEvent(
                clinic_id=clinic_id,
                patient_id=appointment.patient_id,
                event_type="appointment_no_show",
                payload={"appointment_id": appointment.id},
                occurred_at=datetime.now(timezone.utc),
            )
        )
    for patient_id in changed_patients:
        patient = db.query(Patient).filter(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
        ).first()
        if patient:
            _recalculate_patient(db, patient, clinic_id, settings.inactive_months)
    db.commit()
    return NoShowJobResult(marked_no_shows=len(appointments), patients_updated=len(changed_patients))


@router.get("/reactivation", response_model=list[ReactivationPatientOut])
def list_reactivation(
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    settings = _settings(db, clinic_id)
    cutoff = datetime.now(timezone.utc) - relativedelta(months=settings.inactive_months)
    patients = db.query(Patient).filter(
        Patient.clinic_id == clinic_id,
        Patient.lifecycle_status == "inactive",
    ).all()
    result = []
    for patient in patients:
        latest = db.query(PatientAppointment.starts_at).filter(
            PatientAppointment.patient_id == patient.id,
            PatientAppointment.clinic_id == clinic_id,
            PatientAppointment.status == "attended",
        ).order_by(PatientAppointment.starts_at.desc()).first()
        latest_at = latest[0] if latest else None
        if latest_at is None or latest_at < cutoff:
            result.append(
                ReactivationPatientOut(
                    patient_id=patient.id,
                    name=patient.name,
                    last_attended_at=latest_at,
                    lifecycle_status=patient.lifecycle_status,
                )
            )
    return result
