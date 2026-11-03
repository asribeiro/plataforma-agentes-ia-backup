import pytest

from backend.routes.treatment_routes import RECURRENCE_FREQUENCIES, TreatmentProcedureCreate


def test_recurrence_frequency_accepts_supported_values():
    for frequency in RECURRENCE_FREQUENCIES:
        item = TreatmentProcedureCreate(
            name="Manutenção",
            recurrence_frequency=frequency,
            recurrence_sessions=12,
        )
        assert item.recurrence_frequency == frequency


def test_recurrence_rejects_sessions_and_end_date_together():
    with pytest.raises(ValueError):
        TreatmentProcedureCreate(
            name="Manutenção",
            recurrence_frequency="monthly",
            recurrence_sessions=12,
            recurrence_end_date="2027-10-31",
        )
