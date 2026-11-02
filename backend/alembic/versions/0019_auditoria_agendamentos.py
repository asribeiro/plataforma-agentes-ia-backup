"""auditoria de agendamentos (quem alterou/apagou)

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agendamentos_auditoria",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agendamento_id", sa.Integer(), nullable=True),
        sa.Column("operacao", sa.String(length=10), nullable=False),
        sa.Column("dados", sa.JSON(), nullable=True),
        sa.Column("usuario", sa.String(length=120), nullable=True),
        sa.Column("quando", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_agendamentos_auditoria_agendamento_id",
        "agendamentos_auditoria",
        ["agendamento_id"],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_agendamentos_auditoria() RETURNS trigger AS $$
        BEGIN
            IF (TG_OP = 'DELETE') THEN
                INSERT INTO agendamentos_auditoria (agendamento_id, operacao, dados, usuario)
                VALUES (OLD.id, 'DELETE', to_jsonb(OLD), current_user);
                RETURN OLD;
            ELSIF (TG_OP = 'UPDATE') THEN
                INSERT INTO agendamentos_auditoria (agendamento_id, operacao, dados, usuario)
                VALUES (NEW.id, 'UPDATE', jsonb_build_object('antes', to_jsonb(OLD), 'depois', to_jsonb(NEW)), current_user);
                RETURN NEW;
            ELSE
                INSERT INTO agendamentos_auditoria (agendamento_id, operacao, dados, usuario)
                VALUES (NEW.id, 'INSERT', to_jsonb(NEW), current_user);
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agendamentos_auditoria
        AFTER INSERT OR UPDATE OR DELETE ON agendamentos
        FOR EACH ROW EXECUTE FUNCTION fn_agendamentos_auditoria();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agendamentos_auditoria ON agendamentos;")
    op.execute("DROP FUNCTION IF EXISTS fn_agendamentos_auditoria();")
    op.drop_index("ix_agendamentos_auditoria_agendamento_id", table_name="agendamentos_auditoria")
    op.drop_table("agendamentos_auditoria")
