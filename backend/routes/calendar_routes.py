"""CRUD de agenda e slots, agora POR PROFISSIONAL (F1-10).

Por que este arquivo mudou: `agendas.professional_id` existe desde a migration
0009, mas o CRUD criava agenda SEM profissional e a listagem devolvia todas as
agendas da empresa sem dizer de quem eram. Com mais de um profissional isso vira
dois defeitos de uma vez:

  1. QUALQUER usuario da empresa ve e edita a agenda de qualquer colega;
  2. o horario oferecido nao tem dono — nao da para responder "a Dra. Ana tem
     horario amanha as 15h?".

Regras que passam a valer:

- `professional_id` e OBRIGATORIO no cadastro de agenda nova.
- O profissional tem de ser da MESMA empresa e estar ativo (senao 404/409).
- 1 profissional = 1 agenda ATIVA. A garantia dura esta no banco (indice unico
  parcial uq_agendas_professional_active, WHERE active IS TRUE), mas o erro do
  banco nao explica nada ao usuario: aqui a checagem vem antes e o
  IntegrityError tambem e traduzido em 409 com mensagem de negocio.
- Listagem aceita `professional_id` para filtrar; sem filtro continua
  devolvendo as agendas da empresa (compatibilidade), agora com o dono visivel.

NAO entra aqui: tela (F1-11) e tools do agente (F1-04).
"""
import logging
from datetime import time, date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Agenda, AgendaSchedule, Company, Professional, User

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Schemas ---

class ScheduleBase(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    morning_start: Optional[time] = None
    morning_end: Optional[time] = None
    afternoon_start: Optional[time] = None
    afternoon_end: Optional[time] = None
    night_start: Optional[time] = None
    night_end: Optional[time] = None


class AgendaBase(BaseModel):
    name: str
    slot_duration: int = Field(..., gt=0)
    active: bool = True
    timezone: str = "America/Sao_Paulo"
    safety_margin_minutes: int = Field(30, ge=0)
    google_calendar_id: Optional[str] = None
    google_calendar_summary: Optional[str] = None
    google_calendar_time_zone: Optional[str] = None
    # De quem e a agenda. Obrigatorio no cadastro (ver AgendaCreate).
    professional_id: Optional[int] = None


class AgendaCreate(AgendaBase):
    # Na criacao o vinculo NAO e opcional: agenda sem dono e o defeito que este
    # card fecha.
    professional_id: int = Field(..., gt=0)
    schedules: List[ScheduleBase]


class AgendaUpdate(AgendaBase):
    schedules: Optional[List[ScheduleBase]] = None


class ScheduleResponse(ScheduleBase):
    id: int
    agenda_id: int

    class Config:
        orm_mode = True


class AgendaResponse(AgendaBase):
    id: int
    company_id: int
    created_at: datetime
    schedules: List[ScheduleResponse]

    class Config:
        orm_mode = True


class Slot(BaseModel):
    start_time: datetime
    end_time: datetime


# --- Helpers ---

def _company_id_from_user(current_user: User) -> Optional[int]:
    if hasattr(current_user, 'company_id') and current_user.company_id:
        return current_user.company_id

    if hasattr(current_user, 'companies') and current_user.companies:
        first_item = current_user.companies[0]
        return getattr(first_item, 'id', getattr(first_item, 'company_id', None))

    if hasattr(current_user, 'client') and current_user.client and current_user.client.companies:
        first_item = current_user.client.companies[0]
        return getattr(first_item, 'id', getattr(first_item, 'company_id', None))

    return None


def validar_profissional_da_empresa(
    db: Session, company_id: int, professional_id: int
) -> Professional:
    """O profissional tem de ser DESTA empresa e estar ativo.

    Funcao separada de proposito: e a regra que impede uma clinica de vincular
    agenda ao profissional de outra, e ela precisa ser testavel sem subir a API.
    """
    prof = (
        db.query(Professional)
        .filter(
            Professional.id == professional_id,
            Professional.company_id == company_id,
        )
        .first()
    )
    if not prof:
        raise HTTPException(
            status_code=404,
            detail="Profissional não encontrado nesta empresa",
        )
    if not prof.active:
        raise HTTPException(
            status_code=409,
            detail=(
                f'O profissional "{prof.name}" está inativo. Reative o cadastro '
                "antes de vincular uma agenda a ele."
            ),
        )
    return prof


def validar_agenda_unica_ativa(
    db: Session, professional_id: int, ignorar_agenda_id: Optional[int] = None
) -> None:
    """1 profissional = 1 agenda ATIVA.

    Espelha o indice unico parcial do banco (uq_agendas_professional_active),
    mas com mensagem que o usuario entende: o erro cru do Postgres nao diz o que
    fazer. `ignorar_agenda_id` permite editar a propria agenda sem colidir
    consigo mesma.
    """
    q = db.query(Agenda).filter(
        Agenda.professional_id == professional_id,
        Agenda.active.is_(True),
    )
    if ignorar_agenda_id is not None:
        q = q.filter(Agenda.id != ignorar_agenda_id)
    existente = q.first()
    if existente:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Este profissional já tem a agenda ativa \"{existente.name}\". "
                "Um profissional tem uma agenda só: edite a existente ou "
                "desative-a antes de criar outra."
            ),
        )


def _commit_agenda(db: Session) -> None:
    """Commit com traducao do erro do indice parcial em mensagem de negocio."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_agendas_professional_active" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Este profissional já possui uma agenda ativa. "
                    "Desative a anterior antes de criar uma nova."
                ),
            )
        raise


def generate_slots_for_range(date_obj: date, start: time, end: time, duration: int) -> List[Slot]:
    slots = []
    if not start or not end:
        return slots

    current_dt = datetime.combine(date_obj, start)
    end_dt = datetime.combine(date_obj, end)

    while current_dt + timedelta(minutes=duration) <= end_dt:
        slot_end = current_dt + timedelta(minutes=duration)
        slots.append(Slot(start_time=current_dt, end_time=slot_end))
        current_dt = slot_end

    return slots


# --- Routes ---

@router.post("/", response_model=AgendaResponse)
def create_agenda(
    agenda: AgendaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    if not company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")

    # 1) o dono da agenda existe, e desta empresa, e esta ativo
    validar_profissional_da_empresa(db, company_id, agenda.professional_id)
    # 2) agenda nova ativa nao pode duplicar a do mesmo profissional
    if agenda.active:
        validar_agenda_unica_ativa(db, agenda.professional_id)

    db_agenda = Agenda(
        company_id=company_id,
        professional_id=agenda.professional_id,
        name=agenda.name,
        slot_duration=agenda.slot_duration,
        active=agenda.active,
        timezone=agenda.timezone,
        safety_margin_minutes=agenda.safety_margin_minutes
    )
    db.add(db_agenda)
    db.commit()
    db.refresh(db_agenda)

    for sched in agenda.schedules:
        db_sched = AgendaSchedule(
            agenda_id=db_agenda.id,
            day_of_week=sched.day_of_week,
            morning_start=sched.morning_start,
            morning_end=sched.morning_end,
            afternoon_start=sched.afternoon_start,
            afternoon_end=sched.afternoon_end,
            night_start=sched.night_start,
            night_end=sched.night_end
        )
        db.add(db_sched)

    _commit_agenda(db)
    db.refresh(db_agenda)
    return db_agenda


@router.get("/", response_model=List[AgendaResponse])
def list_agendas(
    professional_id: Optional[int] = Query(None, description="Filtra a agenda de um profissional"),
    incluir_inativas: bool = Query(False, description="Traz também as agendas desativadas"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    if not company_id:
        return []

    q = db.query(Agenda).filter(Agenda.company_id == company_id)
    if professional_id is not None:
        q = q.filter(Agenda.professional_id == professional_id)
    if not incluir_inativas:
        q = q.filter(Agenda.active.is_(True))
    return q.all()


@router.get("/{agenda_id}", response_model=AgendaResponse)
def get_agenda(
    agenda_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    agenda = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.company_id == company_id).first()
    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda not found")
    return agenda


@router.put("/{agenda_id}", response_model=AgendaResponse)
def update_agenda(
    agenda_id: int,
    agenda_update: AgendaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    db_agenda = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.company_id == company_id).first()
    if not db_agenda:
        raise HTTPException(status_code=404, detail="Agenda not found")

    # Trocar o dono da agenda e permitido, mas com a mesma validacao da criacao:
    # nao se transfere agenda para profissional de outra empresa.
    novo_profissional = (
        agenda_update.professional_id
        if agenda_update.professional_id is not None
        else db_agenda.professional_id
    )
    if novo_profissional is not None and novo_profissional != db_agenda.professional_id:
        validar_profissional_da_empresa(db, company_id, novo_profissional)
        if agenda_update.active:
            validar_agenda_unica_ativa(db, novo_profissional, ignorar_agenda_id=db_agenda.id)

    db_agenda.name = agenda_update.name
    db_agenda.slot_duration = agenda_update.slot_duration
    db_agenda.active = agenda_update.active
    db_agenda.timezone = agenda_update.timezone
    db_agenda.safety_margin_minutes = agenda_update.safety_margin_minutes
    if agenda_update.professional_id is not None:
        db_agenda.professional_id = agenda_update.professional_id

    if agenda_update.schedules is not None:
        # Remove old schedules
        db.query(AgendaSchedule).filter(AgendaSchedule.agenda_id == agenda_id).delete()
        # Add new ones
        for sched in agenda_update.schedules:
            new_sched = AgendaSchedule(
                agenda_id=agenda_id,
                day_of_week=sched.day_of_week,
                morning_start=sched.morning_start,
                morning_end=sched.morning_end,
                afternoon_start=sched.afternoon_start,
                afternoon_end=sched.afternoon_end,
                night_start=sched.night_start,
                night_end=sched.night_end
            )
            db.add(new_sched)

    _commit_agenda(db)
    db.refresh(db_agenda)
    return db_agenda


@router.get("/{agenda_id}/slots", response_model=List[Slot])
def get_available_slots(
    agenda_id: int,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    agenda = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.company_id == company_id).first()
    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda not found")

    if not agenda.active:
        return []

    # Get schedules mapped by day_of_week
    schedules = {s.day_of_week: s for s in agenda.schedules}

    all_slots = []

    # Iterate through days
    delta = end_date - start_date
    for i in range(delta.days + 1):
        day = start_date + timedelta(days=i)
        weekday = day.weekday() # 0=Monday

        if weekday in schedules:
            sched = schedules[weekday]
            # Morning
            all_slots.extend(generate_slots_for_range(day, sched.morning_start, sched.morning_end, agenda.slot_duration))
            # Afternoon
            all_slots.extend(generate_slots_for_range(day, sched.afternoon_start, sched.afternoon_end, agenda.slot_duration))
            # Night
            all_slots.extend(generate_slots_for_range(day, sched.night_start, sched.night_end, agenda.slot_duration))

    # F1-03: a rota usa a MESMA regra de disponibilidade do agente. Antes ela
    # devolvia todo slot do turno — inclusive passado, ocupado no banco e ocupado
    # no Google — e a tela oferecia vaga que o agente descartava na conversa.
    from backend.agents_sdk.tools.slots_service import SlotsService

    por_inicio = {slot.start_time: slot for slot in all_slots}
    livres = SlotsService(db).filtrar_slots_indisponiveis(
        company_id, agenda, list(por_inicio.keys())
    )
    return [por_inicio[inicio] for inicio in livres]
