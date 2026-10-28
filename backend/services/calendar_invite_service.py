"""Envio do convite de agenda (.ics) por e-mail.

Modulo separado de proposito: `transactional_email_service` ja envia os e-mails
de senha em producao, e eu nao quero arriscar esse caminho para adicionar
anexo. Aqui vive so o convite.

Tres diferencas em relacao ao envio transacional existente:

  1. SSL implicito (porta 465). O Titan usa 465 com TLS desde o primeiro byte,
     e `smtplib.SMTP` + starttls nao funciona nessa porta. Detecto pela porta
     ou por SMTP_USE_SSL.

  2. Anexo .ics. `EmailMessage.add_attachment` com maintype="text" e
     subtype="calendar" — e esse par que faz o cliente de e-mail reconhecer o
     arquivo como convite e oferecer "adicionar a agenda", em vez de mostrar
     como texto anexado.

  3. Varios destinatarios. O convite vai para o paciente E para o profissional,
     cada um vendo o outro como participante. Por isso o To: leva todos.

Se o SMTP nao estiver configurado, a funcao devolve skipped=True em vez de
levantar excecao: agendamento nao pode falhar porque o e-mail caiu. O chamador
decide o que fazer — tipicamente avisar por WhatsApp, que e o fallback decidido
em 28/10 para paciente sem e-mail.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional, Sequence

from backend.services.ics_service import EventoConvite, gerar_ics, nome_arquivo

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 20


@dataclass
class ResultadoConvite:
    enviado: bool
    destinatarios: list[str]
    message_id: Optional[str] = None
    pulado: bool = False
    motivo: Optional[str] = None


def _limpar(valor: Optional[str]) -> str:
    return (valor or "").strip()


def _config_smtp() -> Optional[dict]:
    host = _limpar(os.getenv("SMTP_HOST"))
    remetente = _limpar(os.getenv("SMTP_FROM_EMAIL"))
    if not host or not remetente:
        return None

    try:
        porta = int(_limpar(os.getenv("SMTP_PORT")) or "465")
    except ValueError:
        porta = 465

    # 465 e SSL implicito por convencao; 587 e STARTTLS. SMTP_USE_SSL sobrepoe.
    bruto = _limpar(os.getenv("SMTP_USE_SSL")).casefold()
    if bruto in ("1", "true", "yes", "on"):
        usar_ssl = True
    elif bruto in ("0", "false", "no", "off"):
        usar_ssl = False
    else:
        usar_ssl = porta == 465

    return {
        "host": host,
        "porta": porta,
        "usuario": _limpar(os.getenv("SMTP_USERNAME")) or None,
        "senha": _limpar(os.getenv("SMTP_PASSWORD")) or None,
        "remetente": remetente,
        "nome_remetente": _limpar(os.getenv("SMTP_FROM_NAME")) or "Transformativa",
        "usar_ssl": usar_ssl,
    }


def _corpo_texto(evento: EventoConvite, organizador: str) -> str:
    inicio = evento.inicio.strftime("%d/%m/%Y às %H:%M")
    linhas = [
        "Olá!",
        "",
        f"Segue o convite para {evento.resumo}.",
        "",
        f"Quando: {inicio}",
    ]
    if evento.local:
        linhas.append(f"Onde: {evento.local}")
    if evento.descricao:
        linhas += ["", evento.descricao]
    linhas += [
        "",
        "O convite está anexado (.ics). Abra o arquivo para adicionar à sua agenda;",
        "o horário está em UTC, então cada cliente mostra no fuso correto.",
        "",
        f"Organizado por: {organizador}",
    ]
    return "\n".join(linhas)


def enviar_convite(
    evento: EventoConvite,
    destinatarios: Optional[Sequence[str]] = None,
) -> ResultadoConvite:
    """Gera o .ics e envia por e-mail para os destinatarios informados.

    destinatarios=None usa os participantes do proprio evento.
    """
    config = _config_smtp()
    if not config:
        logger.info("Convite ignorado: SMTP nao configurado")
        return ResultadoConvite(
            enviado=False, destinatarios=[], pulado=True, motivo="smtp_nao_configurado"
        )

    emails = [e.strip() for e in (destinatarios or []) if e and e.strip()]
    if not emails:
        emails = [p.email for p in evento.participantes if p.email]
    if not emails:
        return ResultadoConvite(
            enviado=False, destinatarios=[], pulado=True, motivo="sem_destinatario"
        )

    ics = gerar_ics(evento)
    arquivo = nome_arquivo(evento)
    acao = "cancelado" if evento.cancelado else "confirmado"
    assunto = f"{'Cancelado: ' if evento.cancelado else ''}{evento.resumo}"

    organizador = next(
        (p for p in evento.participantes if p.organizador), evento.participantes[0]
    )
    organizador_txt = organizador.nome or organizador.email

    mensagem = EmailMessage()
    message_id = make_msgid(domain=config["remetente"].split("@")[-1])
    mensagem["Message-ID"] = message_id
    mensagem["Subject"] = assunto
    mensagem["From"] = formataddr((config["nome_remetente"], config["remetente"]))
    mensagem["To"] = ", ".join(emails)
    mensagem.set_content(_corpo_texto(evento, organizador_txt))

    # subtype="calendar" + method e o que faz o cliente tratar como convite
    mensagem.add_attachment(
        ics.encode("utf-8"),
        maintype="text",
        subtype="calendar",
        filename=arquivo,
        params={"method": "CANCEL" if evento.cancelado else "REQUEST"},
    )

    try:
        contexto = ssl.create_default_context()
        if config["usar_ssl"]:
            conexao = smtplib.SMTP_SSL(
                config["host"], config["porta"], timeout=TIMEOUT_SEGUNDOS, context=contexto
            )
        else:
            conexao = smtplib.SMTP(
                config["host"], config["porta"], timeout=TIMEOUT_SEGUNDOS
            )

        with conexao as smtp:
            if not config["usar_ssl"]:
                smtp.ehlo()
                smtp.starttls(context=contexto)
                smtp.ehlo()
            if config["usuario"] and config["senha"]:
                smtp.login(config["usuario"], config["senha"])
            smtp.send_message(mensagem)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning(
            "Falha ao enviar convite erro=%s destinatarios=%d",
            exc.__class__.__name__,
            len(emails),
        )
        return ResultadoConvite(
            enviado=False,
            destinatarios=emails,
            motivo="falha_no_envio",
        )

    logger.info("Convite %s enviado para %d destinatario(s)", acao, len(emails))
    return ResultadoConvite(
        enviado=True, destinatarios=emails, message_id=message_id
    )
