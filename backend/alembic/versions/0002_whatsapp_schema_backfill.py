"""whatsapp_schema_backfill

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27 20:10:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE companies
            ADD COLUMN IF NOT EXISTS wppconnect_session_name VARCHAR(255),
            ADD COLUMN IF NOT EXISTS wppconnect_secret_key VARCHAR(255),
            ADD COLUMN IF NOT EXISTS wppconnect_base_url VARCHAR(255);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_audit (
            id BIGSERIAL PRIMARY KEY,
            instance_id VARCHAR(255) NOT NULL,
            company_id BIGINT NULL REFERENCES companies(id) ON DELETE SET NULL,
            message_id TEXT NOT NULL,
            phone VARCHAR(64) NULL,
            message_type VARCHAR(100) NOT NULL,
            message_data JSONB NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'received',
            task_id VARCHAR(255) NULL,
            error_message TEXT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            processed_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_audit_company_message_type
            ON webhook_audit (company_id, message_id, message_type);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_audit_status_created_at
            ON webhook_audit (status, created_at DESC);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_audit_created_at
            ON webhook_audit (created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_webhook_audit_created_at;")
    op.execute("DROP INDEX IF EXISTS idx_webhook_audit_status_created_at;")
    op.execute("DROP INDEX IF EXISTS idx_webhook_audit_company_message_type;")
    op.execute("DROP TABLE IF EXISTS webhook_audit;")
    op.execute(
        """
        ALTER TABLE companies
            DROP COLUMN IF EXISTS wppconnect_base_url,
            DROP COLUMN IF EXISTS wppconnect_secret_key,
            DROP COLUMN IF EXISTS wppconnect_session_name;
        """
    )

