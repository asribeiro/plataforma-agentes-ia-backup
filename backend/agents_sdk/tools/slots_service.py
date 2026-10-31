"""
Slots Service - Replace Redis with database table
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_
from ..database.models import CompanySlot

logger = logging.getLogger(__name__)


def resolver_agenda(
    agendas: List[Any],
    agenda_id: Optional[int] = None,
    professional_id: Optional[int] = None,
) -> tuple[Optional[Any], str]:
    """Escolhe a agenda que responde pelo horario. Funcao PURA, testavel.

    Devolve (agenda, motivo). Motivo vazio = resolvido.

    A regra existe porque a agenda passou a ser POR PROFISSIONAL (decisao de
    28/10). Antes, "a primeira agenda ativa da empresa" era uma resposta aceita
    porque so existia uma. Com N profissionais ela passa a estar ERRADA: seria
    responder o horario da Dra. Ana para quem perguntou pelo Dr. Bruno.

    - agenda_id         -> aquela agenda, se estiver entre as candidatas
    - professional_id   -> a agenda DAQUELE profissional (uma ativa por vinculo)
    - nenhum dos dois   -> so resolve quando existe UMA unica agenda ativa;
                           com duas ou mais, abstem ("ambiguo") em vez de
                           escolher no chute.
    """
    if not agendas:
        return None, "sem_agenda_ativa"

    if agenda_id is not None:
        for a in agendas:
            if getattr(a, "id", None) == agenda_id:
                return a, ""
        return None, "agenda_inexistente"

    if professional_id is not None:
        do_profissional = [
            a for a in agendas if getattr(a, "professional_id", None) == professional_id
        ]
        if not do_profissional:
            return None, "profissional_sem_agenda"
        return do_profissional[0], ""

    if len(agendas) == 1:
        return agendas[0], ""
    return None, "ambiguo"


class SlotsService:
    """
    Database-based slots management to replace Redis
    """

    def __init__(self, db: Session):
        self.db = db

    def _agenda_timezone(self, agenda) -> ZoneInfo:
        try:
            return ZoneInfo(getattr(agenda, "timezone", None) or "America/Sao_Paulo")
        except ZoneInfoNotFoundError:
            return ZoneInfo("America/Sao_Paulo")

    def _fetch_google_busy_intervals(self, company_id: int, agenda, start_date: date, end_date: date) -> List[Dict[str, datetime]]:
        calendar_id = getattr(agenda, "google_calendar_id", None)
        if not calendar_id:
            return []

        try:
            from backend.routes.integrations.google_calendar_service import get_busy_intervals
            from backend.services.google_credencial import build_service_da_agenda

            # F1-06: credencial da AGENDA (OAuth por profissional) e, quando nao
            # houver, a da empresa. Antes era sempre a da empresa: com N
            # profissionais, todas as agendas respondiam pela mesma conta.
            service, fonte = build_service_da_agenda(self.db, company_id, agenda)
            if not service:
                return []

            agenda_tz = self._agenda_timezone(agenda)
            start_dt = datetime.combine(start_date, time.min).replace(tzinfo=agenda_tz)
            end_dt = datetime.combine(end_date, time.max).replace(tzinfo=agenda_tz)

            # F1-03: freebusy responde "esta ocupado?" e enxerga compromisso que
            # nao e evento legivel pelo token (marcado direto no Gmail pela
            # secretaria). Antes so existia o que o proprio sistema reservou.
            ocupados = get_busy_intervals(
                calendar_id,
                start_dt.isoformat(),
                end_dt.isoformat(),
                service=service,
                time_zone=str(agenda_tz),
            )
            if ocupados is None:
                logger.warning(
                    "freebusy indisponivel na agenda %s (credencial=%s): calculando so com o banco local",
                    getattr(agenda, "id", None), fonte,
                )
                return []

            intervals: List[Dict[str, datetime]] = []
            for intervalo in ocupados:
                start_raw = intervalo.get("start")
                end_raw = intervalo.get("end")
                if not start_raw or not end_raw:
                    continue
                busy_start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00")).astimezone(agenda_tz)
                busy_end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")).astimezone(agenda_tz)
                intervals.append({
                    "start": busy_start.replace(tzinfo=None),
                    "end": busy_end.replace(tzinfo=None),
                })
            return intervals
        except Exception as exc:
            logger.warning("Failed to load Google Calendar blocks for agenda %s: %s", getattr(agenda, "id", None), exc)
            return []

    @staticmethod
    def _slot_blocked_by_google(slot_start: datetime, slot_duration: int, intervals: List[Dict[str, datetime]]) -> bool:
        slot_end = slot_start + timedelta(minutes=slot_duration)
        return any(block["start"] < slot_end and block["end"] > slot_start for block in intervals)

    def _generate_dynamic_slots(
        self,
        company_id: int,
        days_ahead: int = 60,
        agenda_id: Optional[int] = None,
        limit: int = 100,
        professional_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Internal method to generate slots with metadata dynamically"""
        try:
            from backend.models import Agenda, AgendaSchedule, Agendamento

            # 1. Agendas ativas candidatas
            query = self.db.query(Agenda).filter(
                Agenda.company_id == company_id,
                Agenda.active == True
            )
            agendas = query.all()

            # 2. A agenda que RESPONDE: por agenda_id, por professional_id, ou a
            #    unica existente. Com duas ou mais e nenhum endereco, abstem —
            #    devolver o horario da Dra. Ana para quem pediu do Dr. Bruno e
            #    resposta errada, nao resposta aproximada.
            agenda, motivo = resolver_agenda(
                agendas, agenda_id=agenda_id, professional_id=professional_id
            )
            if agenda is None:
                logger.info(
                    "sem agenda para responder (empresa=%s agenda_id=%s professional_id=%s): %s",
                    company_id, agenda_id, professional_id, motivo,
                )
                return []
            agenda_id = agenda.id

            # 2. Setup Time Range
            now = datetime.now()
            start_date = now.date()
            end_date = start_date + timedelta(days=days_ahead)

            safety_margin = timedelta(minutes=agenda.safety_margin_minutes or 180)
            min_booking_time = now + safety_margin

            # 3. Schedules Map
            schedules_map = {s.day_of_week: s for s in agenda.schedules}

            def _bloqueado_por_feriado(dia) -> bool:
                """Feriado fecha o dia; excecao por profissional libera (services/feriados.py)."""
                try:
                    from backend.services import feriados as servico_feriados

                    return (
                        servico_feriados.feriado_bloqueia(
                            db, dia, getattr(agenda, "professional_id", None)
                        )
                        is not None
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[Feriados] falha ao avaliar %s: %s", dia, exc)
                    return False

            # 4. Generate Theoretical Slots
            generated_slots = []
            current_day = start_date

            while current_day <= end_date:
                if _bloqueado_por_feriado(current_day):
                    current_day += timedelta(days=1)
                    continue
                weekday = current_day.weekday()
                if weekday in schedules_map:
                    sched = schedules_map[weekday]
                    periods = [
                        (sched.morning_start, sched.morning_end),
                        (sched.afternoon_start, sched.afternoon_end),
                        (sched.night_start, sched.night_end)
                    ]
                    for start_t, end_t in periods:
                        if start_t and end_t:
                            slot_start = datetime.combine(current_day, start_t)
                            period_end = datetime.combine(current_day, end_t)

                            while slot_start + timedelta(minutes=agenda.slot_duration) <= period_end:
                                if slot_start >= min_booking_time:
                                    # Enrich with metadata
                                    metadata = self._enrich_metadata_with_temporal_context(
                                        current_day, slot_start.time()
                                    )
                                    generated_slots.append({
                                        "slot_date": current_day,
                                        "slot_time": slot_start.time(),
                                        "datetime": slot_start,
                                        "metadata": metadata,
                                        "service_type": "Consulta",
                                        "source": "dynamic_agenda"
                                    })
                                slot_start += timedelta(minutes=agenda.slot_duration)
                current_day += timedelta(days=1)

            # 5. Filter Busy Slots
            busy_query = self.db.query(Agendamento).filter(
                Agendamento.company_id == company_id,
                Agendamento.consulta_data >= datetime.combine(start_date, time.min),
                Agendamento.consulta_data <= datetime.combine(end_date, time.max),
                Agendamento.status != 'CANCELLED'
            )
            # A agenda ja esta resolvida: o conflito de horario e SEMPRE dentro
            # dela. Um agendamento da Dra. Ana nao ocupa a agenda do Dr. Bruno.
            busy_query = busy_query.filter(Agendamento.agenda_id == agenda.id)

            busy_appointments = busy_query.all()

            busy_dt_set = set()
            for appt in busy_appointments:
                 if appt.consulta_data:
                     # Handle timezone naively to match generation
                     dt_naive = appt.consulta_data.replace(tzinfo=None)
                     busy_dt_set.add(dt_naive)

            google_busy_intervals = self._fetch_google_busy_intervals(company_id, agenda, start_date, end_date)

            available_slots = []
            for slot in generated_slots:
                # Check for exact match
                if (
                    slot["datetime"] not in busy_dt_set
                    and not self._slot_blocked_by_google(slot["datetime"], agenda.slot_duration, google_busy_intervals)
                ):
                     # De quem e o horario: sem isso o chamador nao consegue dizer
                     # ao paciente COM QUEM ele esta marcando.
                     slot["agenda_id"] = agenda.id
                     slot["professional_id"] = getattr(agenda, "professional_id", None)
                     available_slots.append(slot)
                     if len(available_slots) >= limit:
                         break

            return available_slots

        except Exception as e:
            logger.error(f"Error generating dynamic slots: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def filtrar_slots_indisponiveis(
        self,
        company_id: int,
        agenda,
        candidatos: List[datetime],
        agora: Optional[datetime] = None,
    ) -> List[datetime]:
        """Remove candidato que ja passou, que colide com agendamento desta agenda
        ou que o Google da como ocupado.

        POR QUE ESTE METODO EXISTE: a rota `GET /api/calendar/{id}/slots` tinha a
        propria geracao de horario e devolvia TODO slot do turno — passado, ocupado
        no banco e ocupado no Google. A tela entao oferecia vaga que o agente
        descartava na conversa seguinte. Duas regras de disponibilidade no mesmo
        sistema e um bug esperando reclamacao; aqui as duas chamam esta.

        `agora` e parametro para teste (nao depender do relogio da maquina).
        """
        if not candidatos:
            return []

        agora = agora or datetime.now()
        margem = int(getattr(agenda, "safety_margin_minutes", 0) or 0)
        limite = agora + timedelta(minutes=margem)

        from backend.models import Agendamento

        ocupados_banco = set()
        try:
            consulta = self.db.query(Agendamento).filter(
                Agendamento.agenda_id == agenda.id,
                or_(
                    Agendamento.status.is_(None),
                    ~Agendamento.status.ilike("%CANCELLED%"),
                ),
            )
            for appt in consulta.all():
                if appt.consulta_data is None:
                    continue
                ocupados_banco.add(appt.consulta_data.replace(tzinfo=None))
        except Exception as erro:  # noqa: BLE001 - banco e local: falha aparece no log
            logger.error("Falha ao ler agendamentos da agenda %s: %s", getattr(agenda, "id", None), erro)

        inicios = sorted(candidatos)
        intervalos_google = self._fetch_google_busy_intervals(
            company_id, agenda, inicios[0].date(), inicios[-1].date()
        )
        duracao = int(getattr(agenda, "slot_duration", 30) or 30)

        livres = []
        for inicio in inicios:
            if inicio <= limite:
                continue
            if inicio in ocupados_banco:
                continue
            if self._slot_blocked_by_google(inicio, duracao, intervalos_google):
                continue
            livres.append(inicio)
        return livres

    def get_available_slots(
        self,
        company_id: int,
        limit: int = 20,
        days_ahead: int = 30,
        agenda_id: Optional[int] = None,
        professional_id: Optional[int] = None
    ) -> List[str]:
        """
        Get available slots dynamically based on Agenda configuration.
        Returns simpler list of strings.

        `professional_id` endereca a agenda de UM profissional. Sem ele, so
        existe resposta quando a empresa tem uma unica agenda ativa.
        """
        slots = self._generate_dynamic_slots(
            company_id, days_ahead, agenda_id, limit, professional_id=professional_id
        )
        return [s["datetime"].strftime("%d/%m/%Y %H:%M") for s in slots]

    def get_available_slots_filtered(
        self,
        company_id: int,
        weekday_name: Optional[str] = None,
        time_period: Optional[str] = None,
        day_type: Optional[str] = None,
        limit: int = 20,
        agenda_id: Optional[int] = None,
        professional_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get available slots using intelligent metadata filtering on dynamic slots.
        """
        # Fetch more slots initially to allow for filtering
        raw_slots = self._generate_dynamic_slots(
            company_id, days_ahead=60, agenda_id=agenda_id, limit=300,
            professional_id=professional_id,
        )

        filtered = []
        for slot in raw_slots:
            meta = slot["metadata"]

            # Apply filters
            if weekday_name and meta.get("weekday_name") != weekday_name:
                continue
            if time_period and meta.get("time_period") != time_period:
                continue
            if day_type and meta.get("day_type") != day_type:
                continue

            filtered.append({
                "slot": slot["datetime"].strftime("%d/%m/%Y %H:%M"),
                "metadata": meta,
                "service_type": slot["service_type"],
                "source": slot["source"],
                "agenda_id": slot.get("agenda_id"),
                "professional_id": slot.get("professional_id"),
            })

            if len(filtered) >= limit:
                break

        logger.info(f"✅ Found {len(filtered)} filtered dynamic slots for company {company_id}")
        return filtered
    def add_slots_from_integration(
        self,
        company_id: int,
        slots_data: List[Dict[str, Any]],
        source: str = "integration"
    ) -> int:
        """
        Add slots from external integration (Google Calendar, Clinicorp, etc)

        Args:
            company_id: ID of the company
            slots_data: List of slot dictionaries with date, time, professional info
            source: Source identifier (google, clinicorp, manual)

        Returns:
            Number of slots added
        """
        added_count = 0

        try:
            for slot_data in slots_data:
                try:
                    # Parse slot data
                    slot_date_str = slot_data.get("date", "")
                    slot_time_str = slot_data.get("time", "")

                    # Convert to proper types
                    if "/" in slot_date_str:  # dd/mm/yyyy format
                        slot_date = datetime.strptime(slot_date_str, "%d/%m/%Y").date()
                    else:  # yyyy-mm-dd format
                        slot_date = datetime.strptime(slot_date_str, "%Y-%m-%d").date()

                    slot_time = datetime.strptime(slot_time_str, "%H:%M").time()

                    # Check if slot already exists
                    existing = self.db.query(CompanySlot).filter(
                        and_(
                            CompanySlot.company_id == company_id,
                            CompanySlot.slot_date == slot_date,
                            CompanySlot.slot_time == slot_time
                        )
                    ).first()

                    if existing:
                        # Update existing slot
                        existing.is_available = slot_data.get("available", True)
                        existing.service_type = slot_data.get("service_type")
                        existing.source = source
                        existing.slot_metadata = slot_data.get("metadata", {})
                        existing.expires_at = datetime.now() + timedelta(hours=24)
                        existing.updated_at = datetime.now()
                    else:
                        # Create new slot with temporal context
                        temporal_metadata = self._enrich_metadata_with_temporal_context(
                            slot_date, slot_time, slot_data.get("metadata", {})
                        )

                        new_slot = CompanySlot(
                            company_id=company_id,
                            slot_date=slot_date,
                            slot_time=slot_time,
                            service_type=slot_data.get("service_type"),
                            is_available=slot_data.get("available", True),
                            source=source,
                            slot_metadata=temporal_metadata,
                            expires_at=datetime.now() + timedelta(hours=24)
                        )
                        self.db.add(new_slot)
                        added_count += 1

                except Exception as e:
                    logger.error(f"Error processing slot {slot_data}: {e}")
                    continue

            self.db.commit()
            logger.info(f"✅ Added/updated {added_count} slots for company {company_id} from {source}")
            return added_count

        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error adding slots for company {company_id}: {e}")
            return 0

    def reserve_slot(
        self,
        company_id: int,
        slot_datetime: str,
        customer_info: Dict[str, Any] = None
    ) -> bool:
        """
        Reserve a slot (mark as unavailable)

        Args:
            company_id: ID of the company
            slot_datetime: Slot in "dd/mm/yyyy HH:MM" format
            customer_info: Optional customer information

        Returns:
            True if reservation successful
        """
        try:
            # Parse datetime
            slot_dt = datetime.strptime(slot_datetime, "%d/%m/%Y %H:%M")
            slot_date = slot_dt.date()
            slot_time = slot_dt.time()

            # Find and reserve the slot
            slot = self.db.query(CompanySlot).filter(
                and_(
                    CompanySlot.company_id == company_id,
                    CompanySlot.slot_date == slot_date,
                    CompanySlot.slot_time == slot_time,
                    CompanySlot.is_available == True
                )
            ).first()

            if slot:
                slot.is_available = False
                if customer_info:
                    slot.slot_metadata = {
                        **(slot.slot_metadata or {}),
                        "reservation": customer_info,
                        "reserved_at": datetime.now().isoformat()
                    }
                slot.updated_at = datetime.now()
                self.db.commit()

                logger.info(f"✅ Reserved slot {slot_datetime} for company {company_id}")
                return True
            else:
                logger.warning(f"Slot {slot_datetime} not available for company {company_id}")
                return False

        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error reserving slot {slot_datetime} for company {company_id}: {e}")
            return False

    def cleanup_expired_slots(self, company_id: int = None) -> int:
        """
        Remove expired slots

        Args:
            company_id: Optional company ID to filter by

        Returns:
            Number of slots removed
        """
        try:
            query = self.db.query(CompanySlot).filter(
                and_(
                    CompanySlot.expires_at.isnot(None),
                    CompanySlot.expires_at < datetime.now()
                )
            )

            if company_id:
                query = query.filter(CompanySlot.company_id == company_id)

            expired_slots = query.all()
            count = len(expired_slots)

            for slot in expired_slots:
                self.db.delete(slot)

            self.db.commit()
            logger.info(f"🧹 Cleaned up {count} expired slots")
            return count

        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error cleaning expired slots: {e}")
            return 0

    def get_slots_stats(self, company_id: int) -> Dict[str, Any]:
        """Get statistics about slots for monitoring"""
        try:
            result = self.db.execute(text("""
                SELECT
                    source,
                    COUNT(*) as total,
                    COUNT(CASE WHEN is_available THEN 1 END) as available,
                    COUNT(CASE WHEN NOT is_available THEN 1 END) as reserved,
                    MIN(slot_date) as earliest_date,
                    MAX(slot_date) as latest_date
                FROM company_slots
                WHERE company_id = :company_id
                AND (expires_at IS NULL OR expires_at > NOW())
                GROUP BY source
            """), {"company_id": company_id}).fetchall()

            stats = {
                "company_id": company_id,
                "sources": {},
                "total_slots": 0,
                "available_slots": 0,
                "reserved_slots": 0
            }

            for row in result:
                source_stats = {
                    "total": row.total,
                    "available": row.available,
                    "reserved": row.reserved,
                    "date_range": {
                        "earliest": row.earliest_date.isoformat() if row.earliest_date else None,
                        "latest": row.latest_date.isoformat() if row.latest_date else None
                    }
                }
                stats["sources"][row.source] = source_stats
                stats["total_slots"] += row.total
                stats["available_slots"] += row.available
                stats["reserved_slots"] += row.reserved

            return stats

        except Exception as e:
            logger.error(f"❌ Error getting slots stats for company {company_id}: {e}")
            return {"company_id": company_id, "error": str(e)}

    def populate_sample_slots(self, company_id: int, days: int = 7) -> int:
        """
        Add sample slots for testing (temporary method)

        Args:
            company_id: ID of the company
            days: Number of days to create slots for

        Returns:
            Number of slots created
        """
        try:
            start_date = date.today() + timedelta(days=1)  # Start tomorrow
            sample_times = ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00"]

            # Available professionals (stored in metadata, not as individual slots)
            available_professionals = ["Dr. Silva", "Dra. Santos", "Dr. Costa"]

            slots_data = []
            for day in range(days):
                current_date = start_date + timedelta(days=day)
                # Skip weekends for sample data
                if current_date.weekday() < 5:  # Monday=0, Sunday=6
                    for time_str in sample_times:
                        # Create ONE slot per time (not per professional)
                        slots_data.append({
                            "date": current_date.strftime("%d/%m/%Y"),
                            "time": time_str,
                            "available": True,
                            "service_type": "Consulta",
                            "metadata": {
                                "sample": True,
                                "available_professionals": available_professionals,
                                "slot_type": "available",
                                "company_capacity": len(available_professionals)
                            }
                        })

            added = self.add_slots_from_integration(company_id, slots_data, "sample")
            logger.info(f"✅ Created {added} sample slots for company {company_id}")
            return added

        except Exception as e:
            logger.error(f"❌ Error creating sample slots for company {company_id}: {e}")
            return 0

    def _enrich_metadata_with_temporal_context(
        self,
        slot_date: date,
        slot_time: time,
        existing_metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Enrich slot metadata with temporal context for LLM understanding
        """
        if existing_metadata is None:
            existing_metadata = {}

        # Calculate temporal context directly here
        reference_datetime = datetime.now()
        reference_date = reference_datetime.date()
        days_diff = (slot_date - reference_date).days

        # Weekday name in Portuguese
        weekday_names = {
            0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
            3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
        }
        weekday_name = weekday_names.get(slot_date.weekday(), "Desconhecido")

        # Time period
        hour = slot_time.hour
        if hour < 12:
            time_period = "manha"
        elif hour < 18:
            time_period = "tarde"
        else:
            time_period = "noite"

        # Day type
        if days_diff == 0:
            day_type = "hoje"
        elif days_diff == 1:
            day_type = "amanha"
        elif days_diff == 2:
            day_type = "depois_amanha"
        elif 3 <= days_diff <= 6:
            day_type = "essa_semana"
        elif 7 <= days_diff <= 13:
            day_type = "semana_que_vem"
        elif 21 <= days_diff <= 31:
            day_type = "mes_que_vem"
        else:
            day_type = "futuro_distante"

        # Merge with existing metadata
        enhanced_metadata = {
            **existing_metadata,
            "weekday_name": weekday_name,
            "day_type": day_type,
            "time_period": time_period,
            "relative_days": days_diff,
            "is_weekend": slot_date.weekday() >= 5,
            "is_today": days_diff == 0,
            "is_this_week": 0 <= days_diff <= 6,
            "is_next_week": 7 <= days_diff <= 13,
            "enhanced_at": datetime.now().isoformat()
        }

        return enhanced_metadata
