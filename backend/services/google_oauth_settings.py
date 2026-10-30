"""Credenciais do aplicativo OAuth do Google (Client ID / Client Secret).

O Admin da plataforma cadastra pela tela; o valor fica criptografado em
`platform_settings`. As variáveis de ambiente continuam valendo como fallback.
"""
import json
import os
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from backend.models import PlatformSetting
from backend.services.ai_provider_service import _fernet

CHAVE = "google_oauth_app"


def _ler_do_banco(db: Optional[Session]) -> Tuple[str, str]:
    if db is None:
        return "", ""
    try:
        linha = db.query(PlatformSetting).filter(PlatformSetting.key == CHAVE).first()
    except Exception:  # tabela ainda não migrada: cai para as variáveis de ambiente
        db.rollback()
        return "", ""
    if not linha:
        return "", ""
    try:
        dados = json.loads(_fernet().decrypt(linha.value_encrypted.encode("utf-8")).decode("utf-8"))
    except Exception:  # chave Fernet trocada ou valor corrompido: trata como não configurado
        return "", ""
    return (dados.get("client_id") or "").strip(), (dados.get("client_secret") or "").strip()


def credenciais_google_oauth(db: Optional[Session]) -> Tuple[str, str, str]:
    """(client_id, client_secret, fonte) com fonte em 'plataforma' | 'ambiente' | ''."""
    client_id, client_secret = _ler_do_banco(db)
    if client_id and client_secret:
        return client_id, client_secret, "plataforma"
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret, "ambiente"
    return "", "", ""


def google_oauth_configurado(db: Optional[Session]) -> bool:
    return bool(credenciais_google_oauth(db)[2])


def salvar_credenciais_google_oauth(db: Session, client_id: str, client_secret: str, atualizado_por: str) -> None:
    valor = _fernet().encrypt(
        json.dumps({"client_id": client_id.strip(), "client_secret": client_secret.strip()}).encode("utf-8")
    ).decode("utf-8")
    linha = db.query(PlatformSetting).filter(PlatformSetting.key == CHAVE).first()
    if linha:
        linha.value_encrypted = valor
        linha.updated_by = atualizado_por
    else:
        db.add(PlatformSetting(key=CHAVE, value_encrypted=valor, updated_by=atualizado_por))
    db.commit()


def remover_credenciais_google_oauth(db: Session) -> bool:
    removidas = db.query(PlatformSetting).filter(PlatformSetting.key == CHAVE).delete()
    db.commit()
    return bool(removidas)
