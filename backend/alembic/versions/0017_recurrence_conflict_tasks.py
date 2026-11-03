"""Tarefas pendentes geradas por conflitos de recorrência."""

from alembic import op
import sqlalchemy as sa

revision = "0017_recurrence_conflict_tasks"
down_revision = "0016_prontuario_jornada"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurrence_conflict_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("clinic_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("appointment_id", sa.String(36), sa.ForeignKey("patient_appointments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_recurrence_conflict_tasks_clinic_status",
        "recurrence_conflict_tasks",
        ["clinic_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_recurrence_conflict_tasks_clinic_status", table_name="recurrence_conflict_tasks")
    op.drop_table("recurrence_conflict_tasks")
