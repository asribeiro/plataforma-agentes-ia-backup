"""Migration 0018: uma mensagem do WhatsApp = uma linha (fim da duplicação).

Contexto do defeito (medido em 02/11/2026): o WAHA entrega o mesmo conteúdo em dois eventos
(`message` e `message.any`). Cada evento virou uma task Celery; quando as duas rodaram ao mesmo
tempo, nenhuma viu a linha da outra e as duas inseriram em `messages` — 13 linhas duplicadas em
produção (ids consecutivos, mesmo `zapi_message_id`). Cada duplicata também disparou o agente, o que
gerou resposta repetida ao paciente.

Conserto: primeiro remover as cópias exatas (mantendo a menor id de cada grupo) e depois criar o
índice único parcial em `(company_id, zapi_message_id)`. O worker já trata erro de chave duplicada
(rollback + reler), então a segunda inserção cai no caminho seguro e não aciona o agente.
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

INDICE = "uq_messages_company_zapi"


def upgrade() -> None:
    conexao = op.get_bind()

    # 1) Remove apenas as cópias: para cada (company_id, zapi_message_id) repetido, mantém a menor id.
    apagados = conexao.exec_driver_sql(
        """
        DELETE FROM messages m
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY company_id, zapi_message_id ORDER BY id
            ) AS ordem
            FROM messages
            WHERE zapi_message_id IS NOT NULL AND zapi_message_id <> ''
        ) copia
        WHERE m.id = copia.id AND copia.ordem > 1
        """
    ).rowcount
    print(f"[0018] linhas duplicadas removidas: {apagados}")

    # 2) Impede que a corrida volte a gravar duas linhas para a mesma mensagem.
    conexao.exec_driver_sql(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {INDICE}
        ON messages (company_id, zapi_message_id)
        WHERE zapi_message_id IS NOT NULL AND zapi_message_id <> ''
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(f"DROP INDEX IF EXISTS {INDICE}")
