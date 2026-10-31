"""
Appointment Management Tools - OpenAI Agents SDK compatible tools for appointment management

This module provides LLM-driven tools for cancelling and rescheduling appointments,
integrating with the existing agendamento_logic.py infrastructure for consistent
behavior across Google Calendar, Clinicorp, and Webhook integrations.
"""

import logging
import re
from typing import Annotated, Optional
from pydantic import Field
from sqlalchemy.orm import Session

# Import OpenAI Agents SDK decorator
from agents import function_tool

logger = logging.getLogger(__name__)


@function_tool(strict_mode=False)
def confirm_cancellation(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do cliente (formato: 5500000000009)")],
    reason: Annotated[str, Field(description="Motivo do cancelamento confirmado pelo cliente")] = "",
    appointment_date: Annotated[str, Field(description="Data do agendamento a cancelar, DD/MM/AAAA ou AAAA-MM-DD. Use quando o cliente disser qual agendamento quer cancelar — sem isso a tool pode cancelar o agendamento errado.")] = "",
    appointment_time: Annotated[str, Field(description="Hora do agendamento a cancelar, HH:MM. Opcional, refina a busca quando o cliente tem mais de um horário.")] = "",
) -> str:
    """
    CONFIRMA e executa o cancelamento depois que o cliente confirmar.

    Use somente depois de o cliente confirmar o cancelamento. Informe
    `appointment_date` com a data que ele citou — a tool cancela o agendamento
    daquele dia, nao "o proximo que encontrar".

    O cancelamento marca o agendamento como CANCELLED, remove o evento da agenda
    do profissional e cancela as tarefas de lembrete. Se nao achar o agendamento
    na data informada, devolve isso e voce NAO deve dizer que cancelou.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from backend.agents_sdk.tools.calendar_scheduling_tools import (
        _cancelar_tarefas_de_lembrete,
        _normalize_phone,
    )
    from backend.db import get_db
    from backend.models import Agenda, Agendamento
    from backend.services.google_credencial import build_service_da_agenda

    db = next(get_db())
    try:
        telefone = _normalize_phone(phone) or phone
        consulta = (
            db.query(Agendamento)
            .filter(
                Agendamento.company_id == company_id,
                Agendamento.phone == telefone,
                ~Agendamento.status.ilike("CANCEL%"),
            )
            .order_by(Agendamento.consulta_data)
        )
        candidatos = consulta.all()
        if not candidatos:
            return (
                "Nao encontrei agendamento ativo para esse telefone. Nao diga ao cliente que "
                "cancelou: confirme com ele a data e o horario do agendamento."
            )

        # Fuso: o da agenda do agendamento, com queda para o padrao da clinica.
        def _fuso(alvo):
            try:
                agenda = db.query(Agenda).filter(Agenda.id == alvo.agenda_id).first()
                return ZoneInfo((agenda.timezone if agenda else None) or "America/Sao_Paulo")
            except (ZoneInfoNotFoundError, ValueError):
                return ZoneInfo("America/Sao_Paulo")

        escolhido = None
        dia_pedido = None
        texto_data = str(appointment_date or "").strip()
        if texto_data:
            normalizado = texto_data.replace("/", "-")
            for formato in ("%d-%m-%Y", "%Y-%m-%d"):
                try:
                    dia_pedido = datetime.strptime(normalizado, formato).date()
                    break
                except ValueError:
                    continue

        if dia_pedido is not None:
            do_dia = [
                item
                for item in candidatos
                if item.consulta_data and item.consulta_data.astimezone(_fuso(item)).date() == dia_pedido
            ]
            if not do_dia:
                return (
                    f"Nao encontrei agendamento ativo em {texto_data}. Nao diga ao cliente que "
                    "cancelou: confirme a data com ele."
                )
            escolhido = do_dia[0]
            texto_hora = str(appointment_time or "").strip().replace("h", ":")
            achado = re.search(r"(\d{1,2})\s*:?\s*(\d{2})?", texto_hora)
            if achado:
                hora = int(achado.group(1))
                minuto = int(achado.group(2) or 0)
                proximo = min(
                    do_dia,
                    key=lambda item: abs(
                        (
                            item.consulta_data.astimezone(_fuso(item)).hour * 60
                            + item.consulta_data.astimezone(_fuso(item)).minute
                        )
                        - (hora * 60 + minuto)
                    ),
                )
                escolhido = proximo
        else:
            escolhido = candidatos[0]

        fuso = _fuso(escolhido)
        quando_local = escolhido.consulta_data.astimezone(fuso) if escolhido.consulta_data else None

        # 1) marca CANCELLED — nunca apaga a linha
        escolhido.status = "CANCELLED"
        if reason:
            escolhido.interesse = (escolhido.interesse or "")[:200]
        db.commit()

        # 2) apaga o evento na agenda do profissional
        google_status = "not_applicable"
        if escolhido.event_id:
            agenda = db.query(Agenda).filter(Agenda.id == escolhido.agenda_id).first()
            servico, motivo = build_service_da_agenda(db, company_id, agenda)
            if servico is None:
                google_status = f"failed: credencial indisponivel ({motivo})"
                logger.warning("[ConfirmCancelTool] sem credencial Google para agenda %s", escolhido.agenda_id)
            else:
                try:
                    servico.events().delete(
                        calendarId=escolhido.google_calendar_id or agenda.google_calendar_id,
                        eventId=escolhido.event_id,
                    ).execute()
                    escolhido.event_id = None
                    escolhido.google_sync_status = "CANCELLED"
                    db.commit()
                    google_status = "deleted"
                except Exception as exc:  # noqa: BLE001
                    google_status = f"failed: {type(exc).__name__}"
                    logger.error("[ConfirmCancelTool] falha ao apagar evento no Google: %s", exc)
        else:
            escolhido.google_sync_status = "CANCELLED"
            db.commit()

        # 3) cancela as tarefas de lembrete
        lembretes = _cancelar_tarefas_de_lembrete(db, company_id, escolhido.id)

        logger.info(
            "[ConfirmCancelTool] cancelado agendamento %s (%s) google=%s lembretes=%s",
            escolhido.id, quando_local, google_status, lembretes,
        )
        return (
            f"Agendamento cancelado: {quando_local.strftime('%d/%m/%Y as %H:%M')}"
            if quando_local
            else "Agendamento cancelado."
        ) + (
            f". Evento removido da agenda do profissional ({google_status})."
            f" {lembretes.get('canceladas', 0)} tarefa(s) de lembrete cancelada(s)."
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[ConfirmCancelTool] erro ao cancelar: %s", exc)
        db.rollback()
        return (
            "Nao consegui cancelar agora. Nao diga ao cliente que cancelou: informe que a "
            "equipe vai confirmar o cancelamento."
        )
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


@function_tool(strict_mode=False)
def reschedule_appointment(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do cliente (formato: 5500000000009)")],
    customer_name: Annotated[str, Field(description="Nome completo do cliente")],
    new_date: Annotated[str, Field(description="Nova data no formato DD/MM/AAAA. Pode ser anterior à data atual do agendamento.")],
    new_time: Annotated[str, Field(description="Novo horário no formato HH:MM")],
    treatment_type: Annotated[str, Field(description="Tipo de tratamento")] = "Consulta de Avaliação",
    customer_type: Annotated[str, Field(description="Tipo de cliente: 'novo' ou 'retorno'")] = "novo",
    current_date: Annotated[str, Field(description="Data do agendamento que será movido (DD/MM/AAAA). Informe quando o cliente tiver mais de um agendamento ativo.")] = "",
) -> str:
    """
    Move um agendamento existente para outra data e horário.

    Use quando o cliente pedir para remarcar. A nova data pode ser ANTES da
    data atual — não existe exigência de ser depois. Confirme a nova data e o
    novo horário com o cliente antes de chamar.

    Antes de chamar, consulte os horários disponíveis (`find_available_lead_slots`)
    e ofereça até 3 opções. Esta tool valida o horário, move o evento na agenda do
    profissional e recria as tarefas de lembrete (2 dias e 1 dia antes, às 09:00).
    Se o horário não estiver livre, ela devolve opções próximas no mesmo dia.
    """
    from datetime import datetime, time as _time, timedelta

    from backend.agents_sdk.tools.calendar_scheduling_tools import (
        _build_available_slots,
        _cancelar_tarefas_de_lembrete,
        _criar_tarefas_de_lembrete,
        _normalize_phone,
        _ordenar_por_horario_preferido,
        _parse_hhmm,
        _safe_timezone,
        _validate_slot_availability,
    )
    from backend.db import get_db
    from backend.models import Agenda, Agendamento
    from backend.services.google_credencial import build_service_da_agenda

    def _data(texto: str):
        limpo = str(texto or "").strip().replace("-", "/")
        for formato in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(limpo, formato).date()
            except ValueError:
                continue
        return None

    db = next(get_db())
    try:
        telefone = _normalize_phone(phone) or phone
        candidatos = (
            db.query(Agendamento)
            .filter(
                Agendamento.company_id == company_id,
                Agendamento.phone == telefone,
                ~Agendamento.status.ilike("CANCEL%"),
            )
            .order_by(Agendamento.consulta_data)
            .all()
        )
        if not candidatos:
            return (
                "Nao encontrei agendamento ativo para esse telefone. Nao diga ao cliente que "
                "remarcou: confirme a data do agendamento atual."
            )

        alvo = candidatos[0]
        dia_atual = _data(current_date)
        if dia_atual is not None:
            do_dia = [
                item
                for item in candidatos
                if item.consulta_data
                and item.consulta_data.date() == dia_atual
            ]
            if do_dia:
                alvo = do_dia[0]

        agenda = (
            db.query(Agenda).filter(Agenda.id == alvo.agenda_id).first()
            if alvo.agenda_id
            else db.query(Agenda).filter(Agenda.company_id == company_id, Agenda.active.is_(True)).first()
        )
        if agenda is None:
            return "Nao consegui identificar a agenda desse agendamento. Escale para a equipe."

        tz = _safe_timezone(agenda.timezone)
        nova_data = _data(new_date)
        minutos = _parse_hhmm(new_time)
        if nova_data is None or minutos is None:
            return (
                f"Nao entendi a data/hora do reagendamento ({new_date} {new_time}). "
                "Use DD/MM/AAAA e HH:MM."
            )

        duracao = agenda.slot_duration or 30
        novo_inicio = datetime.combine(
            nova_data, _time(hour=minutos // 60, minute=minutos % 60), tzinfo=tz
        )
        novo_fim = novo_inicio + timedelta(minutes=duracao)

        # Sem comparar com a data antiga: qualquer data futura e valida.
        validacao = _validate_slot_availability(
            db=db,
            agenda=agenda,
            starts_at=novo_inicio,
            ends_at=novo_fim,
            exclude_appointment_id=alvo.id,
        )
        if not validacao.get("success"):
            alternativas = _ordenar_por_horario_preferido(
                _build_available_slots(
                    db=db,
                    agenda=agenda,
                    start_date=nova_data,
                    end_date=nova_data + timedelta(days=7),
                    preferred_period="",
                    limit=30,
                ),
                new_time,
            )[:3]
            lista = " | ".join(item.get("display", "") for item in alternativas)
            return (
                f"{validacao.get('message_for_agent', 'Horario indisponivel.')} "
                + (f"Opcoes proximas: {lista}. Ofereca essas opcoes ao cliente." if alternativas else "")
            )

        # Move o evento na agenda do profissional (mesmo event_id)
        google_status = "sem evento no Google"
        if alvo.event_id:
            servico, motivo = build_service_da_agenda(db, company_id, agenda)
            if servico is None:
                google_status = f"evento nao movido (credencial indisponivel: {motivo})"
            else:
                try:
                    servico.events().patch(
                        calendarId=alvo.google_calendar_id or agenda.google_calendar_id,
                        eventId=alvo.event_id,
                        body={
                            "start": {"dateTime": novo_inicio.isoformat(), "timeZone": agenda.timezone},
                            "end": {"dateTime": novo_fim.isoformat(), "timeZone": agenda.timezone},
                        },
                    ).execute()
                    google_status = "evento movido na agenda"
                except Exception as exc:  # noqa: BLE001
                    google_status = f"falha ao mover evento ({type(exc).__name__})"
                    logger.error("[RescheduleTool] falha ao mover evento: %s", exc)

        # Lembretes antigos morrem; os novos nascem para a data nova
        antigos = _cancelar_tarefas_de_lembrete(db, company_id, alvo.id)

        alvo.consulta_data = novo_inicio
        alvo.status = "SCHEDULED"
        db.commit()
        db.refresh(alvo)

        novos = _criar_tarefas_de_lembrete(
            db=db,
            company_id=company_id,
            appointment=alvo,
            agenda=agenda,
            starts_at=novo_inicio,
            sufixo=novo_inicio.strftime("%Y%m%d%H%M"),
        )

        logger.info(
            "[RescheduleTool] agendamento %s movido para %s | google=%s | lembretes antigos=%s novos=%s",
            alvo.id, novo_inicio.isoformat(), google_status,
            antigos.get("canceladas"), novos.get("criados"),
        )
        return (
            f"Reagendado para {novo_inicio.strftime('%d/%m/%Y as %H:%M')}. "
            f"{google_status}. "
            f"{antigos.get('canceladas', 0)} lembrete(s) antigo(s) cancelado(s) e "
            f"{novos.get('criados', 0)} novo(s) criado(s)."
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[RescheduleTool] erro ao reagendar: %s", exc)
        db.rollback()
        return (
            "Nao consegui reagendar agora. Nao diga ao cliente que remarcou: informe que a "
            "equipe vai confirmar o novo horario."
        )
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


@function_tool(strict_mode=False)
def suggest_reschedule_before_cancel(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do cliente (formato: 5500000000009)")],
    user_preference: Annotated[str, Field(description="Preferência do usuário (ex: 'sexta', 'manhã', 'semana que vem')")] = "",
    preferred_time: Annotated[str, Field(description="Horário preferido para reagendar (formato: HH:MM)")] = ""
) -> str:
    """
    Busca horários alternativos para evitar cancelamento considerando preferência do usuário.

    Esta tool deve ser usada quando o cliente expressar desejo de cancelar,
    oferecendo alternativas de reagendamento antes do cancelamento definitivo.

    Args:
        company_id: ID numérico da empresa
        phone: Telefone do cliente
        user_preference: Preferência expressa pelo usuário (ex: "sexta", "manhã", "semana que vem")
        preferred_time: Horário preferido para reagendamento (opcional)

    Returns:
        Lista de horários alternativos disponíveis para reagendamento baseados na preferência
    """

    logger.info(f"[ReschedSuggestTool] Suggesting alternatives to avoid cancellation for {phone} at company {company_id}")
    logger.info(f"[ReschedSuggestTool] User preference: '{user_preference}'")

    try:
        # Import DatabaseSchedulingService directly (same as main system uses)
        from backend.agents_sdk.services.database_scheduling_service import DatabaseSchedulingService
        from backend.agents_sdk.tools.scheduling_tools import _analyze_scheduling_preferences_with_context
        from backend.db import get_db

        # Get database session
        db = next(get_db())

        # Create DatabaseSchedulingService (same as main system)
        slots_service = DatabaseSchedulingService(db=db, company_id=company_id)

        preference_to_search = user_preference if user_preference.strip() else ""

        logger.info(f"[ReschedSuggestTool] Using DatabaseSchedulingService with preference: '{preference_to_search}'")

        # Apply semantic analysis if user has preference
        weekday_name = None
        semantic_analysis = {}
        if preference_to_search.strip():
            try:
                import asyncio

                semantic_analysis = asyncio.run(
                    _analyze_scheduling_preferences_with_context(
                        preference_to_search,
                        [],
                        phone=phone,
                        company_id=company_id,
                        db=db,
                    )
                )
                weekday_name = semantic_analysis.get("weekday_name")
                logger.info(f"[ReschedSuggestTool] Semantic analysis: weekday_name='{weekday_name}'")
            except Exception as e:
                logger.warning(f"[ReschedSuggestTool] Semantic analysis failed: {e}")

        # Use slots_service directly since get_available_slots was removed from scheduling_tools
        try:
            # Get available slots directly from slots service
            # Using same logic as the main scheduling tool
            if hasattr(slots_service, 'get_available_slots_from_database'):
                # Use semantic analysis results if available
                weekday = None
                time_period = None

                if semantic_analysis:
                    weekday = semantic_analysis.get('weekday_name')
                    time_periods = semantic_analysis.get('time_periods', [])
                    if time_periods:
                        time_period = time_periods[0]

                # Get slots from database service
                available_slots = slots_service.get_available_slots_from_database(
                    limit=20,  # Get more slots for reagendamento options
                    weekday_name=weekday,
                    time_period=time_period,
                    day_type=None
                )

                if available_slots and len(available_slots) > 0:
                    # Format slots for display - take first 3 options for reagendamento
                    slots_to_show = available_slots[:3]
                    formatted_slots = []

                    for slot in slots_to_show:
                        # Format each slot nicely
                        weekday_str = slot.get('weekday', '')
                        date_str = slot.get('date', '')
                        time_str = slot.get('time', '')
                        formatted_slots.append(f"{weekday_str} {date_str} às {time_str}")

                    slots_result = "Posso reagendar para:\n" + "\n".join(formatted_slots)
                    logger.info(f"[ReschedSuggestTool] Found {len(available_slots)} slots, showing {len(slots_to_show)}")
                else:
                    slots_result = "Não encontrei horários disponíveis no período solicitado."
                    logger.info("[ReschedSuggestTool] No slots available from database")
            else:
                # Fallback if get_available_slots_from_database doesn't exist
                slots_result = "Não consegui verificar os horários disponíveis no momento."
                logger.warning("[ReschedSuggestTool] slots_service doesn't have get_available_slots_from_database method")

        except Exception as e:
            logger.error(f"[ReschedSuggestTool] Error getting slots: {e}")
            slots_result = "Não consegui verificar os horários disponíveis no momento."

        # Check if we got results
        if not slots_result or "não encontrei horários" in slots_result.lower() or "não temos horários" in slots_result.lower():
            return (
                "Entendo que você precisa cancelar. Infelizmente não temos "
                "horários disponíveis no período solicitado. "
                "Posso verificar outras opções próximas ou você prefere "
                "que confirme o cancelamento?"
            )

        # Format as reschedule suggestion
        response = "Antes de cancelarmos, que tal reagendarmos? " + slots_result + "\n\n"
        response += "Se algum destes horários funcionar, posso reagendar para você. "
        response += "Caso contrário, confirme e cancelarei sua consulta."

        logger.info(f"[ReschedSuggestTool] Successfully provided reschedule alternatives for {phone}")
        return response

    except Exception as e:
        logger.error(f"[ReschedSuggestTool] Error suggesting reschedule: {e}")
        return (
            "Entendo que você precisa cancelar. Infelizmente tive um problema "
            "ao buscar horários alternativos. Confirma o cancelamento ou "
            "prefere que eu tente novamente?"
        )
    finally:
        # Ensure database session is closed
        try:
            db.close()
        except:
            pass


# Tool registration for OpenAI Agents SDK
# This will be imported and used by the business assistant agent

@function_tool(strict_mode=False)
def confirm_lead_appointment(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do paciente (formato: 5500000000009)")],
    appointment_date: Annotated[str, Field(description="Data do agendamento que ele confirmou, DD/MM/AAAA ou AAAA-MM-DD. Opcional quando ele só tem um agendamento.")] = "",
    appointment_time: Annotated[str, Field(description="Horario confirmado, HH:MM. Opcional.")] = "",
) -> str:
    """
    REGISTRA A CONFIRMACAO do paciente para um agendamento que JA EXISTE.

    Use quando o paciente responder ao lembrete dizendo que vai comparecer: "sim", "confirmo",
    "ok", "estarei la", "pode confirmar". Nesse caso NUNCA use `create_lead_appointment` — o
    horario ja e dele, tentar reservar de novo devolve "horario indisponivel" e confunde o
    paciente.

    Marca `confirmed_at` no agendamento, cancela os lembretes que sobraram e devolve o resumo para
    voce responder com o que ele precisa saber (data, hora, profissional, endereco). Se ele quiser
    remarcar, use `suggest_reschedule_before_cancel`/`reschedule_appointment`; se quiser cancelar,
    `confirm_cancellation`.
    """
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from backend.db import get_db
    from backend.models import Agendamento, Agenda

    from .calendar_scheduling_tools import _cancelar_tarefas_de_lembrete, _normalize_phone

    db = next(get_db())
    try:
        telefone = _normalize_phone(phone) or phone
        candidatos = (
            db.query(Agendamento)
            .filter(
                Agendamento.company_id == company_id,
                Agendamento.phone == telefone,
                ~Agendamento.status.ilike("CANCEL%"),
            )
            .order_by(Agendamento.consulta_data)
            .all()
        )
        if not candidatos:
            return (
                "Nao encontrei agendamento ativo para esse telefone. Nao diga que confirmou: "
                "confirme com o paciente a data e o horario."
            )

        def _fuso(alvo):
            try:
                agenda = db.query(Agenda).filter(Agenda.id == alvo.agenda_id).first()
                return ZoneInfo((agenda.timezone if agenda else None) or "America/Sao_Paulo")
            except (ZoneInfoNotFoundError, ValueError):
                return ZoneInfo("America/Sao_Paulo")

        escolhido = candidatos[0]
        dia_pedido = None
        texto_data = str(appointment_date or "").strip()
        if texto_data:
            normalizado = texto_data.replace("/", "-")
            for formato in ("%d-%m-%Y", "%Y-%m-%d"):
                try:
                    dia_pedido = datetime.strptime(normalizado, formato).date()
                    break
                except ValueError:
                    continue
            if dia_pedido is not None:
                do_dia = [
                    item for item in candidatos
                    if item.consulta_data
                    and item.consulta_data.astimezone(_fuso(item)).date() == dia_pedido
                ]
                if not do_dia:
                    return (
                        f"Nao encontrei agendamento ativo em {texto_data}. Nao diga que confirmou: "
                        "confirme a data com o paciente."
                    )
                escolhido = do_dia[0]
                texto_hora = str(appointment_time or "").strip().replace("h", ":")
                achado = re.search(r"(\d{1,2})\s*:?\s*(\d{2})?", texto_hora)
                if achado:
                    hora = int(achado.group(1))
                    minuto = int(achado.group(2) or 0)
                    escolhido = min(
                        do_dia,
                        key=lambda item: abs(
                            (
                                item.consulta_data.astimezone(_fuso(item)).hour * 60
                                + item.consulta_data.astimezone(_fuso(item)).minute
                            )
                            - (hora * 60 + minuto)
                        ),
                    )

        if escolhido.status and escolhido.status.upper().startswith("CANCEL"):
            return "Esse agendamento esta cancelado; nao ha o que confirmar."

        fuso = _fuso(escolhido)
        quando_local = (
            escolhido.consulta_data.astimezone(fuso) if escolhido.consulta_data else None
        )

        ja_confirmado = escolhido.confirmed_at is not None
        escolhido.confirmed_at = datetime.now(fuso)
        escolhido.confirmed_via = "whatsapp"
        db.commit()

        lembretes = _cancelar_tarefas_de_lembrete(db, company_id, escolhido.id)

        agenda = db.query(Agenda).filter(Agenda.id == escolhido.agenda_id).first()
        nome_agenda = getattr(agenda, "name", None) or "a clinica"
        quando_texto = (
            quando_local.strftime("%d/%m/%Y as %H:%M") if quando_local else "a data combinada"
        )
        prefixo = "Confirmacao registrada novamente" if ja_confirmado else "Presenca confirmada"
        return (
            f"{prefixo}: {quando_texto} ({nome_agenda}). "
            f"Lembretes pendentes cancelados: {lembretes}. "
            "Nao crie agendamento novo. Agradeca, repita data/hora/profissional e entregue o "
            "endereco e as instrucoes de preparo em UMA mensagem."
        )
    finally:
        db.close()


APPOINTMENT_MANAGEMENT_TOOLS = [
    suggest_reschedule_before_cancel,
    confirm_cancellation,
    confirm_lead_appointment,
    reschedule_appointment
]
