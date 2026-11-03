"""Regras puras do ciclo de vida do paciente."""

from datetime import datetime


def has_two_consecutive_no_shows(statuses: list[str]) -> bool:
    consecutive = 0
    for status in statuses:
        if status == "no_show":
            consecutive += 1
            if consecutive >= 2:
                return True
        elif status not in {"cancelled", "cancelled_by_patient", "cancelled_by_clinic"}:
            consecutive = 0
    return False


def calculate_lifecycle_status(
    *,
    has_risk: bool,
    has_active_treatment: bool,
    has_recurring_procedure: bool,
    has_scheduled_appointment: bool,
    is_inactive: bool,
    has_lead: bool,
) -> str:
    if has_risk:
        return "at_risk"
    if has_active_treatment:
        return "in_treatment"
    if has_recurring_procedure:
        return "in_maintenance"
    if has_scheduled_appointment:
        return "new_patient"
    if is_inactive:
        return "inactive"
    if has_lead:
        return "lead"
    return "inactive"
