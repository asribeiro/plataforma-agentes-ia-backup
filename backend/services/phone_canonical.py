"""Telefone canônico para guardar mensagem: resolve LID em QUALQUER caminho de envio.

Defeito medido em 02/11/2026 (print do dono: "as mensagens que o agente enviou não aparecem na
plataforma"): as respostas do agente foram gravadas com o ID oculto (`140501365833969`) e uma
mensagem com telefone `0`, então a plataforma — que lista por telefone do contato — não as exibe.

O conserto anterior cobriu o caminho de entrada do worker, mas o envio passa por
`_persist_waha_message`, que gravava o telefone cru.

Este módulo centraliza: telefone canônico = telefone do contato (`contacts.phone`), resolvendo:
  1. sufixo (@c.us, @lid, @s.whatsapp.net, @g.us);
  2. `contacts.sender_lid` (mapeamento que já existe no banco);
  3. API do WAHA (`get_phone_by_lid`), com cache Redis de 7 dias, para LID desconhecido.
"""
import logging
import re
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

CACHE_PREFIX = "waha:lid2phone:"
CACHE_TTL_SECONDS = 7 * 24 * 3600


def _limpar(phone: str) -> str:
    return (
        str(phone or "")
        .strip()
        .replace("@c.us", "")
        .replace("@s.whatsapp.net", "")
        .replace("@g.us", "")
        .replace("@lid", "")
    )


def _parece_lid(valor: str) -> bool:
    """LID é um número longo (14+ dígitos) que não é telefone com DDD/país."""

    return bool(re.fullmatch(r"\d{14,}", valor or ""))


def _redis():
    try:
        import redis  # type: ignore

        from backend.config import REDIS_URL

        return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PhoneCanonical] Redis indisponivel: %s", exc)
        return None


def resolver_lid(lid: str, *, session_name: str = "") -> Optional[str]:
    """LID -> telefone real, via cache Redis e API do WAHA."""

    alvo = str(lid or "").strip()
    if not alvo or "@lid" not in alvo:
        return None

    cache = _redis()
    chave = f"{CACHE_PREFIX}{alvo}"
    if cache is not None:
        try:
            guardado = cache.get(chave)
            if guardado:
                return guardado
        except Exception:  # noqa: BLE001
            pass

    try:
        from backend.config import WAHA_API_KEY, WAHA_BASE_URL
        from backend.integrations.waha_sdk import get_client

        if not WAHA_API_KEY:
            return None
        cliente = get_client(base_url=WAHA_BASE_URL, api_key=WAHA_API_KEY)
        telefone = cliente.get_phone_by_lid(session_name or "default", alvo)
        if telefone and cache is not None:
            try:
                cache.setex(chave, CACHE_TTL_SECONDS, telefone)
            except Exception:  # noqa: BLE001
                pass
        return telefone
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PhoneCanonical] falha ao resolver %s: %s", alvo, exc)
        return None


def canonical_phone_for_storage(db: Session, company_id: int, phone: str) -> str:
    """Devolve o telefone do contato para gravar a mensagem (nunca o ID oculto)."""

    bruto = str(phone or "").strip()
    if not bruto:
        return ""
    limpo = _limpar(bruto)
    if not limpo:
        return bruto

    session_name = ""
    try:
        linha = db.execute(
            text("SELECT waha_session_name FROM companies WHERE id = :c"), {"c": company_id}
        ).fetchone()
        session_name = str(linha[0] or "") if linha else ""
    except Exception:  # noqa: BLE001
        session_name = ""

    try:
        contato = db.execute(
            text(
                """
                SELECT phone FROM contacts
                WHERE company_id = :company_id
                  AND (
                    phone = :bruto OR phone = :limpo
                    OR sender_lid = :bruto OR sender_lid = :lid_com_sufixo
                    OR sender_lid = :limpo
                  )
                ORDER BY last_message_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            ),
            {
                "company_id": company_id,
                "bruto": bruto,
                "limpo": limpo,
                "lid_com_sufixo": f"{limpo}@lid",
            },
        ).fetchone()
        if contato and getattr(contato, "phone", None):
            canonico = str(contato.phone).strip()
            if canonico and canonico != bruto:
                logger.info(
                    "[PhoneCanonical] %s -> %s (contato)", bruto, canonico
                )
            return canonico
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PhoneCanonical] consulta de contato falhou: %s", exc)

    if _parece_lid(limpo) or "@lid" in bruto:
        telefone = resolver_lid(f"{limpo}@lid", session_name=session_name)
        if telefone:
            logger.info("[PhoneCanonical] %s -> %s (WAHA)", bruto, telefone)
            return telefone
        logger.warning("[PhoneCanonical] LID %s sem mapeamento; gravando como veio", bruto)

    return limpo
