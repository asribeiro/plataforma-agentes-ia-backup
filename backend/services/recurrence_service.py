"""Regras puras para geração de sessões recorrentes."""

from calendar import monthrange
from datetime import date, datetime, timedelta


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def recurrence_step(frequency: str, interval: int = 1) -> timedelta | None:
    if frequency == "weekly":
        return timedelta(weeks=interval)
    if frequency == "biweekly":
        return timedelta(weeks=2 * interval)
    if frequency == "semiannual":
        return None
    if frequency == "monthly":
        return None
    if frequency == "custom":
        return timedelta(days=interval)
    raise ValueError("frequência de recorrência inválida")


def generate_occurrences(
    start_at: datetime,
    frequency: str,
    *,
    interval: int = 1,
    sessions: int | None = None,
    end_at: datetime | None = None,
    window_days: int = 90,
) -> list[datetime]:
    if sessions is None and end_at is None:
        raise ValueError("recorrência exige sessões ou data final")
    if interval < 1:
        raise ValueError("intervalo deve ser positivo")
    if window_days < 1:
        raise ValueError("janela deve ser positiva")

    limit = min(end_at or start_at + timedelta(days=window_days), start_at + timedelta(days=window_days))
    occurrences = []
    current = start_at
    while current <= limit and (sessions is None or len(occurrences) < sessions):
        occurrences.append(current)
        if frequency == "monthly":
            current = _add_months(current, interval)
        elif frequency == "semiannual":
            current = _add_months(current, 6 * interval)
        else:
            step = recurrence_step(frequency, interval)
            current += step
    return occurrences
