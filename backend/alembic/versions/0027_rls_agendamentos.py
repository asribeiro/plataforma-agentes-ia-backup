"""RLS na agenda operacional (`agendamentos`) — ENSAIO, com downgrade imediato disponível.

Última tabela de dado de paciente sem isolamento por clínica. A coluna aqui é `company_id` (não
`clinic_id`). A expressão usa NULLIF para que a ausência de contexto negue a linha em vez de estourar
(`''::bigint` levanta erro — ver migration 0026).

Antes de ligar, os caminhos que tocam a tabela foram instrumentados: rotas de agenda, tools do agente
(`AgentExecutionManager`), task do WhatsApp, tasks periódicas (lembretes, verificação, disponibilidade,
no-show) e confirmação de presença (com fallback para tarefas antigas na fila).

Rollback: `alembic downgrade 0026` (desliga o RLS e remove a policy) — sem restart de container.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-03
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

POLICY = "agendamentos_clinic_isolation"
EXPRESSAO = "company_id = NULLIF(current_setting('app.clinic_id', true), '')::bigint"


def upgrade() -> None:
    op.execute("ALTER TABLE agendamentos ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON agendamentos USING ({EXPRESSAO}) WITH CHECK ({EXPRESSAO})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON agendamentos")
    op.execute("ALTER TABLE agendamentos DISABLE ROW LEVEL SECURITY")
