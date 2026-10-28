"""contacts_archive_columns_backfill

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27 21:25:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE contacts
            ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS archived_by BIGINT,
            ADD COLUMN IF NOT EXISTS archive_reason TEXT;

        CREATE INDEX IF NOT EXISTS idx_contacts_archived
            ON contacts (company_id, archived, last_message_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_contacts_archived;

        ALTER TABLE contacts
            DROP COLUMN IF EXISTS archive_reason,
            DROP COLUMN IF EXISTS archived_by,
            DROP COLUMN IF EXISTS archived_at,
            DROP COLUMN IF EXISTS archived;
        """
    )

