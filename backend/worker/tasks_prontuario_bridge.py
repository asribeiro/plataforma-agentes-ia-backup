"""Job de 5 min: rede de segurança da ponte prontuário <-> agenda.

A ponte é chamada na criação/cancelamento, mas existem caminhos legados que gravam agendamento por SQL
cru (por exemplo `backend/prompt/db_integration/agendamento_logic.py` e a importação de contatos).
Este job garante que nada fique de fora: varre os agendamentos e sincroniza o que faltar.
"""
import logging

from backend.db import SessionLocal
from backend.services.prontuario_agenda_bridge import sincronizar_pendentes
from backend.worker.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="backend.worker.tasks_prontuario_bridge.sincronizar_agendamentos")
def sincronizar_agendamentos():
    db = SessionLocal()
    try:
        resultado = sincronizar_pendentes(db)
        if resultado["criados"] or resultado["atualizados"] or resultado["cancelados"] or resultado["falhas"]:
            logger.info("[PonteProntuario] job: %s", resultado)
            if resultado["motivos"]:
                logger.warning("[PonteProntuario] job sem sincronizar: %s", resultado["motivos"])
        return resultado
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("[PonteProntuario] job falhou: %s", exc)
        raise
    finally:
        db.close()
