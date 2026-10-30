"""Qual credencial Google vale para esta agenda (card F1-06).

Antes: a credencial vivia so em `calendar_integrations` (uma por EMPRESA). Com
varios profissionais, toda agenda caia no mesmo token e no mesmo calendario — e a
pergunta "qual a disponibilidade da Dra. Ana?" nao tinha resposta possivel.

Agora a leitura e em cascata:

    1. token na propria agenda  (OAuth por profissional — opcao A decidida em 28/10)
    2. token na empresa         (clinica de um profissional so nao precisa reautorizar)
    3. nenhum                   (nao ha integracao: nada de Google, sem erro)

Cascata, e nao troca de fonte unica, por dois motivos praticos: (a) clinica nova
conecta a empresa uma vez e funciona; (b) migrar para por-agenda e por agenda, sem
janela de "todo mundo reautoriza hoje".

O objeto devolvido tem atributo `google_oauth_token`, que e tudo que
`build_google_oauth_service` le — de proposito. Agenda e CalendarIntegration
satisfazem a mesma interface, entao o refresh de token escreve no dono certo sem
precisar de codigo diferente por origem.
"""
import logging
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FONTE_AGENDA = "agenda"
FONTE_EMPRESA = "empresa"


def credencial_google_da_agenda(
    db: Session,
    company_id: Optional[int],
    agenda: Any = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """Devolve (objeto_com_token, fonte) ou (None, None) quando nao ha integracao.

    `fonte` existe para o log e para a tela: saber se a agenda usa credencial
    propria ou herdada da empresa e a diferenca entre "esta profissional autorizou"
    e "esta profissional usa a conta da clinica".
    """
    if agenda is not None and getattr(agenda, "google_oauth_token", None):
        return agenda, FONTE_AGENDA

    if not company_id:
        return None, None

    from backend.models import CalendarIntegration

    integracao = (
        db.query(CalendarIntegration)
        .filter(
            CalendarIntegration.company_id == company_id,
            CalendarIntegration.provider == "google",
        )
        .first()
    )
    if integracao is not None and getattr(integracao, "google_oauth_token", None):
        return integracao, FONTE_EMPRESA

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
    """Calendario alvo: o da agenda; sem ele, o da integracao da empresa."""
    proprio = getattr(agenda, "google_calendar_id", None)
    if proprio:
        return proprio
    dono, _fonte = credencial_google_da_agenda(db, company_id, agenda)
    if dono is not None and getattr(dono, "google_calendar_id", None):
        return dono.google_calendar_id
    return None
