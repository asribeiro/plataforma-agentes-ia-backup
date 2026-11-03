from datetime import datetime, timezone

from backend.routes.clinical_record_routes import _signature_hash


def test_signature_hash_is_deterministic():
    signed_at = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    first = _signature_hash("note-1", 10, signed_at, "Evolução fictícia")
    second = _signature_hash("note-1", 10, signed_at, "Evolução fictícia")

    assert first == second
    assert len(first) == 64


def test_signature_hash_changes_when_note_content_changes():
    signed_at = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    first = _signature_hash("note-1", 10, signed_at, "Texto A")
    second = _signature_hash("note-1", 10, signed_at, "Texto B")

    assert first != second
