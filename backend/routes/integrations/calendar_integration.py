# backend/routes/integrations/calendar_integration.py
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.auth import ALGORITHM, SECRET_KEY, ensure_user_can_access_company, get_current_user
from backend.db import get_db
from backend.models import Agenda, CalendarIntegration, Company, Professional
from backend.services.papel_clinico import _papel_do_usuario
from backend.routes.integrations.google_calendar_service import (
    GOOGLE_OAUTH_SCOPES,
    build_google_oauth_service,
)
from backend.routes.company import is_internal_admin, require_internal_admin
from backend.services.google_oauth_settings import (
    credenciais_google_oauth,
    google_oauth_configurado,
    remover_credenciais_google_oauth,
    salvar_credenciais_google_oauth,
)
from backend.runtime_settings import PUBLIC_APP_URL, PUBLIC_BASE_URL


def require_calendar_company_access(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    ensure_user_can_access_company(user, company_id, db)
    return user


def require_google_agenda_company_access(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # Admin da plataforma atende profissionais de qualquer empresa.
    if is_internal_admin(user):
        return user
    ensure_user_can_access_company(user, company_id, db)
    return user


logger = logging.getLogger(__name__)

router = APIRouter()


class GoogleCalendarConfig(BaseModel):
    google_calendar_id: Optional[str] = None


class GoogleCalendarCreatePayload(BaseModel):
    summary: str
    time_zone: Optional[str] = None


class GoogleCalendarLinkPayload(BaseModel):
    google_calendar_id: str


class ClinicorpConfig(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    code_link: Optional[str] = None
    subscriber_id: Optional[str] = None


def _clean_url(raw_value: Optional[str]) -> str:
    return (raw_value or "").strip().rstrip("/")


def _is_local_url(url: str) -> bool:
    return any(h in url for h in ("localhost", "127.0.0.1", "0.0.0.0"))


def _request_origin(request: Optional[Request]) -> str:
    """Origem pública (https://dominio) pela qual a pessoa acessa a plataforma."""
    if request is None:
        return ""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if not host:
        return ""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    return f"{proto}://{host}"


def _public_app_origin(request: Optional[Request] = None) -> str:
    configured = _clean_url(os.getenv("GOOGLE_OAUTH_FRONTEND_REDIRECT_ORIGIN"))
    if configured:
        return configured

    frontend_url = _clean_url(os.getenv("FRONTEND_URL"))
    if frontend_url and "localhost" not in frontend_url and "127.0.0.1" not in frontend_url:
        return frontend_url

    # PUBLIC_APP_URL local em producao gera redirect para 127.0.0.1: usa o dominio da requisicao.
    origem_requisicao = _request_origin(request)
    if origem_requisicao and _is_local_url(PUBLIC_APP_URL):
        return origem_requisicao

    return PUBLIC_APP_URL


def _oauth_redirect_uri(request: Optional[Request] = None) -> str:
    configured = _clean_url(os.getenv("GOOGLE_OAUTH_REDIRECT_URI"))
    if configured and not (_is_local_url(configured) and _request_origin(request) and not _is_local_url(_request_origin(request))):
        return configured

    origem_requisicao = _request_origin(request)
    if origem_requisicao and _is_local_url(PUBLIC_BASE_URL):
        return f"{origem_requisicao}/api/integrations/calendar/google/oauth/callback"

    return f"{PUBLIC_BASE_URL}/api/integrations/calendar/google/oauth/callback"


def _oauth_client_config(db: Optional[Session] = None, redirect_uri: Optional[str] = None) -> dict:
    client_id, client_secret, _ = credenciais_google_oauth(db)
    redirect_uri = redirect_uri or _oauth_redirect_uri()

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="OAuth do Google não configurado. O Admin da plataforma deve informar o Client ID e o Client Secret na tela Agenda → Integrações.",
        )

    if redirect_uri.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _new_oauth_flow(db: Optional[Session] = None, redirect_uri: Optional[str] = None) -> Flow:
    redirect_uri = redirect_uri or _oauth_redirect_uri()
    return Flow.from_client_config(
        _oauth_client_config(db, redirect_uri),
        scopes=GOOGLE_OAUTH_SCOPES,
        redirect_uri=redirect_uri,
    )


def _make_state(
    company_id: int,
    user_id: Optional[int],
    agenda_id: Optional[int] = None,
    return_to: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    origin: Optional[str] = None,
) -> str:
    """State assinado do OAuth. `agenda_id` marca autorizacao POR AGENDA (F1-06).

    Sem `agenda_id` o token vai para a empresa (comportamento antigo, preservado);
    com ele, o callback grava na agenda — e a empresa continua com o token dela,
    porque as outras agendas dependem disso.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "company_id": company_id,
        "user_id": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "type": "google_calendar_oauth",
    }
    if agenda_id:
        payload["agenda_id"] = int(agenda_id)
    if return_to:
        payload["return_to"] = return_to
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri
    if origin:
        payload["origin"] = origin
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _read_state(state: str) -> dict:
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido ou expirado.")

    if payload.get("type") != "google_calendar_oauth" or not payload.get("company_id"):
        raise HTTPException(status_code=400, detail="Estado OAuth inválido.")
    return payload


def _get_google_integration(db: Session, company_id: int) -> Optional[CalendarIntegration]:
    return db.query(CalendarIntegration).filter(
        CalendarIntegration.provider == "google",
        CalendarIntegration.company_id == company_id,
    ).first()


def _get_google_integration_or_404(db: Session, company_id: int) -> CalendarIntegration:
    integration = _get_google_integration(db, company_id)
    if not integration or not integration.google_oauth_token:
        raise HTTPException(status_code=404, detail="Google Agenda ainda não conectado para esta empresa.")
    return integration


def _get_company_agenda_or_404(db: Session, company_id: int, agenda_id: int) -> Agenda:
    agenda = db.query(Agenda).filter(
        Agenda.id == agenda_id,
        Agenda.company_id == company_id,
    ).first()
    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda local não encontrada para esta empresa.")
    return agenda


def _ensure_google_agenda_access(user, agenda: Agenda) -> None:
    if is_internal_admin(user):
        return
    role = _papel_do_usuario(user)
    if role == "clinic_admin":
        return
    if (
        role in {"clinical_professional", "service_professional"}
        and getattr(user, "professional_id", None) == agenda.professional_id
    ):
        return
    raise HTTPException(
        status_code=403,
        detail="Somente o Admin da plataforma, o Admin Clínica ou o profissional vinculado pode configurar o Google desta agenda.",
    )


def _calendar_to_response(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "summary": item.get("summary"),
        "description": item.get("description"),
        "primary": bool(item.get("primary")),
        "access_role": item.get("accessRole"),
        "background_color": item.get("backgroundColor"),
        "time_zone": item.get("timeZone"),
    }


def _list_writable_calendars(service) -> list[dict]:
    result = service.calendarList().list(
        minAccessRole="writer",
        showHidden=True,
    ).execute()
    return [
        _calendar_to_response(item)
        for item in result.get("items", [])
        if item.get("accessRole") == "owner"
    ]


def _apply_google_calendar_to_agenda(db: Session, agenda: Agenda, calendar_item: dict) -> dict:
    agenda.google_calendar_id = calendar_item.get("id")
    agenda.google_calendar_summary = calendar_item.get("summary")
    agenda.google_calendar_time_zone = calendar_item.get("timeZone")
    db.add(agenda)
    db.commit()
    db.refresh(agenda)
    return _calendar_to_response(calendar_item)


def _select_calendar(db: Session, integration: CalendarIntegration, calendar_id: str) -> dict:
    normalized_calendar_id = (calendar_id or "").strip()
    if not normalized_calendar_id:
        raise HTTPException(status_code=400, detail="Informe uma agenda para conectar.")

    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    try:
        calendar_list_entry = service.calendarList().get(calendarId=normalized_calendar_id).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Agenda não encontrada na conta Google conectada.")

    access_role = calendar_list_entry.get("accessRole")
    if access_role != "owner":
        raise HTTPException(status_code=403, detail="Escolha uma agenda que pertença à conta Google conectada.")

    integration.google_calendar_id = calendar_list_entry.get("id") or normalized_calendar_id
    integration.google_calendar_summary = calendar_list_entry.get("summary")
    db.add(integration)
    db.commit()

    return _calendar_to_response(calendar_list_entry)


def _link_calendar_to_agenda(
    db: Session,
    integration: Optional[CalendarIntegration],
    agenda: Agenda,
    calendar_id: str,
) -> dict:
    normalized_calendar_id = (calendar_id or "").strip()
    if not normalized_calendar_id:
        raise HTTPException(status_code=400, detail="Informe uma agenda Google para vincular.")

    # Cada calendário deve pertencer à conta OAuth autorizada nesta agenda.
    from backend.services.google_credencial import build_service_da_agenda

    service, _fonte = build_service_da_agenda(db, agenda.company_id, agenda)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    try:
        calendar_list_entry = service.calendarList().get(calendarId=normalized_calendar_id).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Agenda não encontrada na conta Google conectada.")

    access_role = calendar_list_entry.get("accessRole")
    if access_role != "owner":
        raise HTTPException(status_code=403, detail="Escolha uma agenda que pertença à conta Google conectada.")

    return _apply_google_calendar_to_agenda(db, agenda, calendar_list_entry)


def _oauth_success_redirect(
    query: str = "google_oauth=success",
    agenda_id: Optional[int] = None,
    return_to: Optional[str] = None,
    origem: Optional[str] = None,
) -> str:
    """Destino depois do OAuth.

    Com `agenda_id` a pessoa autorizou o Google de UMA agenda: ela tem de voltar
    para a tela de agendas (/calendar-config), na aba de horarios, e nao para a
    tela de integracao da empresa — senao autoriza e nao ve o resultado.
    """
    origem = origem or _public_app_origin()
    if agenda_id and return_to == "integrations":
        return f"{origem}/calendar-config?tab=integrations&{query}&agenda_id={agenda_id}"
    if agenda_id:
        separador = "&" if query else ""
        return f"{origem}/calendar-config?tab=hours&{query}{separador}agenda_id={agenda_id}"
    return f"{origem}/prompt/agenda?{query}"


@router.get("/google/{company_id}")
def get_google_calendar_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = _get_google_integration(db, company_id)
    oauth_configured = google_oauth_configurado(db)

    if not config:
        return {
            "google_calendar_id": None,
            "google_calendar_summary": None,
            "google_account_email": None,
            "google_oauth_connected": False,
            "oauth_configured": oauth_configured,
            "oauth_redirect_uri": _oauth_redirect_uri(),
            "message": "Nenhuma integração Google para essa empresa.",
        }

    return {
        "google_calendar_id": config.google_calendar_id,
        "google_calendar_summary": config.google_calendar_summary,
        "google_account_email": config.google_account_email,
        "google_oauth_connected": bool(config.google_oauth_token),
        "oauth_configured": oauth_configured,
        "oauth_redirect_uri": _oauth_redirect_uri(),
    }


@router.get("/google/{company_id}/oauth/start")
def start_google_calendar_oauth(
    request: Request,
    company_id: int,
    agenda_id: int = Query(
        ...,
        description="Agenda do profissional que receberá a credencial OAuth.",
    ),
    return_to: Optional[str] = Query(None, pattern="^(integrations|calendar)$"),
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    """Inicia o OAuth para a agenda de um profissional."""
    # 404 se a agenda nao for desta empresa: sem isso o state levaria um id
    # de outra clinica e o token seria gravado no lugar errado.
    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    redirect_uri = _oauth_redirect_uri(request)
    flow = _new_oauth_flow(db, redirect_uri)
    state = _make_state(
        company_id, getattr(user, "id", None), agenda_id, return_to,
        redirect_uri=redirect_uri, origin=_public_app_origin(request),
    )
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return {"authorization_url": authorization_url}


@router.get("/google/oauth/callback")
def google_calendar_oauth_callback(
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # O state ja diz de qual agenda se trata: sem isso o erro volta sem dizer
    # QUAL agenda falhou e a tela nao consegue ser especifica.
    payload = _read_state(state) if state else None
    agenda_do_state = payload.get("agenda_id") if payload else None
    retorno = payload.get("return_to") if payload else None
    origem_state = payload.get("origin") if payload else None

    if error:
        return RedirectResponse(
            _oauth_success_redirect(f"google_oauth=error&reason={error}", agenda_do_state, retorno, origem_state)
        )

    if not code:
        raise HTTPException(status_code=400, detail="Código OAuth ausente.")

    company_id = int(payload["company_id"])

    flow = _new_oauth_flow(db, payload.get("redirect_uri"))
    try:
        flow.fetch_token(code=code)
    except Exception:
        return RedirectResponse(
            _oauth_success_redirect("google_oauth=error&reason=token", agenda_do_state, retorno, origem_state)
        )

    credentials = flow.credentials
    service = build_google_oauth_service(
        type("TemporaryIntegration", (), {"google_oauth_token": json.loads(credentials.to_json())})()
    )
    if not service:
        return RedirectResponse(
            _oauth_success_redirect("google_oauth=error&reason=service", agenda_do_state, retorno, origem_state)
        )

    try:
        calendars = _list_writable_calendars(service)
    except Exception as exc:  # noqa: BLE001 - erro do Google vira aviso na tela, não 500
        motivo = "api_disabled" if "accessNotConfigured" in str(exc) or "has not been used" in str(exc) else "calendars"
        logger.warning("OAuth Google: falha ao listar calendários (%s): %s", motivo, exc)
        return RedirectResponse(
            _oauth_success_redirect(f"google_oauth=error&reason={motivo}", agenda_do_state, retorno, origem_state)
        )
    primary_calendar = next((item for item in calendars if item.get("primary")), None)
    token_json = json.loads(credentials.to_json())
    escopos = " ".join(credentials.scopes or GOOGLE_OAUTH_SCOPES)
    conta = primary_calendar.get("id") if primary_calendar else None

    agenda_id = payload.get("agenda_id")
    if agenda_id:
        # F1-06: credencial POR AGENDA. A empresa nao e tocada — as outras agendas
        # continuam usando (ou nao) a credencial dela.
        agenda = _get_company_agenda_or_404(db, company_id, int(agenda_id))
        agenda.google_oauth_token = token_json
        agenda.google_oauth_scopes = escopos
        agenda.google_account_email = conta
        if primary_calendar and not agenda.google_calendar_id:
            agenda.google_calendar_id = primary_calendar.get("id")
            agenda.google_calendar_summary = primary_calendar.get("summary")
            agenda.google_calendar_time_zone = primary_calendar.get("timeZone")
        db.add(agenda)
        db.commit()
        return RedirectResponse(
            _oauth_success_redirect("google_oauth=success", agenda.id, retorno, origem_state)
        )

    config = _get_google_integration(db, company_id)
    if not config:
        config = CalendarIntegration(provider="google", company_id=company_id)
        db.add(config)

    config.google_oauth_token = token_json
    config.google_oauth_scopes = escopos
    config.google_account_email = conta

    db.commit()
    return RedirectResponse(_oauth_success_redirect(origem=origem_state))


@router.get("/google/{company_id}/calendars")
def list_google_calendars(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")
    return {"calendars": _list_writable_calendars(service)}


@router.post("/google/{company_id}/calendar/select")
def select_google_calendar(
    company_id: int,
    data: GoogleCalendarConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    calendar = _select_calendar(db, integration, data.google_calendar_id or "")
    return {"status": "success", "message": "Agenda Google selecionada.", "calendar": calendar}


@router.post("/google/{company_id}/agendas/{agenda_id}/link")
def link_google_calendar_to_agenda(
    company_id: int,
    agenda_id: int,
    data: GoogleCalendarLinkPayload,
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    calendar = _link_calendar_to_agenda(db, None, agenda, data.google_calendar_id)
    return {
        "status": "success",
        "message": "Agenda local vinculada ao Google Agenda.",
        "calendar": calendar,
        "agenda_id": agenda.id,
    }


@router.delete("/google/{company_id}/agendas/{agenda_id}/link")
def unlink_google_calendar_from_agenda(
    company_id: int,
    agenda_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    # Desvincular e limpar colunas: nao depende de credencial nenhuma. Exigir a
    # da empresa impedia desvincular quando so a agenda tinha Google conectado.
    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    agenda.google_calendar_id = None
    agenda.google_calendar_summary = None
    agenda.google_calendar_time_zone = None
    db.add(agenda)
    db.commit()
    return {
        "status": "success",
        "message": "Agenda Google desvinculada da agenda local.",
        "agenda_id": agenda.id,
    }


@router.post("/google/{company_id}/agendas/{agenda_id}/calendars")
def create_google_calendar_for_agenda(
    company_id: int,
    agenda_id: int,
    data: GoogleCalendarCreatePayload,
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    from backend.services.google_credencial import build_service_da_agenda

    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    service, _fonte = build_service_da_agenda(db, company_id, agenda)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    summary = (data.summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Informe um nome para a nova agenda.")

    body = {"summary": summary}
    if data.time_zone:
        body["timeZone"] = data.time_zone

    try:
        created = service.calendars().insert(body=body).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Não foi possível criar a agenda na conta Google conectada.")

    calendar = _apply_google_calendar_to_agenda(db, agenda, created)
    return {
        "status": "success",
        "message": "Agenda Google criada e vinculada à agenda local.",
        "calendar": calendar,
        "agenda_id": agenda.id,
    }


@router.post("/google/{company_id}/calendars")
def create_google_calendar(
    company_id: int,
    data: GoogleCalendarCreatePayload,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    summary = (data.summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Informe um nome para a nova agenda.")

    body = {"summary": summary}
    if data.time_zone:
        body["timeZone"] = data.time_zone

    try:
        created = service.calendars().insert(body=body).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Não foi possível criar a agenda na conta Google conectada.")

    integration.google_calendar_id = created.get("id")
    integration.google_calendar_summary = created.get("summary")
    db.add(integration)
    db.commit()

    return {
        "status": "success",
        "message": "Agenda Google criada e selecionada.",
        "calendar": _calendar_to_response(created),
    }


@router.post("/google/{company_id}")
def create_google_calendar_config(
    company_id: int,
    data: GoogleCalendarConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    calendar = _select_calendar(db, integration, data.google_calendar_id or "")
    return {"status": "success", "message": "Agenda Google selecionada.", "calendar": calendar}


@router.put("/google/{company_id}")
def update_google_calendar_config(
    company_id: int,
    data: GoogleCalendarConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    calendar = _select_calendar(db, integration, data.google_calendar_id or "")
    return {"status": "success", "message": "Agenda Google selecionada.", "calendar": calendar}


@router.delete("/google/{company_id}")
def delete_google_calendar_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = _get_google_integration(db, company_id)
    if not config:
        raise HTTPException(status_code=404, detail="Integração Google não encontrada para essa empresa.")

    db.query(Agenda).filter(Agenda.company_id == company_id).update({
        Agenda.google_calendar_id: None,
        Agenda.google_calendar_summary: None,
        Agenda.google_calendar_time_zone: None,
    }, synchronize_session=False)
    db.delete(config)
    db.commit()
    return {"status": "success", "message": "Integração Google removida com sucesso."}


@router.get("/clinicorp/{company_id}")
def get_clinicorp_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).options(
        joinedload(CalendarIntegration.clinicorp_details)
    ).filter(
        CalendarIntegration.provider == "clinicorp",
        CalendarIntegration.company_id == company_id
    ).first()

    if not config:
        return {
            "username": None,
            "password": None,
            "code_link": None,
            "subscriber_id": None,
            "business_id": None,
            "dentist_person_id": None,
            "message": "Nenhuma integração Clinicorp para essa empresa."
        }

    details = config.clinicorp_details
    return {
        "username": config.clinicorp_username,
        "code_link": config.clinicorp_code_link,
        "subscriber_id": config.clinicorp_subscriber_id,
        "business_id": details.business_id if details else None,
        "dentist_person_id": details.dentist_person_id if details else None,
    }


@router.post("/clinicorp/{company_id}")
def create_clinicorp_config(
    company_id: int,
    data: ClinicorpConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).filter_by(
        provider="clinicorp",
        company_id=company_id
    ).first()

    if config:
        config.clinicorp_username = data.username
        config.clinicorp_password = data.password
        config.clinicorp_code_link = data.code_link
        config.clinicorp_subscriber_id = data.subscriber_id
    else:
        config = CalendarIntegration(
            provider="clinicorp",
            company_id=company_id,
            clinicorp_username=data.username,
            clinicorp_password=data.password,
            clinicorp_code_link=data.code_link,
            clinicorp_subscriber_id=data.subscriber_id
        )
        db.add(config)

    db.commit()
    return {"status": "success", "message": "Integração Clinicorp (POST) criada ou sobrescrita."}


@router.put("/clinicorp/{company_id}")
def update_clinicorp_config(
    company_id: int,
    data: ClinicorpConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).filter_by(
        provider="clinicorp",
        company_id=company_id
    ).first()

    if not config:
        config = CalendarIntegration(
            provider="clinicorp",
            company_id=company_id,
            clinicorp_username=data.username,
            clinicorp_password=data.password,
            clinicorp_code_link=data.code_link,
            clinicorp_subscriber_id=data.subscriber_id
        )
        db.add(config)
    else:
        config.clinicorp_username = data.username
        config.clinicorp_password = data.password
        config.clinicorp_code_link = data.code_link
        config.clinicorp_subscriber_id = data.subscriber_id

    db.commit()
    return {"status": "success", "message": "Integração Clinicorp (PUT) atualizada ou criada."}


@router.delete("/clinicorp/{company_id}")
def delete_clinicorp_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).filter_by(
        provider="clinicorp",
        company_id=company_id
    ).first()

    if not config:
        raise HTTPException(status_code=404, detail="Integração Clinicorp não encontrada para essa empresa.")

    db.delete(config)
    db.commit()
    return {"status": "success", "message": "Integração Clinicorp removida com sucesso."}


# ---------------------------------------------------------------------------
# Credencial Google POR AGENDA (F1-06)
#
# Os endpoints acima sao por EMPRESA. Estes sao por AGENDA: cada profissional
# autoriza a propria conta Google, sem herdar a credencial da clinica.
# ---------------------------------------------------------------------------

@router.get("/google/{company_id}/agendas/{agenda_id}/status")
def get_agenda_google_status(
    company_id: int,
    agenda_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    from backend.services.google_credencial import credencial_google_da_agenda

    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    dono, fonte = credencial_google_da_agenda(db, company_id, agenda)
    return {
        "agenda_id": agenda.id,
        "agenda_nome": agenda.name,
        "fonte_credencial": fonte,  # "agenda" | None
        "credencial_propria": fonte == "agenda",
        "google_connected": dono is not None,
        "google_account_email": getattr(dono, "google_account_email", None) if dono else None,
        "google_calendar_id": agenda.google_calendar_id,
        "google_calendar_summary": agenda.google_calendar_summary,
        "oauth_configured": google_oauth_configurado(db),
    }


@router.get("/google/{company_id}/agendas/{agenda_id}/calendars")
def list_agenda_google_calendars(
    company_id: int,
    agenda_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    """Calendarios que a credencial DESTA agenda enxerga."""
    from backend.services.google_credencial import build_service_da_agenda

    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    service, fonte = build_service_da_agenda(db, company_id, agenda)
    if not service:
        raise HTTPException(
            status_code=404,
            detail="Esta agenda não tem Google conectado. Conecte o Google desta agenda primeiro.",
        )
    return {"fonte_credencial": fonte, "calendars": _list_writable_calendars(service)}


@router.post("/google/{company_id}/agendas/{agenda_id}/calendar")
def set_agenda_google_calendar(
    company_id: int,
    agenda_id: int,
    data: GoogleCalendarConfig,
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    """Escolhe o calendario da agenda usando a credencial dela."""
    from backend.services.google_credencial import build_service_da_agenda

    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    service, _fonte = build_service_da_agenda(db, company_id, agenda)
    if not service:
        raise HTTPException(status_code=404, detail="Esta agenda não tem Google conectado.")

    calendar_id = (data.google_calendar_id or "").strip()
    if not calendar_id:
        raise HTTPException(status_code=400, detail="Informe uma agenda para conectar.")

    try:
        entrada = service.calendarList().get(calendarId=calendar_id).execute()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Agenda não encontrada na conta Google conectada a esta agenda.",
        )
    if entrada.get("accessRole") != "owner":
        raise HTTPException(
            status_code=403,
            detail="A conta conectada só tem acesso de leitura a este calendário. Conecte uma conta que seja dona dele.",
        )

    return {
        "status": "success",
        "calendar": _apply_google_calendar_to_agenda(db, agenda, entrada),
    }


@router.delete("/google/{company_id}/agendas/{agenda_id}/credential")
def delete_agenda_google_credential(
    company_id: int,
    agenda_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    """Remove a credencial Google própria desta agenda."""
    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    _ensure_google_agenda_access(user, agenda)
    tinha = bool(agenda.google_oauth_token)
    agenda.google_oauth_token = None
    agenda.google_oauth_scopes = None
    agenda.google_account_email = None
    db.add(agenda)
    db.commit()
    return {
        "status": "success",
        "removed": tinha,
        "message": (
            "Credencial Google removida desta agenda."
            if tinha
            else "Esta agenda já não tinha credencial própria."
        ),
    }


@router.get("/google-agendas/profissionais")
def list_google_agenda_professionals(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Profissionais cujo Google o usuário pode configurar.

    Admin da plataforma: todos, de todas as empresas. Admin Clínica: os da sua
    empresa. Profissional: somente o próprio.
    """
    query = (
        db.query(Professional, Company)
        .join(Company, Company.id == Professional.company_id)
        .filter(Professional.active.is_(True))
    )
    if is_internal_admin(user):
        pass
    else:
        role = _papel_do_usuario(user)
        if role == "clinic_admin":
            query = query.filter(Professional.company_id == getattr(user, "company_id", None))
        elif role in {"clinical_professional", "service_professional"} and getattr(user, "professional_id", None):
            query = query.filter(Professional.id == user.professional_id)
        else:
            raise HTTPException(status_code=403, detail="Sem permissão para configurar o Google Agenda.")

    rows = query.order_by(Company.name, Professional.name).all()
    ids = [prof.id for prof, _ in rows]
    agendas = {}
    if ids:
        for agenda in db.query(Agenda).filter(Agenda.professional_id.in_(ids), Agenda.active.is_(True)).all():
            agendas[agenda.professional_id] = agenda

    result = []
    for prof, company in rows:
        agenda = agendas.get(prof.id)
        result.append({
            "professional_id": prof.id,
            "professional_name": prof.name,
            "company_id": company.id,
            "company_name": company.name_company or company.name,
            "agenda_id": agenda.id if agenda else None,
            "agenda_name": agenda.name if agenda else None,
            "google_connected": bool(agenda and agenda.google_oauth_token),
            "google_account_email": agenda.google_account_email if agenda else None,
            "google_calendar_summary": agenda.google_calendar_summary if agenda else None,
        })
    return {"items": result}


class GoogleOAuthAppPayload(BaseModel):
    client_id: str
    client_secret: str


def _google_oauth_app_status(db: Session, user, request: Optional[Request] = None) -> dict:
    client_id, _, fonte = credenciais_google_oauth(db)
    return {
        "configured": bool(fonte),
        "source": fonte or None,
        "client_id": client_id or None,
        "redirect_uri": _oauth_redirect_uri(request),
        "can_configure": is_internal_admin(user),
    }


@router.get("/google-oauth/app")
def get_google_oauth_app(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Estado das credenciais do app Google. O Client Secret nunca é devolvido."""
    return _google_oauth_app_status(db, user, request)


@router.put("/google-oauth/app")
def save_google_oauth_app(
    request: Request,
    data: GoogleOAuthAppPayload,
    db: Session = Depends(get_db),
    user=Depends(require_internal_admin),
):
    if not data.client_id.strip() or not data.client_secret.strip():
        raise HTTPException(status_code=422, detail="Informe o Client ID e o Client Secret.")
    salvar_credenciais_google_oauth(
        db, data.client_id, data.client_secret, getattr(user, "email", "") or ""
    )
    return _google_oauth_app_status(db, user, request)


@router.delete("/google-oauth/app")
def delete_google_oauth_app(request: Request, db: Session = Depends(get_db), user=Depends(require_internal_admin)):
    remover_credenciais_google_oauth(db)
    return _google_oauth_app_status(db, user, request)


@router.get("/google/{company_id}/agendas/{agenda_id}/events")
def list_agenda_google_events(
    company_id: int,
    agenda_id: int,
    start: datetime = Query(..., description="Início do período (ISO 8601)."),
    end: datetime = Query(..., description="Fim do período (ISO 8601)."),
    db: Session = Depends(get_db),
    user=Depends(require_google_agenda_company_access),
):
    """Compromissos do Google Agenda do profissional, para a agenda exibir e bloquear horários."""
    from backend.routes.integrations.google_calendar_service import list_calendar_events
    from backend.services.google_credencial import build_service_da_agenda

    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    if not agenda.google_oauth_token or not agenda.google_calendar_id:
        return {"connected": False, "events": [], "error": None}
    if end - start > timedelta(days=45):
        raise HTTPException(status_code=422, detail="Período máximo de 45 dias.")

    service, _fonte = build_service_da_agenda(db, company_id, agenda)
    if not service:
        return {"connected": True, "events": [], "error": "Google Agenda precisa ser reconectado."}

    def _iso(valor: datetime) -> str:
        return (valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)).isoformat()

    eventos = list_calendar_events(
        agenda.google_calendar_id,
        _iso(start),
        _iso(end),
        service=service,
        time_zone=agenda.timezone,
    )
    if eventos is None:
        return {"connected": True, "events": [], "error": "Não foi possível ler os compromissos do Google."}
    return {"connected": True, "events": eventos, "error": None}
