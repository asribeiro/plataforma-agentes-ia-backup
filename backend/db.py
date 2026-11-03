import os
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.pool import Pool
from typing import Generator

# SQLite used in tests and local development cannot compile PostgreSQL's JSONB
# type natively. Map it to JSON so table creation and validation pass while
# keeping the real PostgreSQL schema unchanged in production.
if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"

# URL de conexão (obrigatório usar variável de ambiente)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required!")

# Parâmetros de pool — todos lidos do ambiente, com defaults
POOL_SIZE        = int(os.getenv("DB_POOL_SIZE", "50"))
MAX_OVERFLOW     = int(os.getenv("DB_MAX_OVERFLOW", "50"))
POOL_TIMEOUT     = int(os.getenv("DB_POOL_TIMEOUT", "30"))   # segundos
POOL_RECYCLE     = int(os.getenv("DB_POOL_RECYCLE", "1800")) # segundos
WEB_TRANSACTION_LOCK_TIMEOUT_MS = max(
    50,
    min(5000, int(os.getenv("DB_WEB_LOCK_TIMEOUT_MS", "1000"))),
)
WEB_REQUEST_SESSION_INFO_KEY = "agentive_web_request"
TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY = "agentive_transaction_lock_timeout_ms"
TRANSACTION_LOCK_TIMEOUT_MIN_MS = 50
TRANSACTION_LOCK_TIMEOUT_MAX_MS = 60_000

# Configuração condicional de connect_args
connect_args = {}
if "postgresql" in DATABASE_URL:
    connect_args = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
elif "sqlite" in DATABASE_URL:
    connect_args = {
        "check_same_thread": False
    }

engine_options = {
    "pool_pre_ping": True,
    "connect_args": connect_args,
}
if "sqlite" not in DATABASE_URL:
    engine_options.update(
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT,
        pool_recycle=POOL_RECYCLE,
    )

engine = create_engine(DATABASE_URL, **engine_options)

logger = logging.getLogger(__name__)


def _pool_metric(name: str):
    value = getattr(engine.pool, name, 0)
    return value() if callable(value) else value


# Event listeners para monitorar conexões
@event.listens_for(Pool, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Evento disparado quando uma nova conexão é criada"""
    logger.debug(
        "Nova conexão criada. Pool size: %s, checked out: %s",
        _pool_metric("size"),
        _pool_metric("checkedout"),
    )

@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """Evento disparado quando uma conexão é retirada do pool"""
    checked_out = _pool_metric("checkedout")
    pool_size = _pool_metric("size")
    logger.debug(f"Conexão retirada do pool. Pool: {pool_size}, checked out: {checked_out}")

    # Alerta se estivermos próximo do limite
    total_capacity = POOL_SIZE + MAX_OVERFLOW
    if checked_out > total_capacity * 0.8:  # 80% do pool total
        logger.warning(f"Pool de conexões sob pressão! {checked_out}/{total_capacity} conexões em uso")

@event.listens_for(Pool, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """Evento disparado quando uma conexão é devolvida ao pool"""
    logger.debug(
        "Conexão devolvida ao pool. Pool size: %s, checked out: %s",
        _pool_metric("size"),
        _pool_metric("checkedout"),
    )

def get_connection_stats():
    """Retorna estatísticas do pool de conexões"""
    return {
        "pool_size": _pool_metric("size"),
        "checked_out": _pool_metric("checkedout"),
        "overflow": _pool_metric("overflow"),
        "checked_in": _pool_metric("checkedin"),
        "max_overflow": MAX_OVERFLOW,
        "total_capacity": POOL_SIZE + MAX_OVERFLOW
    }


def check_database_connection() -> None:
    """Executa uma consulta real para validar que o banco responde."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)
Base = declarative_base()


def mark_session_as_web_request(db: Session) -> Session:
    """Mark a request-owned session so every PostgreSQL transaction is fused."""
    db.info[WEB_REQUEST_SESSION_INFO_KEY] = True
    return db


def mark_session_with_transaction_lock_timeout(
    db: Session,
    timeout_ms: int,
) -> Session:
    """Apply a bounded lock fuse to every transaction opened by ``db``."""
    db.info[TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY] = max(
        TRANSACTION_LOCK_TIMEOUT_MIN_MS,
        min(int(timeout_ms), TRANSACTION_LOCK_TIMEOUT_MAX_MS),
    )
    return db


def _session_transaction_lock_timeout_ms(session: Session) -> int | None:
    configured = session.info.get(TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY)
    if configured is not None:
        try:
            return max(
                TRANSACTION_LOCK_TIMEOUT_MIN_MS,
                min(int(configured), TRANSACTION_LOCK_TIMEOUT_MAX_MS),
            )
        except (TypeError, ValueError):
            return None
    if session.info.get(WEB_REQUEST_SESSION_INFO_KEY):
        return WEB_TRANSACTION_LOCK_TIMEOUT_MS
    return None


@event.listens_for(Session, "after_begin")
def apply_web_transaction_lock_timeout(
    session: Session,
    transaction,
    connection,
) -> None:
    """Bound explicit and trigger-owned lock waits for HTTP request sessions.

    ``SET LOCAL`` is transaction-scoped, so pooled connections are never
    contaminated and a request that commits then starts another transaction
    receives the fuse again.
    """
    del transaction
    if connection.dialect.name != "postgresql":
        return
    timeout_ms = _session_transaction_lock_timeout_ms(session)
    if timeout_ms is None:
        return
    connection.exec_driver_sql(
        "SET LOCAL lock_timeout = "
        f"'{timeout_ms}ms'"
    )

def get_db() -> Generator:
    """Dependency do FastAPI para obter sessão e fechar ao final."""
    db = mark_session_as_web_request(SessionLocal())
    try:
        yield db
    finally:
        db.close()


def set_clinic_context(db: Session, clinic_id: int) -> None:
    """Define o tenant da transação para as políticas RLS do prontuário.

    O contexto é transacional (`set_config(..., true)`) e nunca fica preso à
    conexão devolvida ao pool. Em SQLite, usado apenas por testes legados,
    mantemos o valor na sessão sem emitir SQL específico do PostgreSQL.
    """
    try:
        normalized_clinic_id = int(clinic_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("clinic_id deve ser um inteiro positivo") from exc
    if normalized_clinic_id <= 0:
        raise ValueError("clinic_id deve ser um inteiro positivo")

    db.info["clinic_id"] = normalized_clinic_id
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.clinic_id', :clinic_id, true)"),
            {"clinic_id": str(normalized_clinic_id)},
        )

@event.listens_for(Session, "after_begin")
def _reaplicar_contexto_clinico(session, transaction, connection):
    """Reaplica o tenant em toda transação nova.

    `set_config('app.clinic_id', ..., true)` vale até o fim da transação — um `commit()` no meio de uma
    rota clínica deixaria a transação seguinte sem tenant e as policies RLS negariam tudo. Aqui o
    contexto guardado em `session.info` volta a ser aplicado em cada transação que abre.
    """
    clinic_id = session.info.get("clinic_id")
    if not clinic_id:
        return
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT set_config('app.clinic_id', :clinic_id, true)"),
        {"clinic_id": str(clinic_id)},
    )

