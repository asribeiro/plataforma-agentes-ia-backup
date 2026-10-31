"""Feriados: dia bloqueado para todas as clínicas + liberação por profissional.

Regra (31/10/2026): feriado fecha a agenda de TODOS os profissionais de TODAS as clínicas. Cada
clínica pode liberar profissional por profissional naquele feriado, e só o admin da clínica faz
isso. O cadastro do feriado é do admin da plataforma (o dia é global).

- `feriados`: lista global. `recorrente` marca o que repete todo ano no mesmo dia/mês.
- `feriado_excecoes`: "quem trabalha nesse feriado, nesta clínica". A presença da linha é a
  liberação — não existe coluna booleana para ficar inconsistente.
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015_company_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feriados",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("tipo", sa.String(length=20), server_default=sa.text("'nacional'"), nullable=False),
        sa.Column("uf", sa.String(length=2), nullable=True),
        sa.Column("cidade", sa.String(length=120), nullable=True),
        sa.Column("recorrente", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("origem", sa.String(length=20), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("data", "nome", name="uq_feriados_data_nome"),
        sa.CheckConstraint(
            "tipo IN ('nacional', 'estadual', 'municipal', 'pontual')",
            name="ck_feriados_tipo",
        ),
    )
    op.create_index("ix_feriados_data", "feriados", ["data"])

    op.create_table(
        "feriado_excecoes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "feriado_id",
            sa.Integer(),
            sa.ForeignKey("feriados.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.BigInteger(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "professional_id",
            sa.Integer(),
            sa.ForeignKey("professionals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("feriado_id", "professional_id", name="uq_feriado_excecao_profissional"),
    )
    op.create_index("ix_feriado_excecoes_feriado_id", "feriado_excecoes", ["feriado_id"])
    op.create_index("ix_feriado_excecoes_company_id", "feriado_excecoes", ["company_id"])
    op.create_index("ix_feriado_excecoes_professional_id", "feriado_excecoes", ["professional_id"])


def downgrade() -> None:
    op.drop_index("ix_feriado_excecoes_professional_id", table_name="feriado_excecoes")
    op.drop_index("ix_feriado_excecoes_company_id", table_name="feriado_excecoes")
    op.drop_index("ix_feriado_excecoes_feriado_id", table_name="feriado_excecoes")
    op.drop_table("feriado_excecoes")
    op.drop_index("ix_feriados_data", table_name="feriados")
    op.drop_table("feriados")
