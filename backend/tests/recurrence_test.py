from datetime import datetime

import pytest

from backend.services.recurrence_service import generate_occurrences


def test_monthly_recurrence_generates_twelve_sessions_within_window():
    occurrences = generate_occurrences(
        datetime(2026, 1, 31, 10, 0),
        "monthly",
        sessions=12,
        window_days=365,
    )

    assert len(occurrences) == 12
    assert occurrences[1].day == 28


def test_recurrence_requires_target():
    with pytest.raises(ValueError):
        generate_occurrences(datetime(2026, 1, 1, 10, 0), "weekly")
