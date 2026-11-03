"""Fundacao do modulo de prontuario e jornada do paciente."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def _uuid():
    return sa.String(length=36)


def _common():
    return [
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("clinic_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("clinic_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cpf", sa.String(11)),
        sa.Column("birth_date", sa.Date()),
        sa.Column("phone", sa.String(30)),
        sa.Column("email", sa.String(255)),
        sa.Column("insurance", sa.String(160)),
        sa.Column("source", sa.String(80)),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="SET NULL")),
        sa.Column("lifecycle_status", sa.String(30), server_default=sa.text("'lead'"), nullable=False),
        sa.Column("lgpd_consent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("lgpd_consent_version", sa.String(40)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_patients_clinic_name", "patients", ["clinic_id", "name"])
    op.create_index("idx_patients_clinic_phone", "patients", ["clinic_id", "phone"])
    op.create_index("idx_patients_clinic_lifecycle", "patients", ["clinic_id", "lifecycle_status"])
    op.create_index("uq_patients_clinic_cpf", "patients", ["clinic_id", "cpf"], unique=True, postgresql_where=sa.text("cpf IS NOT NULL"))

    op.create_table(
        "treatments",
        *_common()[:2],
        sa.Column("patient_id", _uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professionals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), server_default=sa.text("'proposed'"), nullable=False),
        sa.Column("total_value", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("start_date", sa.Date()),
        sa.Column("expected_end_date", sa.Date()),
        *_common()[2:],
    )
    op.create_index("idx_treatments_clinic_patient_status", "treatments", ["clinic_id", "patient_id", "status"])
    op.create_table(
        "treatment_procedures",
        *_common()[:2],
        sa.Column("treatment_id", _uuid(), sa.ForeignKey("treatments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tooth_region", sa.String(120)),
        sa.Column("value", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("recurrence_frequency", sa.String(20)),
        sa.Column("recurrence_interval", sa.Integer()),
        sa.Column("recurrence_sessions", sa.Integer()),
        sa.Column("recurrence_end_date", sa.Date()),
        *_common()[2:],
    )
    op.create_index("idx_treatment_procedures_clinic_treatment", "treatment_procedures", ["clinic_id", "treatment_id"])

    op.create_table(
        "patient_appointments",
        *_common()[:2],
        sa.Column("patient_id", _uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professionals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("treatment_procedure_id", _uuid(), sa.ForeignKey("treatment_procedures.id", ondelete="SET NULL")),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), server_default=sa.text("'scheduled'"), nullable=False),
        sa.Column("cancellation_reason", sa.Text()),
        *_common()[2:],
    )
    op.create_index("idx_patient_appointments_clinic_start", "patient_appointments", ["clinic_id", "starts_at"])
    op.create_index("idx_patient_appointments_clinic_status", "patient_appointments", ["clinic_id", "status"])

    op.create_table(
        "clinical_notes",
        *_common()[:2],
        sa.Column("appointment_id", _uuid(), sa.ForeignKey("patient_appointments.id", ondelete="CASCADE")),
        sa.Column("patient_id", _uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("procedures", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("guidance", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("signed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("signature_hash", sa.String(128)),
        *_common()[2:],
    )
    op.create_index("idx_clinical_notes_clinic_patient", "clinical_notes", ["clinic_id", "patient_id", "created_at"])
    op.create_table(
        "clinical_note_addenda",
        *_common()[:2],
        sa.Column("note_id", _uuid(), sa.ForeignKey("clinical_notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("note_id", "version", name="uq_clinical_note_addenda_version"),
    )
    op.create_table(
        "clinical_attachments",
        *_common()[:2],
        sa.Column("note_id", _uuid(), sa.ForeignKey("clinical_notes.id", ondelete="CASCADE")),
        sa.Column("patient_id", _uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_clinical_attachments_clinic_patient", "clinical_attachments", ["clinic_id", "patient_id", "created_at"])

    op.create_table(
        "satisfaction_surveys",
        *_common()[:2],
        sa.Column("appointment_id", _uuid(), sa.ForeignKey("patient_appointments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", _uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professionals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("nps_score", sa.Integer()),
        sa.Column("procedure_score", sa.Integer()),
        sa.Column("comment", sa.Text()),
        sa.Column("channel", sa.String(30), server_default=sa.text("'whatsapp'"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'sent'"), nullable=False),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("responded_at", sa.TIMESTAMP(timezone=True)),
        *_common()[2:],
        sa.UniqueConstraint("appointment_id", name="uq_satisfaction_surveys_appointment"),
        sa.CheckConstraint("nps_score IS NULL OR nps_score BETWEEN 0 AND 10", name="ck_satisfaction_nps"),
        sa.CheckConstraint("procedure_score IS NULL OR procedure_score BETWEEN 1 AND 5", name="ck_satisfaction_procedure"),
    )
    op.create_table(
        "patient_timeline_events",
        *_common()[:2],
        sa.Column("patient_id", _uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_patient_timeline_clinic_patient", "patient_timeline_events", ["clinic_id", "patient_id", "occurred_at"])
    op.create_table(
        "patient_record_module_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("clinic_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("noshow_minutes", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("recurrence_window_days", sa.Integer(), server_default=sa.text("90"), nullable=False),
        sa.Column("survey_delay_hours", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("survey_expiration_hours", sa.Integer(), server_default=sa.text("72"), nullable=False),
        sa.Column("inactive_months", sa.Integer(), server_default=sa.text("6"), nullable=False),
        sa.Column("google_review_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_signed_clinical_note_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.signed_at IS NOT NULL THEN
            RAISE EXCEPTION 'clinical note is immutable after signing';
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER clinical_notes_immutable_after_signing
        BEFORE UPDATE OR DELETE ON clinical_notes
        FOR EACH ROW EXECUTE FUNCTION prevent_signed_clinical_note_mutation();
        """
    )

    for table in (
        "patients", "treatments", "treatment_procedures", "patient_appointments",
        "clinical_notes", "clinical_note_addenda", "clinical_attachments",
        "satisfaction_surveys", "patient_timeline_events", "patient_record_module_settings",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_clinic_isolation ON {table}
            USING (clinic_id = current_setting('app.clinic_id', true)::bigint)
            WITH CHECK (clinic_id = current_setting('app.clinic_id', true)::bigint)
            """
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS clinical_notes_immutable_after_signing ON clinical_notes")
    op.execute("DROP FUNCTION IF EXISTS prevent_signed_clinical_note_mutation()")
    for table in (
        "patient_record_module_settings", "patient_timeline_events", "satisfaction_surveys",
        "clinical_attachments", "clinical_note_addenda", "clinical_notes",
        "patient_appointments", "treatment_procedures", "treatments", "patients",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_clinic_isolation ON {table}")
        op.drop_table(table)
