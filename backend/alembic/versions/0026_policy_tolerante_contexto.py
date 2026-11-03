"""Policy tolerante a contexto ausente: NULLIF antes do cast (senão a query estoura em vez de negar).

Achado em 03/11/2026, ao ligar o RLS de verdade: a policy era

    clinic_id = current_setting('app.clinic_id', true)::bigint

`current_setting(..., true)` devolve NULL só quando o parâmetro nunca foi tocado na sessão. Depois que a
primeira transação rodou `set_config('app.clinic_id', ..., true)`, o fim da transação devolve o
parâmetro ao estado **vazio** (`''`), não a NULL — e `''::bigint` levanta
`invalid input syntax for type bigint: ""`.

Efeito prático: com pool de conexões, a primeira requisição clínica "suja" a conexão e as seguintes,
quando chegam sem contexto, davam erro 500 em vez de lista vazia. Com a aplicação usando um papel comum
(o RLS passa a valer), isso viraria erro em produção.

Correção: `NULLIF(current_setting('app.clinic_id', true), '')::bigint` — sem contexto a comparação vira
NULL, a linha não é visível (falha fechada) e nada estoura.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-03
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

TABELAS = [
    "patients",
    "treatments",
    "treatment_procedures",
    "patient_appointments",
    "clinical_notes",
    "clinical_note_addenda",
    "clinical_attachments",
    "satisfaction_surveys",
    "patient_timeline_events",
    "patient_record_module_settings",
    "recurrence_conflict_tasks",
]

EXPRESSAO_NOVA = "clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::bigint"
EXPRESSAO_ANTIGA = "clinic_id = current_setting('app.clinic_id', true)::bigint"


def _recriar(tabela: str, expressao: str) -> None:
    politica = f"{tabela}_clinic_isolation"
    op.execute(f"DROP POLICY IF EXISTS {politica} ON {tabela}")
    op.execute(
        f"CREATE POLICY {politica} ON {tabela} "
        f"USING ({expressao}) WITH CHECK ({expressao})"
    )


def upgrade() -> None:
    for tabela in TABELAS:
        _recriar(tabela, EXPRESSAO_NOVA)


def downgrade() -> None:
    for tabela in TABELAS:
        _recriar(tabela, EXPRESSAO_ANTIGA)
