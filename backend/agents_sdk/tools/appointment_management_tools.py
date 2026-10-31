"""
Appointment Management Tools - OpenAI Agents SDK compatible tools for appointment management

This module provides LLM-driven tools for cancelling and rescheduling appointments,
integrating with the existing agendamento_logic.py infrastructure for consistent
behavior across Google Calendar, Clinicorp, and Webhook integrations.
"""

import logging
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
    new_date: Annotated[str, Field(description="Nova data no formato DD/MM/YYYY")],
    new_time: Annotated[str, Field(description="Novo horário no formato HH:MM")],
    treatment_type: Annotated[str, Field(description="Tipo de tratamento")] = "Consulta de Avaliação",
    customer_type: Annotated[str, Field(description="Tipo de cliente: 'novo' ou 'retorno'")] = "novo"
) -> str:
    """
    Reagenda consulta existente para nova data/horário.

    Fluxo automático integrado:
    1. Cancela agendamento atual (Google Calendar/Clinicorp/Local)
    2. Valida disponibilidade do novo horário
    3. Cria novo agendamento na data/hora especificada
    4. Sincroniza com integração ativa (Google/Clinicorp/Webhook)
    5. Envia nova confirmação ao cliente

    Args:
        company_id: ID numérico da empresa
        phone: Telefone no formato brasileiro completo
        customer_name: Nome completo do cliente
        new_date: Nova data no formato brasileiro DD/MM/YYYY
        new_time: Novo horário no formato 24h HH:MM
        treatment_type: Tipo de tratamento (padrão: "Consulta de Avaliação")
        customer_type: "novo" para primeira consulta, "retorno" para clientes existentes

    Returns:
        Mensagem de confirmação do reagendamento com novos detalhes

    Example:
        >>> result = reschedule_appointment(
        ...     company_id=42,
        ...     phone="5500000000009",
        ...     customer_name="João Silva",
        ...     new_date="15/09/2025",
        ...     new_time="14:30",
        ...     treatment_type="Limpeza",
        ...     customer_type="retorno"
        ... )
        >>> print(result)
        "João Silva, seu reagendamento está confirmado! Nova data: 15/09/2025 às 14:30..."
    """

    logger.info(f"[RescheduleTool] Processing reschedule for {phone} at company {company_id} to {new_date} {new_time}")

    try:
        # Import required services
        from backend.prompt.db_integration.agendamento_logic import processar_json_do_llm
        from backend.prompt.llm.slot_verification import verify_slot_availability
        from backend.db import get_db

        # Get database session
        db = next(get_db())

        # Step 0: Check if new date is after current appointment
        try:
            from sqlalchemy.sql import text
            from datetime import datetime

            result = db.execute(text("""
                SELECT consulta_data
                FROM agendamentos
                WHERE phone = :phone AND company_id = :company_id
                AND status NOT LIKE 'CANCELLED%'
                ORDER BY id DESC
                LIMIT 1
            """), {"phone": phone, "company_id": company_id})

            row = result.fetchone()
            if row and row.consulta_data:
                current_appointment_date = row.consulta_data.date()
                new_appointment_date = datetime.strptime(new_date, "%d/%m/%Y").date()

                if new_appointment_date <= current_appointment_date:
                    return (
                        f"A nova data ({new_date}) deve ser posterior à sua consulta atual "
                        f"({current_appointment_date.strftime('%d/%m/%Y')}). "
                        "Por favor, escolha uma data futura."
                    )

                logger.info(f"[RescheduleTool] Date validation OK: {new_date} > {current_appointment_date}")
        except Exception as e:
            logger.warning(f"[RescheduleTool] Could not validate appointment date: {e}")

        # Step 1: Validate new slot availability
        try:
            slot_available = verify_slot_availability(
                db=db,
                company_id=company_id,
                requested_date=new_date,
                requested_time=new_time
            )

            if not slot_available:
                return (
                    f"O horário {new_date} às {new_time} não está disponível. "
                    "Por favor, escolha outro horário."
                )
        except Exception as e:
            logger.warning(f"[RescheduleTool] Could not verify slot availability: {e}")
            # Continue with reschedule attempt - slot verification is optional

        # Step 2: Process reschedule as cancellation + new appointment
        # The existing logic in processar_json_do_llm already handles this pattern
        # by cancelling old appointments before creating new ones

        # Create LLM JSON format for confirmation (reschedule)
        llm_json = {
            "agendamento_confirmado": True,
            "cancelar_agendamento": False,
            "nome": customer_name,
            "data": new_date,
            "horario": new_time,
            "tratamento": treatment_type,
            "cliente": customer_type,
            "is_reschedule": True  # Flag to indicate this is a reschedule operation
        }

        # Get API key for webhook integration
        api_key = None
        try:
            from sqlalchemy.sql import text
            row_client_data = db.execute(text("""
                SELECT c.api_key
                FROM clients c
                JOIN client_companies cc ON cc.client_id = c.id
                WHERE cc.company_id = :cid LIMIT 1
            """), {"cid": company_id}).fetchone()
            if row_client_data and hasattr(row_client_data, 'api_key'):
                api_key = row_client_data.api_key
        except Exception as e:
            logger.error(f"Error fetching api_key for company_id {company_id}: {e}")

        # Process reschedule using existing confirmation logic
        # The router will automatically cancel old appointment before creating new one
        result = processar_json_do_llm(
            db=db,
            company_id=company_id,
            phone=phone,
            llm_json=llm_json,
            api_key=api_key
        )

        logger.info(f"[RescheduleTool] Reschedule processed successfully for {phone}")

        # Enhance the confirmation message to indicate reschedule
        if result and not result.startswith("Erro") and not result.startswith("Ocorreu"):
            # Add reschedule context to confirmation message
            reschedule_note = "\n\n✅ Reagendamento realizado com sucesso!"
            result = reschedule_note + "\n\n" + result

        return result or f"Reagendamento confirmado para {new_date} às {new_time}!"

    except Exception as e:
        logger.error(f"[RescheduleTool] Error processing reschedule: {e}")
        return (
            "Ocorreu um erro ao processar o reagendamento. "
            "Nossa equipe foi notificada. Por favor, tente novamente ou entre em contato."
        )
    finally:
        # Ensure database session is closed
        try:
            db.close()
        except:
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
APPOINTMENT_MANAGEMENT_TOOLS = [
    suggest_reschedule_before_cancel,
    confirm_cancellation,
    reschedule_appointment
]
