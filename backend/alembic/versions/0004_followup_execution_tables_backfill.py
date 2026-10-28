"""followup_execution_tables_backfill

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27 20:55:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS follow_up_executions (
            id BIGSERIAL PRIMARY KEY,
            lead_id BIGINT NOT NULL,
            company_id BIGINT NOT NULL,
            follow_up_sequence_id BIGINT NOT NULL,
            follow_up_step_id BIGINT NOT NULL,
            step_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
            scheduled_for TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_follow_up_execution_step UNIQUE (lead_id, follow_up_sequence_id, follow_up_step_id)
        );

        CREATE INDEX IF NOT EXISTS idx_follow_up_exec_due
            ON follow_up_executions (status, scheduled_for);

        CREATE INDEX IF NOT EXISTS idx_follow_up_exec_lead
            ON follow_up_executions (company_id, lead_id, follow_up_sequence_id);

        CREATE TABLE IF NOT EXISTS noshow_follow_up_executions (
            id BIGSERIAL PRIMARY KEY,
            lead_id BIGINT NOT NULL,
            company_id BIGINT NOT NULL,
            noshow_follow_up_sequence_id BIGINT NOT NULL,
            noshow_follow_up_step_id BIGINT NOT NULL,
            step_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
            scheduled_for TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_noshow_follow_up_execution_step UNIQUE (lead_id, noshow_follow_up_sequence_id, noshow_follow_up_step_id)
        );

        CREATE INDEX IF NOT EXISTS idx_noshow_follow_up_exec_due
            ON noshow_follow_up_executions (status, scheduled_for);

        CREATE INDEX IF NOT EXISTS idx_noshow_follow_up_exec_lead
            ON noshow_follow_up_executions (company_id, lead_id, noshow_follow_up_sequence_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS noshow_follow_up_executions;
        DROP TABLE IF EXISTS follow_up_executions;
        """
    )

