"""Anexos clínicos com armazenamento privado local por clínica."""

from pathlib import Path
from typing import Optional
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import ClinicalAttachment, ClinicalNote, Patient, PatientTimelineEvent
from backend.services.papel_clinico import (
    _papel_do_usuario,
    configurar_contexto_clinico,
)

router = APIRouter(prefix="/api/clinical-attachments", tags=["clinical-attachments"])

CLINICAL_ROLES = {"admin", "clinic_admin", "clinical_professional"}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
STORAGE_ROOT = Path(os.getenv("CLINICAL_ATTACHMENTS_DIR", "backend/storage/clinical_attachments")).resolve()


class ClinicalAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    note_id: Optional[str]
    mime_type: str
    size_bytes: int


def _require_clinical_role(usuario):
    if _papel_do_usuario(usuario) not in CLINICAL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu papel não permite acessar anexos clínicos",
        )


def _get_patient(db: Session, clinic_id: int, patient_id: str) -> Patient:
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
    ).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    return patient


def _get_attachment(db: Session, clinic_id: int, attachment_id: str) -> ClinicalAttachment:
    attachment = db.query(ClinicalAttachment).filter(
        ClinicalAttachment.id == attachment_id,
        ClinicalAttachment.clinic_id == clinic_id,
    ).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")
    return attachment


def _extension_for(file: UploadFile) -> str:
    extension = ALLOWED_MIME_TYPES.get(file.content_type or "")
    if not extension:
        raise HTTPException(
            status_code=422,
            detail="Tipo de arquivo não permitido. Use PDF, JPG, PNG ou WebP",
        )
    return extension


@router.get("/patients/{patient_id}", response_model=list[ClinicalAttachmentOut])
def list_patient_attachments(
    patient_id: str,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    _get_patient(db, clinic_id, patient_id)
    return db.query(ClinicalAttachment).filter(
        ClinicalAttachment.clinic_id == clinic_id,
        ClinicalAttachment.patient_id == patient_id,
    ).order_by(ClinicalAttachment.created_at.desc()).all()


@router.post("/patients/{patient_id}", response_model=ClinicalAttachmentOut, status_code=201)
def upload_patient_attachment(
    patient_id: str,
    file: UploadFile = File(...),
    note_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    _get_patient(db, clinic_id, patient_id)
    if note_id:
        note = db.query(ClinicalNote).filter(
            ClinicalNote.id == note_id,
            ClinicalNote.patient_id == patient_id,
            ClinicalNote.clinic_id == clinic_id,
        ).first()
        if note is None:
            raise HTTPException(status_code=404, detail="Evolução clínica não encontrada")
    extension = _extension_for(file)
    content = file.file.read(MAX_ATTACHMENT_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="Arquivo vazio")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo excede o limite de 10 MB")

    attachment_id = str(uuid.uuid4())
    clinic_dir = STORAGE_ROOT / str(clinic_id) / patient_id
    clinic_dir.mkdir(parents=True, exist_ok=True)
    object_key = f"{clinic_id}/{patient_id}/{attachment_id}{extension}"
    destination = STORAGE_ROOT / object_key
    with destination.open("wb") as target:
        target.write(content)

    attachment = ClinicalAttachment(
        id=attachment_id,
        clinic_id=clinic_id,
        patient_id=patient_id,
        note_id=note_id,
        object_key=object_key,
        mime_type=file.content_type,
        size_bytes=len(content),
    )
    db.add(attachment)
    db.add(
        PatientTimelineEvent(
            clinic_id=clinic_id,
            patient_id=patient_id,
            event_type="clinical_attachment_uploaded",
            payload={
                "attachment_id": attachment_id,
                "mime_type": file.content_type,
                "size_bytes": len(content),
                "note_id": note_id,
            },
        )
    )
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{attachment_id}/download")
def download_patient_attachment(
    attachment_id: str,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    clinic_id = configurar_contexto_clinico(db, usuario)
    _require_clinical_role(usuario)
    attachment = _get_attachment(db, clinic_id, attachment_id)
    path = (STORAGE_ROOT / attachment.object_key).resolve()
    if not str(path).startswith(str(STORAGE_ROOT)) or not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no armazenamento")
    db.add(
        PatientTimelineEvent(
            clinic_id=clinic_id,
            patient_id=attachment.patient_id,
            event_type="clinical_attachment_downloaded",
            payload={"attachment_id": attachment.id},
        )
    )
    db.commit()
    return FileResponse(
        path,
        media_type=attachment.mime_type,
        filename=f"{attachment.id}{path.suffix}",
    )
