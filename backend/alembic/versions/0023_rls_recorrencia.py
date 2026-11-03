"""RLS em recurrence_conflict_tasks (a única tabela clínica sem isolamento).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-03
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

TABELA = "recurrence_conflict_tasks"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABELA} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABELA}_clinic_isolation ON {TABELA}
        USING (clinic_id = current_setting('app.clinic_id', true)::bigint)
        WITH CHECK (clinic_id = current_setting('app.clinic_id', true)::bigint)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABELA}_clinic_isolation ON {TABELA}")
    op.execute(f"ALTER TABLE {TABELA} DISABLE ROW LEVEL SECURITY")
