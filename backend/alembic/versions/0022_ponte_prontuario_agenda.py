"""ponte prontuário <-> agenda: coluna agendamento_id em patient_appointments

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patient_appointments",
        sa.Column("agendamento_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_patient_appointments_agendamento",
        "patient_appointments",
        "agendamentos",
        ["agendamento_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_patient_appointments_agendamento",
        "patient_appointments",
        ["clinic_id", "agendamento_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_patient_appointments_agendamento", table_name="patient_appointments")
    op.drop_constraint(
        "fk_patient_appointments_agendamento", "patient_appointments", type_="foreignkey"
    )
    op.drop_column("patient_appointments", "agendamento_id")
