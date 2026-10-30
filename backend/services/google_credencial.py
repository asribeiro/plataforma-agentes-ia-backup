"""Resolve the Google OAuth credential attached to a professional's agenda."""
import logging
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FONTE_AGENDA = "agenda"
def credencial_google_da_agenda(
    db: Session,
    company_id: Optional[int],
    agenda: Any = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """Return the agenda credential, or (None, None) if it is not connected."""
    if agenda is not None and getattr(agenda, "google_oauth_token", None):
        return agenda, FONTE_AGENDA

    return None, None


def build_service_da_agenda(db: Session, company_id: Optional[int], agenda: Any = None):
    """Cliente Calendar API para esta agenda, ou None quando nao ha credencial.

    None aqui NAO e erro: clinica sem Google simplesmente nao sincroniza. Quem
    chama decide se a ausencia muda o comportamento (slots usam so o banco local,
    por exemplo).
    """
    dono, fonte = credencial_google_da_agenda(db, company_id, agenda)
    if dono is None:
        return None, None

    from backend.routes.integrations.google_calendar_service import (
        build_google_oauth_service,
    )

    servico = build_google_oauth_service(dono, db)
    if servico is None:
        logger.warning(
            "Credencial Google presente (%s) mas servico nao subiu para agenda=%s empresa=%s",
            fonte,
            getattr(agenda, "id", None),
            company_id,
        )
    return servico, fonte


def calendar_id_da_agenda(db: Session, company_id: Optional[int], agenda: Any) -> Optional[str]:
    """Return only the calendar explicitly selected for this agenda."""
    return getattr(agenda, "google_calendar_id", None)
