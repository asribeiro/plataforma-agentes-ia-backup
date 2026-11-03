"""RLS de verdade: papel de banco para a aplicação (sem superuser, sem bypassrls).

Hoje o app usa um papel SUPERUSER/BYPASSRLS, então as policies das 11 tabelas clínicas existem mas não
são aplicadas a ele. Esta migration cria o papel `plataforma_app` (comum) e concede o que ele precisa
para operar. A senha NÃO fica aqui: é definida por script operacional (`ALTER ROLE ... PASSWORD`), porque
migration é versionada no git.

Depois desta migration, a troca de `DATABASE_URL` (app → plataforma_app) e `ALEMBIC_DATABASE_URL`
(migrações → owner) é feita no env do servidor.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-03
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

PAPEL = "plataforma_app"
DONO = "plataforma_agentes"


def upgrade() -> None:
    # papel comum: sem superuser, sem bypassrls, sem criacao de banco/papel
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL}') THEN
            CREATE ROLE {PAPEL} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
              NOINHERIT NOBYPASSRLS NOREPLICATION;
          END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PAPEL}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {PAPEL}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {PAPEL}")
    # tabelas/sequences que nascerem depois já entram concedidas
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {DONO} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {PAPEL}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {DONO} IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {PAPEL}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {DONO} IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {PAPEL}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {DONO} IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {PAPEL}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {PAPEL}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {PAPEL}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {PAPEL}")
    # Nada de DROP ROLE aqui: papel é objeto de CLUSTER, não do banco. Com a 0025 já aplicada em
    # produção, o papel tem dependências em outro banco e o DROP falharia dentro de um dry-run —
    # foi o que aconteceu em 03/11. Remover o papel é ação operacional, fora da migration.
    op.execute(f"ALTER ROLE {PAPEL} NOLOGIN")
