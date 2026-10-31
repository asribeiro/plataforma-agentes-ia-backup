import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Torna os imports independentes do diretório em que o Alembic é executado.
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Importe todos os registros de modelos antes de expor o metadata. A aplicação
# mantém modelos no Base principal e um pequeno conjunto legado do Agents SDK
# em outro Base; ambos fazem parte do schema público suportado.
from backend.config import DATABASE_URL
from backend.db import Base
import backend.models  # noqa: F401
import backend.prompt.agents_sdk.models.memory_models  # noqa: F401
from backend.agents_sdk.database.models import Base as AgentsSDKBase

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = [Base.metadata, AgentsSDKBase.metadata]

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Configurar URL do banco baseado no ambiente
def get_url():
    # DATABASE_URL é obrigatória fora do modo development e nunca deve conter
    # credenciais versionadas no alembic.ini.
    #
    # ALEMBIC_DATABASE_URL existe para dry-run em banco descartável. Antes deste override o
    # `DATABASE_URL` do backend.config sempre vencia e o "dry-run" rodava no banco de PRODUÇÃO.
    override = os.environ.get("ALEMBIC_DATABASE_URL")
    if override:
        return override
    return DATABASE_URL or config.get_main_option("sqlalchemy.url")


# ---------------------------------------------------------------------------
# P2-09: guarda contra autogenerate destrutivo
#
# O ORM nao cobre todas as tabelas e colunas que existem no banco (webhook_audit,
# follow_up_executions, confirmation_executions, pos_venda_*, contacts.archived,
# entre outras). Sem esta trava, `alembic revision --autogenerate` produz um
# rascunho com dezenas de drop_* que apagaria dados em uso se aplicado.
#
# Com a trava, o autogenerate falha e o humano decide: ou escreve a migration a
# mao, ou primeiro alinha o ORM com o banco.
# ---------------------------------------------------------------------------
_OPERACOES_DESTRUTIVAS = {
    "DropTableOp": "apagar tabela",
    "DropColumnOp": "apagar coluna",
    "DropConstraintOp": "apagar constraint",
    "DropIndexOp": "apagar indice",
}


def recusar_autogenerate_destrutivo(context, revision, directives):
    """Bloqueia o rascunho se ele propuser apagar qualquer coisa."""
    if not directives:
        return
    upgrade = getattr(directives[0], "upgrade_ops", None)
    if upgrade is None:
        return

    encontradas = []
    for op in getattr(upgrade, "ops", []):
        nome = type(op).__name__
        if nome in _OPERACOES_DESTRUTIVAS:
            alvo = getattr(op, "table_name", None) or getattr(op, "index_name", None) or "?"
            encontradas.append(f"  - {_OPERACOES_DESTRUTIVAS[nome]}: {alvo}")

    if encontradas:
        directives[:] = []
        raise RuntimeError(
            "Autogenerate cancelado: o rascunho apagaria objetos que existem no banco.\n"
            + "\n".join(encontradas)
            + "\n\nO ORM esta incompleto em relacao ao banco. Opcoes:\n"
            "  1. Escrever a migration a mao (op.drop_* explicito continua permitido).\n"
            "  2. Alinhar o ORM com o banco antes de gerar a migration.\n"
            "Nenhum arquivo foi criado."
        )


# ---------------------------------------------------------------------------
# Item 2 do Public Release Gate: objetos legados fora do autogenerate.
#
# Estas tabelas e colunas existem no banco e SAO USADAS pelo sistema (webhook_audit
# tem registros reais; follow_up e pos_venda rodam em producao), mas nao estao
# declaradas no ORM. Sem esta lista, o `alembic check` da CI enxerga tudo como
# "removido" e falha, e o autogenerate proporia apagar dados em uso.
#
# Declarar aqui e deliberado: o autogenerate ignora esses objetos, e a decisao
# fica registrada no codigo em vez de a verificacao ser desligada.
#
# Para migrar de verdade no futuro: criar os models correspondentes, rodar
# `alembic check` para confirmar, e entao remover o nome desta lista.
# ---------------------------------------------------------------------------
TABELAS_FORA_DO_AUTOGENERATE = {
    "company_slots",  # tabela de SQL cru, sem model ORM
    "webhook_audit",
    "confirmation_executions",
    "follow_up_executions",
    "noshow_follow_up_executions",
    "pos_venda_steps",
    "pos_venda_messages",
    "pos_venda_sequences",
    "pos_venda_executions",
    "pos_venda_schedule_configs",
}

COLUNAS_FORA_DO_AUTOGENERATE = {
    # integracao WPPConnect descontinuada; colunas ficaram no banco
    ("companies", "wppconnect_base_url"),
    ("companies", "wppconnect_session_name"),
    ("companies", "wppconnect_secret_key"),
    # arquivamento de contatos: gerenciado por SQL direto
    ("contacts", "archived"),
    ("contacts", "archived_at"),
    ("contacts", "archived_by"),
    ("contacts", "archive_reason"),
    ("contacts", "unread_count"),
    ("contacts", "last_message_at"),
    ("contacts", "sender_lid"),
    ("contacts", "source_id"),
    ("contacts", "thumbnail_url"),
}

INDICES_FORA_DO_AUTOGENERATE = {
    "idx_webhook_audit_company_message_type",
    "idx_webhook_audit_created_at",
    "idx_webhook_audit_status_created_at",
    "idx_confirmation_exec_agendamento",
    "idx_confirmation_exec_due",
    "idx_noshow_follow_up_exec_due",
    "idx_noshow_follow_up_exec_lead",
    "idx_follow_up_exec_due",
    "idx_follow_up_exec_lead",
    "idx_pos_venda_messages_step",
    "idx_pos_venda_exec_due",
    "idx_pos_venda_exec_venda",
    "idx_pos_venda_steps_sequence",
    "idx_pos_venda_sequences_company_unique",
    "idx_contacts_archived",
}


def incluir_objeto(object, name, type_, reflected, compare_to):
    """Chamado pelo alembic para decidir se um objeto entra na comparacao."""
    if type_ == "table":
        return name not in TABELAS_FORA_DO_AUTOGENERATE

    if type_ == "column":
        tabela = getattr(getattr(object, "table", None), "name", None)
        if tabela in TABELAS_FORA_DO_AUTOGENERATE:
            return False
        return (tabela, name) not in COLUNAS_FORA_DO_AUTOGENERATE

    if type_ == "index":
        tabela = getattr(getattr(object, "table", None), "name", None)
        if tabela in TABELAS_FORA_DO_AUTOGENERATE:
            return False
        return name not in INDICES_FORA_DO_AUTOGENERATE

    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        include_object=incluir_objeto,
        process_revision_directives=recusar_autogenerate_destrutivo,
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        # PostgreSQL's ``json`` type has no equality operator. Comparing
        # defaults such as ``'[]'::json`` makes ``alembic check`` fail before
        # it can report real schema drift, so defaults are intentionally
        # excluded while types, tables, indexes and constraints are checked.
        compare_server_default=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section)
    if configuration is None:
        raise RuntimeError("Seção [alembic] não encontrada")
    configuration['sqlalchemy.url'] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
        include_object=incluir_objeto,
        process_revision_directives=recusar_autogenerate_destrutivo,
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
