"""contacts_whatsapp_fields_backfill

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27 20:20:00

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE contacts
            ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS source_id VARCHAR(255),
            ADD COLUMN IF NOT EXISTS thumbnail_url TEXT,
            ADD COLUMN IF NOT EXISTS sender_lid VARCHAR(255),
            ADD COLUMN IF NOT EXISTS unread_count INTEGER NOT NULL DEFAULT 0;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE contacts
            DROP COLUMN IF EXISTS unread_count,
            DROP COLUMN IF EXISTS sender_lid,
            DROP COLUMN IF EXISTS thumbnail_url,
            DROP COLUMN IF EXISTS source_id,
            DROP COLUMN IF EXISTS last_message_at;
        """
    )

