"""Pesquisas de satisfação e painel de jornada."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.integrations.whatsapp_provider import send_nps_poll
from backend.models import (
    ModuleSetting,
    Patient,
    PatientAppointment,
    PatientTimelineEvent,
    SatisfactionSurvey,
)
from backend.services.papel_clinico import configurar_contexto_clinico

router = APIRouter(prefix="/api/satisfaction", tags=["patient-satisfaction"])


class SatisfactionResponse(BaseModel):
    nps_score: int = Field(..., ge=0, le=10)
    procedure_score: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=5_000)


class SatisfactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    sent_at: Optional[datetime]
    responded_at: Optional[datetime]
    nps_score: Optional[int]
    procedure_score: Optional[int]
    comment: Optional[str]
    patient_id: Optional[str] = None
    appointment_id: Optional[str] = None


class SatisfactionDashboard(BaseModel):
    total_surveys: int
    answered_surveys: int
    nps: Optional[float]
    average_procedure_score: Optional[float]
    no_show_rate: float
    inactive_patients: int
    pending_treatment_sessions: int
    recent_negative_comments: list[dict]


def _settings(db: Session, clinic_id: int):
    return db.query(ModuleSetting).filter(ModuleSetting.clinic_id == clinic_id).first() or ModuleSetting(
        clinic_id=clinic_id,
        noshow_minutes=30,
        recurrence_window_days=90,
        survey_delay_hours=2,
        survey_expiration_hours=72,
        inactive_months=6,
        google_review_enabled=False,
    )


@router.get("", response_model=list[SatisfactionOut])
def list_satisfaction_surveys(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    query = db.query(SatisfactionSurvey).filter(SatisfactionSurvey.clinic_id == clinic_id)
    if status_filter:
        query = query.filter(SatisfactionSurvey.status == status_filter)
    return query.order_by(SatisfactionSurvey.created_at.desc()).limit(200).all()


@router.post("/appointments/{appointment_id}/send", response_model=SatisfactionOut, status_code=201)
def send_satisfaction(
    appointment_id: str,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    appointment = db.query(PatientAppointment).filter(
        PatientAppointment.id == appointment_id,
        PatientAppointment.clinic_id == clinic_id,
        PatientAppointment.status == "attended",
    ).first()
    if appointment is None:
        raise HTTPException(status_code=404, detail="Atendimento concluído não encontrado")
    patient = db.query(Patient).filter(
        Patient.id == appointment.patient_id,
        Patient.clinic_id == clinic_id,
    ).first()
    if patient is None or not patient.phone:
        raise HTTPException(status_code=422, detail="Paciente não possui telefone para WhatsApp")
    existing = db.query(SatisfactionSurvey).filter(
        SatisfactionSurvey.appointment_id == appointment.id,
        SatisfactionSurvey.clinic_id == clinic_id,
    ).first()
    if existing is not None:
        return existing
    send_nps_poll(
        company_id=clinic_id,
        data={
            "phone": patient.phone,
            "question": "De 0 a 10, como você avalia seu atendimento?",
            "scale_type": "nps",
            "campaign_name": "patient_record_satisfaction",
        },
        db=db,
    )
    survey = SatisfactionSurvey(
        clinic_id=clinic_id,
        appointment_id=appointment.id,
        patient_id=patient.id,
        professional_id=appointment.professional_id,
        channel="whatsapp",
        status="sent",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(survey)
    db.commit()
    db.refresh(survey)
    return survey


@router.post("/{survey_id}/respond", response_model=SatisfactionOut)
def respond_satisfaction(
    survey_id: str,
    payload: SatisfactionResponse,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    survey = db.query(SatisfactionSurvey).filter(
        SatisfactionSurvey.id == survey_id,
        SatisfactionSurvey.clinic_id == clinic_id,
    ).first()
    if survey is None:
        raise HTTPException(status_code=404, detail="Pesquisa não encontrada")
    settings = _settings(db, clinic_id)
    if survey.sent_at and datetime.now(timezone.utc) > survey.sent_at + timedelta(hours=settings.survey_expiration_hours):
        survey.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Pesquisa expirada")
    if survey.status == "responded":
        raise HTTPException(status_code=409, detail="Pesquisa já respondida")
    survey.nps_score = payload.nps_score
    survey.procedure_score = payload.procedure_score
    survey.comment = payload.comment
    survey.responded_at = datetime.now(timezone.utc)
    survey.status = "responded"
    if payload.nps_score <= 6:
        db.add(
            PatientTimelineEvent(
                clinic_id=clinic_id,
                patient_id=survey.patient_id,
                event_type="negative_satisfaction_followup_required",
                payload={"survey_id": survey.id, "nps_score": payload.nps_score},
            )
        )
    elif payload.nps_score >= 9 and settings.google_review_enabled:
        db.add(
            PatientTimelineEvent(
                clinic_id=clinic_id,
                patient_id=survey.patient_id,
                event_type="google_review_invite_eligible",
                payload={"survey_id": survey.id},
            )
        )
    db.commit()
    db.refresh(survey)
    return survey


@router.get("/dashboard", response_model=SatisfactionDashboard)
def satisfaction_dashboard(
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    surveys = db.query(SatisfactionSurvey).filter(
        SatisfactionSurvey.clinic_id == clinic_id
    ).all()
    answered = [survey for survey in surveys if survey.status == "responded" and survey.nps_score is not None]
    promoters = sum(survey.nps_score >= 9 for survey in answered)
    detractors = sum(survey.nps_score <= 6 for survey in answered)
    appointments = db.query(PatientAppointment).filter(
        PatientAppointment.clinic_id == clinic_id
    ).all()
    completed = [item for item in appointments if item.status in {"attended", "no_show"}]
    no_shows = sum(item.status == "no_show" for item in completed)
    inactive_patients = db.query(func.count(Patient.id)).filter(
        Patient.clinic_id == clinic_id,
        Patient.lifecycle_status == "inactive",
    ).scalar() or 0
    pending_sessions = db.query(func.count(PatientAppointment.id)).filter(
        PatientAppointment.clinic_id == clinic_id,
        PatientAppointment.status.in_(("scheduled", "pending_confirmation")),
    ).scalar() or 0
    return SatisfactionDashboard(
        total_surveys=len(surveys),
        answered_surveys=len(answered),
        nps=round((promoters - detractors) * 100 / len(answered), 2) if answered else None,
        average_procedure_score=round(
            sum(survey.procedure_score for survey in answered) / len(answered), 2
        ) if answered else None,
        no_show_rate=round(no_shows * 100 / len(completed), 2) if completed else 0,
        inactive_patients=int(inactive_patients),
        pending_treatment_sessions=int(pending_sessions),
        recent_negative_comments=[
            {"survey_id": survey.id, "comment": survey.comment, "nps_score": survey.nps_score}
            for survey in sorted(
                (item for item in answered if item.nps_score <= 6 and item.comment),
                key=lambda item: item.responded_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )[:10]
        ],
    )
