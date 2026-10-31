"""Migration 0017: confirmacao do paciente no agendamento."""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agendamentos",
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "agendamentos",
        sa.Column(
            "confirmed_via",
            sa.String(length=20),
            nullable=True,
            comment="Canal pelo qual o paciente confirmou (whatsapp, telefone, presencial)",
        ),
    )


def downgrade() -> None:
    op.drop_column("agendamentos", "confirmed_via")
    op.drop_column("agendamentos", "confirmed_at")
