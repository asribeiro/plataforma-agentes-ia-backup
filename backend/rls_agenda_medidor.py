"""Medidor de acesso à tabela `agendamentos` sem contexto de clínica.

Etapa 1 do RLS na agenda: antes de ligar `ENABLE ROW LEVEL SECURITY` em `agendamentos`, precisamos saber
quais caminhos tocam a tabela sem definir `app.clinic_id` — porque com RLS ligado esses caminhos não dão
erro, apenas passam a não ver nada (agente agenda no vazio, lembrete não sai).

Como funciona: listener `before_cursor_execute` no Engine vê o SQL final (sem custo de compilação extra) e
checa um contexto de thread. `set_clinic_context` marca o contexto; `get_db` limpa ao fim da requisição.

Leitura:
  - API: `GET /health/rls-agenda` (header `x-monitoring-token`);
  - worker/beat: primeira ocorrência de cada origem sai no log como `[RLS-Agenda] acesso sem contexto`.
"""
from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_local = threading.local()
_lock = threading.Lock()

_estado = {
    "iniciado_em": datetime.now(timezone.utc).isoformat(),
    "total": 0,
    "com_contexto": 0,
    "sem_contexto": 0,
    "origens_sem_contexto": {},
    "amostras": [],
}
_origens_ja_logadas: set[str] = set()

_IGNORAR = (
    "sqlalchemy",
    "site-packages",
    "/backend/db.py",
    "rls_agenda_medidor",
    "threading.py",
    "contextlib.py",
)


def marcar_contexto(clinic_id) -> None:
    _local.clinic_id = clinic_id


def limpar_contexto() -> None:
    _local.clinic_id = None


def contexto_atual():
    return getattr(_local, "clinic_id", None)


def _origem(limite: int = 80) -> str:
    """Primeiro frame do código da aplicação (fora do SQLAlchemy e do próprio medidor)."""
    pilha = traceback.extract_stack(limit=limite)[:-1]
    for frame in reversed(pilha):
        caminho = f"{frame.filename}:{frame.lineno}"
        if any(ignorado in caminho for ignorado in _IGNORAR):
            continue
        return caminho
    if pilha:
        return f"{pilha[0].filename}:{pilha[0].lineno}"
    return "origem_desconhecida"


@event.listens_for(Engine, "before_cursor_execute")
def _medir_acesso_agenda(conn, cursor, statement, parameters, context, executemany):
    """Conta acessos a `agendamentos` e separa quem tem contexto de clínica de quem não tem."""
    if not statement or "agendamentos" not in statement:
        return
    if contexto_atual() is not None:
        with _lock:
            _estado["total"] += 1
            _estado["com_contexto"] += 1
        return

    origem = _origem()
    resumo_sql = " ".join(statement.split())[:180]
    with _lock:
        _estado["total"] += 1
        _estado["sem_contexto"] += 1
        _estado["origens_sem_contexto"][origem] = (
            _estado["origens_sem_contexto"].get(origem, 0) + 1
        )
        if len(_estado["amostras"]) < 40:
            _estado["amostras"].append({
                "origem": origem,
                "sql": resumo_sql,
                "quando": datetime.now(timezone.utc).isoformat(),
            })
        primeira_vez = origem not in _origens_ja_logadas
        if primeira_vez:
            _origens_ja_logadas.add(origem)

    if primeira_vez:
        logger.warning("[RLS-Agenda] acesso a `agendamentos` SEM contexto de clinica: %s | %s",
                       origem, resumo_sql)


def estatisticas() -> dict:
    with _lock:
        return {
            "iniciado_em": _estado["iniciado_em"],
            "total": _estado["total"],
            "com_contexto": _estado["com_contexto"],
            "sem_contexto": _estado["sem_contexto"],
            "cobertura_percentual": (
                round(100 * _estado["com_contexto"] / _estado["total"], 1)
                if _estado["total"] else None
            ),
            "origens_sem_contexto": dict(sorted(
                _estado["origens_sem_contexto"].items(), key=lambda item: -item[1]
            )),
            "amostras": list(_estado["amostras"]),
        }


def zerar() -> None:
    with _lock:
        _estado["total"] = 0
        _estado["com_contexto"] = 0
        _estado["sem_contexto"] = 0
        _estado["origens_sem_contexto"] = {}
        _estado["amostras"] = []
        _estado["iniciado_em"] = datetime.now(timezone.utc).isoformat()
        _origens_ja_logadas.clear()
