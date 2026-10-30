"""Credencial Google por agenda e prova do convite (F1-02 / F1-06)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-29

POR QUE ESTA MIGRATION TROCA O DONO DA CREDENCIAL

`calendar_integrations` e por EMPRESA: cabe um Google Calendar por clinica. Com N
profissionais, a pergunta "qual a disponibilidade da Dra. Ana?" nao tem resposta —
as duas agendas caem na mesma credencial e no mesmo `google_calendar_id`. O card
F1-06 decidiu (28/10) OAuth por agenda, opcao A, porque a clinica usa Gmail comum
(delegacao de dominio exigiria Workspace e foi descartada).

A credencial continua podendo viver na empresa (clinica de um profissional so nao
deve ser obrigada a reautorizar). Por isso a leitura e em cascata — agenda
primeiro, empresa como fallback — e nao uma troca de fonte unica.

`patient_email` entra porque hoje NAO existe e-mail de paciente em lugar nenhum
neste banco: `leads` e `contacts` guardam nome e telefone apenas. Sem campo nao ha
convite; o agendamento segue valido e o aviso vai por WhatsApp (decisao de 28/10).

`invite_sent_at` ja existe desde a 0009 — esta migration nao o cria. O que falta
ali e o par: `invite_attendees`, com quem foi realmente convidado, para que
"mandamos o convite" seja verificavel e nao uma promessa no log.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _colunas(tabela: str) -> set:
    inspetor = sa.inspect(op.get_bind())
    return {c["name"] for c in inspetor.get_columns(tabela)}


def upgrade() -> None:
    # ---------------------------------------------------------------- agendas
    existentes = _colunas("agendas")
    novas_agenda = [
        ("google_account_email", sa.String(255)),
        ("google_oauth_token", postgresql.JSON(astext_type=sa.Text())),
        ("google_oauth_scopes", sa.Text()),
    ]
    for nome, tipo in novas_agenda:
        if nome not in existentes:
            op.add_column("agendas", sa.Column(nome, tipo, nullable=True))

    # ------------------------------------------------------------ agendamentos
    existentes = _colunas("agendamentos")
    if "patient_email" not in existentes:
        op.add_column("agendamentos", sa.Column("patient_email", sa.String(255), nullable=True))
    if "invite_attendees" not in existentes:
        op.add_column("agendamentos", sa.Column("invite_attendees", sa.Text(), nullable=True))

    # Indice para achar rapido "quem ja foi convidado" ao reprocessar um dia.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agendamentos_patient_email "
        "ON agendamentos (patient_email)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agendamentos_patient_email")

    existentes = _colunas("agendamentos")
    for nome in ("invite_attendees", "patient_email"):
        if nome in existentes:
            op.drop_column("agendamentos", nome)

    existentes = _colunas("agendas")
    for nome in ("google_oauth_scopes", "google_oauth_token", "google_account_email"):
        if nome in existentes:
            op.drop_column("agendas", nome)
