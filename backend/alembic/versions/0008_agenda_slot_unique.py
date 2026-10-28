"""Agenda unica por profissional: impede dois agendamentos no mesmo horario

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28

Problema: a unica trava era UNIQUE (client_id, lead_id, consulta_data), que e
por lead. Dois leads diferentes podiam ser marcados na mesma agenda, no mesmo
horario, sem ninguem reclamar.

Solucao: indice unico parcial em (company_id, agenda_id, consulta_data).
- agenda_id entra porque a agenda e por profissional: cada profissional tem a
  sua, e dois profissionais podem atender no mesmo horario.
- E um indice parcial (WHERE status NOT LIKE 'CANCELLED%') porque horario
  cancelado precisa voltar a ficar livre.
- agenda_id IS NOT NULL porque registros antigos sem agenda nao devem colidir
  entre si (varios NULLs sao distintos, mas o filtro deixa a intencao explicita).

Estado verificado antes de aplicar: tabela agendamentos vazia (0 linhas), sem
duplicatas. A migracao e segura.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

NOME_INDICE = "uq_agendamento_agenda_slot"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {NOME_INDICE}
        ON agendamentos (company_id, agenda_id, consulta_data)
        WHERE status NOT LIKE 'CANCELLED%'
          AND agenda_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {NOME_INDICE}")
