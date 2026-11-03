"""Registro e assinatura de evoluções clínicas."""

import hashlib
import json
from io import BytesIO
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import (
    ClinicalNote,
    ClinicalNoteAddendum,
    Patient,
    PatientAppointment,
    PatientTimelineEvent,
)
from backend.services.papel_clinico import (
    _papel_do_usuario,
    configurar_contexto_clinico,
)
from xml.sax.saxutils import escape

router = APIRouter(prefix="/api/clinical-records", tags=["clinical-record"])
CLINICAL_ROLES = {"admin", "clinic_admin", "clinical_professional"}


class ClinicalNoteCreate(BaseModel):
    note_text: str = Field(..., min_length=1, max_length=50_000)
    procedures: list[dict] = Field(default_factory=list)
    guidance: list[dict] = Field(default_factory=list)


class ClinicalNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    appointment_id: Optional[str]
    author_id: Optional[int]
    note_text: str
    procedures: list[dict]
    guidance: list[dict]
    signed_at: Optional[datetime]
    signature_hash: Optional[str]


class ClinicalNoteAddendumCreate(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2_000)
    content: str = Field(..., min_length=1, max_length=50_000)


class ClinicalNoteAddendumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    note_id: str
    author_id: Optional[int]
    version: int
    reason: str
    content: str
    created_at: datetime


def _require_clinical_role(usuario):
    if _papel_do_usuario(usuario) not in CLINICAL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu papel não permite acessar conteúdo clínico",
        )


def _get_appointment(db: Session, clinic_id: int, patient_id: str, appointment_id: str):
    appointment = db.query(PatientAppointment).filter(
        PatientAppointment.id == appointment_id,
        PatientAppointment.patient_id == patient_id,
        PatientAppointment.clinic_id == clinic_id,
    ).first()
    if appointment is None:
        raise HTTPException(status_code=404, detail="Atendimento não encontrado")
    return appointment


def _signature_hash(note_id: str, author_id: int, signed_at: datetime, note_text: str) -> str:
    payload = {
        "note_id": note_id,
        "author_id": author_id,
        "signed_at": signed_at.isoformat(),
        "note_text": note_text,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


@router.post(
    "/patients/{patient_id}/appointments/{appointment_id}/notes",
    response_model=ClinicalNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_clinical_note(
    patient_id: str,
    appointment_id: str,
    payload: ClinicalNoteCreate,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
    ).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    appointment = _get_appointment(db, clinic_id, patient_id, appointment_id)
    role = _papel_do_usuario(usuario)
    if role == "clinical_professional" and appointment.professional_id != usuario.professional_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O profissional só pode registrar a evolução do próprio atendimento",
        )
    existing = db.query(ClinicalNote.id).filter(
        ClinicalNote.appointment_id == appointment.id,
        ClinicalNote.clinic_id == clinic_id,
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Este atendimento já possui evolução clínica")
    note = ClinicalNote(
        clinic_id=clinic_id,
        patient_id=patient_id,
        appointment_id=appointment.id,
        author_id=usuario.id,
        note_text=payload.note_text,
        procedures=payload.procedures,
        guidance=payload.guidance,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.post("/notes/{note_id}/sign", response_model=ClinicalNoteOut)
def sign_clinical_note(
    note_id: str,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    note = db.query(ClinicalNote).filter(
        ClinicalNote.id == note_id,
        ClinicalNote.clinic_id == clinic_id,
    ).first()
    if note is None:
        raise HTTPException(status_code=404, detail="Evolução clínica não encontrada")
    if note.signed_at is not None:
        raise HTTPException(status_code=409, detail="A evolução clínica já está assinada")
    role = _papel_do_usuario(usuario)
    if role == "clinical_professional" and note.author_id != usuario.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente o profissional autor pode assinar esta evolução",
        )
    signed_at = datetime.now(timezone.utc)
    note.signed_at = signed_at
    note.signature_hash = _signature_hash(note.id, usuario.id, signed_at, note.note_text)
    db.add(
        PatientTimelineEvent(
            clinic_id=clinic_id,
            patient_id=note.patient_id,
            event_type="clinical_note_signed",
            payload={"note_id": note.id},
            occurred_at=signed_at,
        )
    )
    db.commit()
    db.refresh(note)
    return note


@router.post("/notes/{note_id}/addenda", response_model=ClinicalNoteAddendumOut, status_code=201)
def create_note_addendum(
    note_id: str,
    payload: ClinicalNoteAddendumCreate,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    note = db.query(ClinicalNote).filter(
        ClinicalNote.id == note_id,
        ClinicalNote.clinic_id == clinic_id,
    ).first()
    if note is None:
        raise HTTPException(status_code=404, detail="Evolução clínica não encontrada")
    if note.signed_at is None:
        raise HTTPException(status_code=409, detail="Adendo só pode corrigir nota assinada")
    if _papel_do_usuario(usuario) == "clinical_professional" and note.author_id != usuario.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente o profissional autor pode criar o adendo",
        )
    latest_version = db.query(ClinicalNoteAddendum.version).filter(
        ClinicalNoteAddendum.note_id == note.id,
        ClinicalNoteAddendum.clinic_id == clinic_id,
    ).order_by(ClinicalNoteAddendum.version.desc()).first()
    version = (latest_version[0] if latest_version else 1) + (1 if latest_version else 0)
    addendum = ClinicalNoteAddendum(
        clinic_id=clinic_id,
        note_id=note.id,
        author_id=usuario.id,
        version=version,
        reason=payload.reason,
        content=payload.content,
    )
    db.add(addendum)
    db.add(
        PatientTimelineEvent(
            clinic_id=clinic_id,
            patient_id=note.patient_id,
            event_type="clinical_note_addendum_created",
            payload={"note_id": note.id, "version": version},
        )
    )
    db.commit()
    db.refresh(addendum)
    return addendum


@router.get("/patients/{patient_id}/export")
def export_patient_history(
    patient_id: str,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
    ).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    notes = db.query(ClinicalNote).filter(
        ClinicalNote.patient_id == patient.id,
        ClinicalNote.clinic_id == clinic_id,
    ).order_by(ClinicalNote.created_at.asc()).all()
    addenda = db.query(ClinicalNoteAddendum).filter(
        ClinicalNoteAddendum.clinic_id == clinic_id,
        ClinicalNoteAddendum.note_id.in_([note.id for note in notes] or [""]),
    ).order_by(ClinicalNoteAddendum.created_at.asc()).all()
    addenda_by_note = {}
    for item in addenda:
        addenda_by_note.setdefault(item.note_id, []).append(item)

    buffer = BytesIO()
    styles = getSampleStyleSheet()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    content = [
        Paragraph("Histórico clínico do paciente", styles["Title"]),
        Paragraph(escape(patient.name), styles["Heading2"]),
        Spacer(1, 8),
    ]
    for note in notes:
        signed = note.signed_at.isoformat() if note.signed_at else "não assinada"
        content.extend(
            [
                Paragraph(f"Evolução — assinatura: {escape(signed)}", styles["Heading3"]),
                Paragraph(escape(note.note_text), styles["BodyText"]),
                Spacer(1, 6),
            ]
        )
        for item in addenda_by_note.get(note.id, []):
            content.extend(
                [
                    Paragraph(f"Adendo v{item.version}: {escape(item.reason)}", styles["Heading4"]),
                    Paragraph(escape(item.content), styles["BodyText"]),
                    Spacer(1, 6),
                ]
            )
    document.build(content)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="prontuario-{patient.id}.pdf"'},
    )
