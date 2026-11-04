"""Sincronização com agenda externa é opcional, por profissional.

A escolha de espelhar a agenda do profissional em Google Agenda (ou outro serviço) passa a ser do admin da
clínica, num campo booleano do cadastro do profissional. Padrão: desligado.

Desligado NÃO tira a agenda do profissional: `agendas` continua com uma linha por profissional
(`validar_agenda_unica_ativa`). O que muda é que nada é consultado nem escrito em calendário externo.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"


def upgrade() -> None:
    op.add_column(
        "professionals",
        sa.Column(
            "sync_external_calendar",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("professionals", "sync_external_calendar")
