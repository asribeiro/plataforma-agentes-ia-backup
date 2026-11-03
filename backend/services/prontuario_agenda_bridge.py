"""Ponte entre a agenda operacional (`agendamentos`) e o prontuário (`patients` / `patient_appointments`).

Problema medido em 02/11/2026: o módulo de prontuário entrou como uma ilha — `patients` e
`patient_appointments` com 0 linhas, enquanto `agendamentos` tinha 11. Nada no prontuário leem
`agendamentos`, então não havia como registrar evolução de uma consulta marcada pelo agente ou pelo
balcão.

Esta ponte garante, para cada agendamento:
- um `patients` (casado pelo telefone, criado se não existir), herdando `lead_id` quando houver;
- um `patient_appointments` ligado por `agendamento_id`, com início, duração (slot da agenda),
  profissional da agenda e status equivalente;
- quando o agendamento é cancelado na agenda, a consulta clínica vira `cancelled`.

É idempotente: pode rodar quantas vezes quiser (chamada na criação e no job de 5 min).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ORIGEM_AGENDA = "agenda"

# status da agenda -> status da consulta no prontuário
MAPA_STATUS = {
    "SCHEDULED": "scheduled",
    "AGENDADO": "scheduled",
    "CONFIRMED": "scheduled",
    "CONFIRMADO": "scheduled",
    "PENDING": "pending_confirmation",
    "PENDENTE": "pending_confirmation",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
    "CANCELADO": "cancelled",
    "NOSHOW": "no_show",
    "NO_SHOW": "no_show",
    "FALTOU": "no_show",
    "COMPLETED": "completed",
    "REALIZADO": "completed",
    "ATENDIDO": "completed",
}


def apenas_digitos(valor) -> str:
    """Telefone só com dígitos (o banco guarda formatos diferentes entre agenda e CRM)."""
    return "".join(caractere for caractere in str(valor or "") if caractere.isdigit())


def telefone_para_comparacao(valor) -> str:
    """Últimos 11 dígitos: casa '+55 (19) 9...' com '55199...' e com '199...'."""
    digitos = apenas_digitos(valor)
    return digitos[-11:] if len(digitos) > 11 else digitos


def garantir_paciente(
    db: Session,
    clinic_id: int,
    nome: Optional[str],
    telefone: Optional[str],
    lead_id: Optional[int] = None,
):
    """Devolve (paciente, 'existente'|'criado'). Casa por telefone; sem telefone, por lead_id."""
    from backend.models import Patient

    alvo = telefone_para_comparacao(telefone)
    paciente = None

    if alvo:
        for candidato in db.query(Patient).filter(Patient.clinic_id == clinic_id).all():
            if telefone_para_comparacao(candidato.phone) == alvo:
                paciente = candidato
                break

    if paciente is None and lead_id:
        paciente = (
            db.query(Patient)
            .filter(Patient.clinic_id == clinic_id, Patient.lead_id == lead_id)
            .first()
        )

    if paciente is not None:
        mudou = False
        if lead_id and not paciente.lead_id:
            paciente.lead_id = lead_id
            mudou = True
        if not paciente.phone and apenas_digitos(telefone):
            paciente.phone = apenas_digitos(telefone)
            mudou = True
        if mudou:
            db.commit()
            db.refresh(paciente)
        return paciente, "existente"

    paciente = Patient(
        clinic_id=clinic_id,
        name=(nome or "Paciente sem nome").strip()[:255],
        phone=apenas_digitos(telefone) or None,
        lead_id=lead_id,
        source=ORIGEM_AGENDA,
        lifecycle_status="lead",
    )
    db.add(paciente)
    db.commit()
    db.refresh(paciente)
    logger.info("[PonteProntuario] paciente criado %s (clinic %s)", paciente.id, clinic_id)
    return paciente, "criado"


def sincronizar_agendamento(db: Session, agendamento) -> dict:
    """Cria/atualiza a consulta clínica correspondente ao agendamento. Nunca levanta exceção grave."""
    from backend.models import Agenda, PatientAppointment

    if agendamento is None:
        return {"ok": False, "motivo": "agendamento ausente"}

    status_agenda = str(agendamento.status or "SCHEDULED").upper()
    status_clinico = MAPA_STATUS.get(status_agenda, "scheduled")

    existente = (
        db.query(PatientAppointment)
        .filter(
            PatientAppointment.clinic_id == agendamento.company_id,
            PatientAppointment.agendamento_id == agendamento.id,
        )
        .first()
    )

    if status_agenda.startswith("CANCEL"):
        if existente is None:
            return {"ok": True, "acao": "ignorado_cancelado", "agendamento_id": agendamento.id}
        existente.status = "cancelled"
        existente.cancellation_reason = (
            existente.cancellation_reason or "Cancelado na agenda"
        )[:255]
        db.commit()
        return {
            "ok": True,
            "acao": "cancelado",
            "agendamento_id": agendamento.id,
            "patient_appointment_id": existente.id,
        }

    agenda = db.query(Agenda).filter(Agenda.id == agendamento.agenda_id).first()
    profissional_id = getattr(agenda, "professional_id", None)
    if not profissional_id:
        logger.warning(
            "[PonteProntuario] agenda %s sem professional_id: agendamento %s fica sem consulta clínica",
            agendamento.agenda_id,
            agendamento.id,
        )
        return {
            "ok": False,
            "motivo": "agenda sem profissional vinculado",
            "agendamento_id": agendamento.id,
        }
    if not agendamento.consulta_data:
        return {"ok": False, "motivo": "agendamento sem data", "agendamento_id": agendamento.id}

    paciente, origem_paciente = garantir_paciente(
        db,
        agendamento.company_id,
        agendamento.nome,
        agendamento.phone,
        agendamento.lead_id,
    )
    duracao = int(getattr(agenda, "slot_duration", None) or 30)

    if existente is None:
        nova = PatientAppointment(
            clinic_id=agendamento.company_id,
            patient_id=paciente.id,
            professional_id=profissional_id,
            starts_at=agendamento.consulta_data,
            duration_minutes=duracao,
            source=ORIGEM_AGENDA,
            status=status_clinico,
            agendamento_id=agendamento.id,
        )
        db.add(nova)
        db.commit()
        db.refresh(nova)
        logger.info(
            "[PonteProntuario] consulta criada %s para agendamento %s (paciente %s)",
            nova.id,
            agendamento.id,
            origem_paciente,
        )
        return {
            "ok": True,
            "acao": "criado",
            "agendamento_id": agendamento.id,
            "patient_appointment_id": nova.id,
            "paciente": origem_paciente,
        }

    mudou = False
    if existente.patient_id != paciente.id:
        existente.patient_id = paciente.id
        mudou = True
    if existente.professional_id != profissional_id:
        existente.professional_id = profissional_id
        mudou = True
    if existente.starts_at != agendamento.consulta_data:
        existente.starts_at = agendamento.consulta_data
        mudou = True
    if existente.duration_minutes != duracao:
        existente.duration_minutes = duracao
        mudou = True
    if existente.status != status_clinico:
        existente.status = status_clinico
        mudou = True
    if existente.status != "cancelled" and existente.cancellation_reason:
        existente.cancellation_reason = None
        mudou = True
    if mudou:
        db.commit()
    return {
        "ok": True,
        "acao": "atualizado" if mudou else "sem_mudanca",
        "agendamento_id": agendamento.id,
        "patient_appointment_id": existente.id,
    }


def sincronizar_pendentes(db: Session, company_id: Optional[int] = None, limite: int = 500) -> dict:
    """Varre os agendamentos e sincroniza. Rede de segurança para caminhos que não chamam a ponte."""
    from backend.models import Agendamento

    consulta = db.query(Agendamento).order_by(Agendamento.id.desc())
    if company_id is not None:
        consulta = consulta.filter(Agendamento.company_id == company_id)

    resultado = {"analisados": 0, "criados": 0, "atualizados": 0, "cancelados": 0,
                 "sem_mudanca": 0, "falhas": 0, "motivos": {}}
    for agendamento in consulta.limit(limite).all():
        resultado["analisados"] += 1
        try:
            saida = sincronizar_agendamento(db, agendamento)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            resultado["falhas"] += 1
            logger.exception("[PonteProntuario] falha no agendamento %s: %s", agendamento.id, exc)
            continue
        if not saida.get("ok"):
            resultado["falhas"] += 1
            motivo = saida.get("motivo") or "desconhecido"
            resultado["motivos"][motivo] = resultado["motivos"].get(motivo, 0) + 1
            continue
        acao = saida.get("acao")
        if acao in ("criado", "atualizado", "cancelado", "sem_mudanca"):
            resultado[acao] += 1
    return resultado
