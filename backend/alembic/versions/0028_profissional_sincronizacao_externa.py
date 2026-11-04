"""Sincronização com agenda externa é opcional, por profissional.

A escolha de espelhar a agenda do profissional em Google Agenda (ou outro serviço) passa a ser do admin da
clínica, num campo booleano do cadastro do profissional. Padrão para cadastro novo: desligado.

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

    # Backfill: quem já espelha a agenda hoje continua espelhando.
    #
    # Sem isto, o padrão "false" desligaria clínicas em operação no dia do deploy: o agente continuaria
    # agendando (o banco local não depende do Google), mas o evento deixaria de aparecer na agenda que o
    # profissional usa no celular — falha silenciosa, descoberta só quando alguém reclamasse de não ver o
    # compromisso. Só fica ligado quem tem, na agenda, calendário externo apontado ou token OAuth gravado.
    #
    # Cadastro novo nasce desligado: é o que o cliente pediu, porque a maioria das clínicas não tem quem
    # conecte OAuth.
    op.execute(
        """
        UPDATE professionals p
           SET sync_external_calendar = true
         WHERE EXISTS (
               SELECT 1
                 FROM agendas a
                WHERE a.professional_id = p.id
                  AND (a.google_calendar_id IS NOT NULL OR a.google_oauth_token IS NOT NULL)
         )
        """
    )


def downgrade() -> None:
    op.drop_column("professionals", "sync_external_calendar")
