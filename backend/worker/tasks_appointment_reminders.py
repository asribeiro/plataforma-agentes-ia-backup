"""Envio do lembrete de consulta AO PACIENTE.

Por que existe: o lembrete de consulta era criado como `ContactTask` e o único caminho de
notificação existente (`tasks_reminders.send_task_reminder`) avisa o USUÁRIO da clínica pelo
WebSocket. O paciente nunca recebia nada. Aqui a tarefa vencida é despachada para
`tasks_scheduled_messages.enviar_mensagem_agendada`, que envia de verdade por WAHA.

Regras (decisão do dono do produto, 31/10/2026):

- o lembrete é enviado SEMPRE ao paciente, inclusive sábado, domingo e feriado — não existe
  filtro de dia útil aqui de propósito;
- o horário do disparo é o `scheduled_for` da tarefa (09:00 no fuso da agenda, 2 dias e 1 dia
  antes da consulta);
- idempotente: `enviar_mensagem_agendada` recusa tarefa que não está `pending`, e a varredura só
  pega o que já venceu;
- janela de recuperação de 12 horas: se o worker ficar fora por algumas horas, o lembrete ainda
  sai no mesmo dia em vez de morrer.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, text

from .celery_app import app
from backend.db import SessionLocal
from backend.models import ContactTask

logger = logging.getLogger("saas_business.lembretes_consulta")

LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
JANELA_DE_RECUPERACAO_HORAS = 12
LIMITE_POR_RODADA = 200


def _texto_do_lembrete(task: ContactTask) -> str:
    """Reconstroi o texto quando a tarefa antiga não tem `message_content`."""
    metadata = task.task_metadata if isinstance(task.task_metadata, dict) else {}
    telefone = getattr(task.contact, "phone", "") if task.contact else ""
    inicio = metadata.get("consulta_iso") or metadata.get("inicio_iso")
    if inicio:
        try:
            momento = datetime.fromisoformat(str(inicio))
            quando = momento.strftime("%d/%m/%Y às %H:%M")
        except ValueError:
            quando = str(inicio)
    else:
        quando = metadata.get("consulta") or "a data combinada"

    nome = "paciente"
    if task.contact and task.contact.name:
        nome = task.contact.name.strip().split(" ")[0]
    return (
        f"Olá, {nome}! Passando para confirmar sua consulta em {quando}. "
        f"Você confirma? Se precisar remarcar, me avise que eu vejo os horários disponíveis."
    )


@app.task(name="backend.worker.tasks_appointment_reminders.enviar_lembretes_vencidos")
def enviar_lembretes_vencidos() -> str:
    """Despacha o envio (WAHA) dos lembretes de consulta que já venceram.

    Roda a cada 5 minutos. Não olha dia da semana nem feriado.
    """
    agora = datetime.now(timezone.utc)
    inicio_da_janela = agora - timedelta(hours=JANELA_DE_RECUPERACAO_HORAS)

    despachados = 0
    sem_conteudo = 0
    with SessionLocal() as db:
        try:
            tarefas = (
                db.query(ContactTask)
                .filter(
                    and_(
                        ContactTask.status == "pending",
                        ContactTask.scheduled_for <= agora,
                        ContactTask.scheduled_for >= inicio_da_janela,
                        text("contact_tasks.task_metadata->>'marcador' LIKE 'lembrete_%'"),
                    )
                )
                .order_by(ContactTask.scheduled_for.asc())
                .limit(LIMITE_POR_RODADA)
                .all()
            )

            if not tarefas:
                logger.info("[Lembretes] nada vencido agora")
                return "0 lembretes vencidos"

            logger.info("[Lembretes] %s lembrete(s) vencido(s) para enviar", len(tarefas))

            from backend.worker.tasks_scheduled_messages import enviar_mensagem_agendada

            for tarefa in tarefas:
                if not tarefa.message_content:
                    tarefa.message_content = _texto_do_lembrete(tarefa)
                    tarefa.message_type = tarefa.message_type or "text"
                    db.commit()
                    sem_conteudo += 1

                # `enviar_mensagem_agendada` valida status, sessão WAHA da empresa e marca o
                # resultado (completed/erro) na própria tarefa.
                enviar_mensagem_agendada.apply_async(
                    args=[tarefa.id], queue="scheduled_messages_queue"
                )
                despachados += 1
                logger.info(
                    "[Lembretes] despachado task=%s contato=%s scheduled_for=%s",
                    tarefa.id,
                    getattr(tarefa.contact, "phone", "?"),
                    tarefa.scheduled_for,
                )

            return (
                f"{despachados} lembrete(s) despachado(s) "
                f"({sem_conteudo} com texto reconstruído)"
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[Lembretes] falha na varredura: %s", exc, exc_info=True)
            raise
