"""confirmation_posvenda_backfill

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27 21:05:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS confirmation_executions (
            id BIGSERIAL PRIMARY KEY,
            agendamento_id BIGINT NOT NULL,
            company_id BIGINT NOT NULL,
            confirmation_sequence_id BIGINT NOT NULL,
            confirmation_step_id BIGINT NOT NULL,
            step_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
            scheduled_for TIMESTAMPTZ,
            original_consulta_data TIMESTAMPTZ,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_confirmation_execution_step UNIQUE (agendamento_id, confirmation_sequence_id, confirmation_step_id)
        );

        CREATE INDEX IF NOT EXISTS idx_confirmation_exec_due
            ON confirmation_executions (status, scheduled_for);

        CREATE INDEX IF NOT EXISTS idx_confirmation_exec_agendamento
            ON confirmation_executions (company_id, agendamento_id, confirmation_sequence_id);

        CREATE TABLE IF NOT EXISTS pos_venda_executions (
            id BIGSERIAL PRIMARY KEY,
            venda_id BIGINT NOT NULL,
            lead_id BIGINT NOT NULL,
            company_id BIGINT NOT NULL,
            pos_venda_sequence_id BIGINT NOT NULL,
            pos_venda_step_id BIGINT NOT NULL,
            step_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
            scheduled_for TIMESTAMPTZ,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_pos_venda_execution_step UNIQUE (venda_id, pos_venda_sequence_id, pos_venda_step_id)
        );

        CREATE INDEX IF NOT EXISTS idx_pos_venda_exec_due
            ON pos_venda_executions (status, scheduled_for);

        CREATE INDEX IF NOT EXISTS idx_pos_venda_exec_venda
            ON pos_venda_executions (company_id, venda_id, pos_venda_sequence_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS pos_venda_executions;
        DROP TABLE IF EXISTS confirmation_executions;
        """
    )

