import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import date, datetime
from backend.db import set_clinic_context

from backend.models import (
    Base,
    ClinicalNote,
    ClinicalNoteAddendum,
    Patient,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(bind=engine)()
    session.execute(text(
        "CREATE TABLE companies (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, cnpj VARCHAR(14) NOT NULL)"
    ))
    session.commit()
    Base.metadata.create_all(
        engine,
        tables=[
            Patient.__table__,
        ],
    )
    session.execute(text(
        """
        CREATE TABLE clinical_notes (
            id VARCHAR(36) PRIMARY KEY,
            clinic_id BIGINT NOT NULL,
            appointment_id VARCHAR(36),
            patient_id VARCHAR(36) NOT NULL,
            author_id INTEGER,
            note_text TEXT NOT NULL,
            procedures TEXT NOT NULL DEFAULT '[]',
            guidance TEXT NOT NULL DEFAULT '[]',
            signed_at TIMESTAMP,
            signature_hash VARCHAR(128),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    ))
    session.execute(text(
        """
        CREATE TABLE clinical_note_addenda (
            id VARCHAR(36) PRIMARY KEY,
            clinic_id BIGINT NOT NULL,
            note_id VARCHAR(36) NOT NULL,
            author_id INTEGER,
            version INTEGER NOT NULL,
            reason TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def test_patient_requires_clinic_and_identity(db):
    patient = Patient(clinic_id=1, name="Paciente ficticio", birth_date=date(1990, 1, 1))
    db.add(patient)
    db.commit()

    assert patient.id is not None
    assert patient.clinic_id == 1


def test_patient_cpf_is_unique_within_clinic(db):
    db.add_all(
        [
            Patient(clinic_id=1, name="Paciente A", cpf="12345678901"),
            Patient(clinic_id=1, name="Paciente B", cpf="12345678901"),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_signed_note_has_addenda_without_mutating_original(db):
    patient = Patient(clinic_id=1, name="Paciente ficticio", birth_date=date(1990, 1, 1))
    db.add(patient)
    db.flush()
    note = ClinicalNote(
        clinic_id=1,
        patient_id=patient.id,
        note_text="Nota original",
        signed_at=datetime(2026, 10, 31, 12, 0),
        signature_hash="hash-ficticio",
    )
    db.add(note)
    db.flush()
    db.add(
        ClinicalNoteAddendum(
            clinic_id=1,
            note_id=note.id,
            version=2,
            reason="Correcao de informacao",
            content="Adendo da nota",
        )
    )
    db.commit()

    db.refresh(note)
    assert note.note_text == "Nota original"
    assert len(note.addenda) == 1


def test_clinic_context_is_required_to_be_positive(db):
    set_clinic_context(db, 7)
    assert db.info["clinic_id"] == 7

    with pytest.raises(ValueError):
        set_clinic_context(db, 0)
