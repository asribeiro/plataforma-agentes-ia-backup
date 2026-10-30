"""Cadastro completo de empresas, rascunhos e auditoria."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_company_registration"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("network_unit_limit", sa.Integer(), server_default=sa.text("30"), nullable=True))
    op.drop_constraint("ck_companies_professional_tier", "companies", type_="check")
    op.create_check_constraint(
        "ck_companies_professional_tier",
        "companies",
        "professional_tier IN ('mono', 'up_to_4', 'up_to_10', 'network')",
    )
    op.add_column("companies", sa.Column("person_type", sa.String(length=2), server_default=sa.text("'PJ'"), nullable=False))
    op.add_column("companies", sa.Column("municipal_registration", sa.String(length=40), nullable=True))
    op.add_column("companies", sa.Column("postal_code", sa.String(length=8), nullable=True))
    op.add_column("companies", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("companies", sa.Column("address_number", sa.String(length=30), nullable=True))
    op.add_column("companies", sa.Column("address_complement", sa.String(length=120), nullable=True))
    op.add_column("companies", sa.Column("province", sa.String(length=120), nullable=True))
    op.add_column("companies", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("companies", sa.Column("state", sa.String(length=2), nullable=True))
    op.add_column("companies", sa.Column("fixed_phone", sa.String(length=30), nullable=True))
    op.add_column("companies", sa.Column("website", sa.String(length=255), nullable=True))
    op.add_column("companies", sa.Column("instagram", sa.String(length=255), nullable=True))
    op.add_column("companies", sa.Column("ai_whatsapp", sa.String(length=30), nullable=True))
    op.add_column("companies", sa.Column("accepts_insurance", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("companies", sa.Column("accepted_insurance", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("companies", sa.Column("business_hours", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("companies", sa.Column("administrative_responsible_name", sa.String(length=255), nullable=True))
    op.add_column("companies", sa.Column("administrative_responsible_email", sa.String(length=255), nullable=True))
    op.add_column("companies", sa.Column("administrative_responsible_phone", sa.String(length=30), nullable=True))
    op.add_column("companies", sa.Column("technical_responsible_professional_id", sa.Integer(), nullable=True))
    op.add_column("companies", sa.Column("technical_responsible_cro", sa.String(length=30), nullable=True))
    op.add_column("companies", sa.Column("technical_responsible_cro_uf", sa.String(length=2), nullable=True))
    op.add_column("companies", sa.Column("billing_email", sa.String(length=255), nullable=True))
    op.add_column("companies", sa.Column("preferred_payment_method", sa.String(length=40), nullable=True))
    op.add_column("companies", sa.Column("billing_interval", sa.String(length=20), server_default=sa.text("'monthly'"), nullable=False))
    op.add_column("companies", sa.Column("is_founder_customer", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("companies", sa.Column("registration_started_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_companies_technical_responsible_professional",
        "companies",
        "professionals",
        ["technical_responsible_professional_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "company_registration_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_by_client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_company_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("status IN ('draft','created','cancelled')", name="ck_company_registration_draft_status"),
    )
    op.create_index("idx_company_registration_drafts_status", "company_registration_drafts", ["status"])

    op.create_table(
        "company_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("before_data", postgresql.JSONB(), nullable=True),
        sa.Column("after_data", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_company_audit_events_company_created", "company_audit_events", ["company_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_company_audit_events_company_created", table_name="company_audit_events")
    op.drop_table("company_audit_events")
    op.drop_index("idx_company_registration_drafts_status", table_name="company_registration_drafts")
    op.drop_table("company_registration_drafts")
    op.drop_constraint("fk_companies_technical_responsible_professional", "companies", type_="foreignkey")
    op.drop_constraint("ck_companies_professional_tier", "companies", type_="check")
    op.create_check_constraint(
        "ck_companies_professional_tier",
        "companies",
        "professional_tier IN ('mono', 'up_to_4', 'up_to_10')",
    )
    op.drop_column("companies", "network_unit_limit")
    for column in (
        "registration_started_at", "is_founder_customer", "billing_interval",
        "preferred_payment_method", "billing_email", "technical_responsible_cro_uf",
        "technical_responsible_cro", "technical_responsible_professional_id",
        "administrative_responsible_phone", "administrative_responsible_email",
        "administrative_responsible_name", "business_hours", "accepted_insurance",
        "accepts_insurance", "ai_whatsapp", "instagram", "website", "fixed_phone",
        "state", "city", "province", "address_complement", "address_number",
        "address", "postal_code", "municipal_registration", "person_type",
    ):
        op.drop_column("companies", column)
