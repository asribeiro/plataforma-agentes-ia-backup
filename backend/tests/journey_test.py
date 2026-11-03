from backend.services.journey_service import (
    calculate_lifecycle_status,
    has_two_consecutive_no_shows,
)


def test_two_consecutive_no_shows_trigger_risk():
    assert has_two_consecutive_no_shows(["attended", "no_show", "no_show"])
    assert not has_two_consecutive_no_shows(["no_show", "attended", "no_show"])


def test_lifecycle_priority_puts_risk_first():
    assert calculate_lifecycle_status(
        has_risk=True,
        has_active_treatment=True,
        has_recurring_procedure=True,
        has_scheduled_appointment=True,
        is_inactive=True,
        has_lead=True,
    ) == "at_risk"
