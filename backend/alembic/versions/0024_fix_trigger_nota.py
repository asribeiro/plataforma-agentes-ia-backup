"""Conserta o trigger de imutabilidade da nota clínica: DELETE devolvia NEW (NULL) e não apagava nada.

Achado em 03/11/2026, ao tentar limpar duas notas de teste: `DELETE FROM clinical_notes` respondia
"0 linhas" e as notas continuavam lá. Causa: `prevent_signed_clinical_note_mutation()` é usado num
trigger `BEFORE DELETE OR UPDATE` e sempre termina com `RETURN NEW`. Em DELETE, `NEW` é NULL, e um
trigger BEFORE que devolve NULL cancela a operação **em silêncio** — nem erro, nem exclusão.

Efeito prático: nenhuma nota clínica jamais pode ser apagada, mesmo rascunho não assinado criado por
engano (e sem caminho para atender pedido de exclusão de dados).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-03
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

CORPO_ANTIGO = """
        BEGIN
          IF OLD.signed_at IS NOT NULL THEN
            RAISE EXCEPTION 'clinical note is immutable after signing';
          END IF;
          RETURN NEW;
        END;
"""

CORPO_NOVO = """
        BEGIN
          IF OLD.signed_at IS NOT NULL THEN
            RAISE EXCEPTION 'clinical note is immutable after signing';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
"""


def upgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION prevent_signed_clinical_note_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $function$" + CORPO_NOVO + "$function$;"
    )


def downgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION prevent_signed_clinical_note_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $function$" + CORPO_ANTIGO + "$function$;"
    )
