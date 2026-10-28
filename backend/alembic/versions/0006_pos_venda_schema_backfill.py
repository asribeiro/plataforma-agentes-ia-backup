"""pos_venda_schema_backfill

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27 21:15:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_venda_sequences (
            id BIGSERIAL PRIMARY KEY,
            company_id BIGINT NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_venda_sequences_company_unique
            ON pos_venda_sequences (company_id);

        CREATE TABLE IF NOT EXISTS pos_venda_steps (
            id BIGSERIAL PRIMARY KEY,
            pos_venda_sequence_id BIGINT NOT NULL,
            step_number INTEGER NOT NULL,
            send_after INTEGER NOT NULL DEFAULT 0,
            send_after_unit VARCHAR(20) NOT NULL DEFAULT 'minutes',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_pos_venda_steps_sequence_step UNIQUE (pos_venda_sequence_id, step_number)
        );

        CREATE INDEX IF NOT EXISTS idx_pos_venda_steps_sequence
            ON pos_venda_steps (pos_venda_sequence_id);

        CREATE TABLE IF NOT EXISTS pos_venda_messages (
            id BIGSERIAL PRIMARY KEY,
            pos_venda_step_id BIGINT NOT NULL,
            type VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_pos_venda_messages_step
            ON pos_venda_messages (pos_venda_step_id);

        CREATE TABLE IF NOT EXISTS pos_venda_schedule_configs (
            id BIGSERIAL PRIMARY KEY,
            company_id BIGINT NOT NULL,
            pos_venda_sequence_id BIGINT NOT NULL,
            schedule_data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_pos_venda_schedule_company_sequence UNIQUE (company_id, pos_venda_sequence_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS pos_venda_schedule_configs;
        DROP TABLE IF EXISTS pos_venda_messages;
        DROP TABLE IF EXISTS pos_venda_steps;
        DROP TABLE IF EXISTS pos_venda_sequences;
        """
    )

