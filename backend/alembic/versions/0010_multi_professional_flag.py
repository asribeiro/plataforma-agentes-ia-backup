"""flag de multiplos profissionais por clinica

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28

Requisito do Anderson: cada clinica escolhe se atende com um ou varios
profissionais. A opcao de consultar a agenda de um profissional especifico
so existe quando a flag esta ligada.

Default FALSE: clinica que ja existe nasce monoprofissional, que e o caso
mais comum e o fluxo mais simples.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "multi_professional_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "multi_professional_enabled")
