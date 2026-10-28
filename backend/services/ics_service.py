"""Gerador de convite iCalendar (RFC 5545) sem dependencia externa.

Por que existe: o convite de agenda nao pode depender do Google. O e-mail do
profissional nem sempre e Gmail — pode ser Outlook, iCloud, corporativo — e o
cliente de e-mail de qualquer um deles entende um anexo .ics. Gerar o arquivo
aqui e mandar por SMTP resolve o convite para qualquer profissional, sem exigir
que ninguem autorize OAuth.

Decisoes de implementacao:

  UTC sempre (sufixo Z) em vez de VTIMEZONE.
    VTIMEZONE exige descrever as regras de horario de verao do fuso, e errar
    isso faz o convite aparecer na hora errada em alguns clientes. Convertendo
    para UTC o problema desaparece: todo cliente sabe ler UTC.

  Dobra de linha em 75 octetos.
    A RFC 5545 exige. Clientes rigorosos (Outlook) truncam linha longa se ela
    nao for dobrada.

  Escape de \\ ; , e quebra de linha nos campos de texto.
    Uma virgula no nome do paciente quebra o parse se nao for escapada.

  UID estavel por agendamento.
    E o UID que faz o cliente entender que uma atualizacao e o MESMO evento, e
    nao um evento novo. Por isso ele e derivado do id do agendamento.

  SEQUENCE crescente.
    Sem ele o cliente ignora a atualizacao — RFC 5545 secao 3.8.7.4.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

PRODID = "-//Transformativa//Plataforma Agentes IA//PT-BR"
FUSO_PADRAO = "America/Sao_Paulo"
LIMITE_OCTETOS = 75


# --------------------------------------------------------------------- escape

def escapar(texto: Optional[str]) -> str:
    """Escapa um valor de texto conforme RFC 5545 secao 3.3.11."""
    if texto is None:
        return ""
    s = str(texto)
    s = s.replace("\\", "\\\\")
    s = s.replace(";", "\\;")
    s = s.replace(",", "\\,")
    s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return s


def _dobrar(linha: str) -> str:
    """Dobra a linha em 75 octetos (RFC 5545 secao 3.1), sem cortar UTF-8.

    A primeira linha pode ter 75 octetos. As continuacoes podem ter 74, porque o
    espaco inicial da continuacao conta como um octeto — foi exatamente esse
    off-by-one que gerou linha de 76 e faria cliente rigoroso truncar.
    """
    if len(linha.encode("utf-8")) <= LIMITE_OCTETOS:
        return linha

    pedacos: list[str] = []
    atual = ""
    limite = LIMITE_OCTETOS
    for caractere in linha:
        if len((atual + caractere).encode("utf-8")) > limite:
            pedacos.append(atual)
            atual = caractere
            limite = LIMITE_OCTETOS - 1  # o espaco da continuacao ocupa 1
        else:
            atual += caractere
    if atual:
        pedacos.append(atual)

    return pedacos[0] + "".join("\r\n " + p for p in pedacos[1:])


def _para_utc(momento: datetime) -> datetime:
    """Normaliza para UTC. Datetime ingenuo e assumido como UTC."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


def _formato(momento: datetime) -> str:
    return _para_utc(momento).strftime("%Y%m%dT%H%M%SZ")


def _uid_estavel(agendamento_id: object, dominio: str = "transformativa.com.br") -> str:
    """UID derivado do agendamento: mesmo id -> mesmo UID -> atualizacao, nao duplicata."""
    return f"agendamento-{agendamento_id}@{dominio}"


# ------------------------------------------------------------------- estrutura

@dataclass
class Participante:
    email: str
    nome: Optional[str] = None
    organizador: bool = False
    opcional: bool = False


@dataclass
class EventoConvite:
    agendamento_id: object
    inicio: datetime
    fim: datetime
    resumo: str
    participantes: list[Participante] = field(default_factory=list)
    descricao: Optional[str] = None
    local: Optional[str] = None
    sequencia: int = 0
    cancelado: bool = False
    dominio_uid: str = "transformativa.com.br"


# --------------------------------------------------------------------- gerador

def gerar_ics(evento: EventoConvite) -> str:
    """Gera o texto .ics completo de um convite.

    METHOD REQUEST para criar/atualizar, CANCEL para cancelar. STATUS segue o
    mesmo criterio. O cancelamento preserva o UID e sobe o SEQUENCE, que e como
    os clientes sabem remover o evento da agenda em vez de ignorar.
    """
    if not evento.participantes:
        raise ValueError("convite sem participante nao faz sentido")

    organizador = next(
        (p for p in evento.participantes if p.organizador),
        evento.participantes[0],
    )
    if not organizador.organizador:
        organizador.organizador = True

    metodo = "CANCEL" if evento.cancelado else "REQUEST"
    status = "CANCELLED" if evento.cancelado else "CONFIRMED"

    linhas: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        f"METHOD:{metodo}",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{_uid_estavel(evento.agendamento_id, evento.dominio_uid)}",
        f"DTSTAMP:{_formato(datetime.now(timezone.utc))}",
        f"DTSTART:{_formato(evento.inicio)}",
        f"DTEND:{_formato(evento.fim)}",
        f"SUMMARY:{escapar(evento.resumo)}",
        f"SEQUENCE:{int(evento.sequencia)}",
        f"STATUS:{status}",
        f"TRANSP:{'TRANSPARENT' if evento.cancelado else 'OPAQUE'}",
    ]

    if evento.descricao:
        linhas.append(f"DESCRIPTION:{escapar(evento.descricao)}")
    if evento.local:
        linhas.append(f"LOCATION:{escapar(evento.local)}")

    nome_org = escapar(organizador.nome or organizador.email)
    linhas.append(f"ORGANIZER;CN={nome_org}:mailto:{organizador.email}")

    for p in evento.participantes:
        if p.organizador:
            continue
        papel = "OPT-PARTICIPANT" if p.opcional else "REQ-PARTICIPANT"
        nome = escapar(p.nome or p.email)
        linhas.append(
            f"ATTENDEE;CN={nome};ROLE={papel};RSVP=TRUE:mailto:{p.email}"
        )

    linhas += ["END:VEVENT", "END:VCALENDAR"]

    return "\r\n".join(_dobrar(ln) for ln in linhas) + "\r\n"


def nome_arquivo(evento: EventoConvite) -> str:
    """Nome do .ics anexado: sem acento, sem espaco, estavel por agendamento."""
    base = re.sub(r"[^a-z0-9]+", "-", (evento.resumo or "agendamento").lower()).strip("-")
    sufixo = "cancelamento" if evento.cancelado else "convite"
    return f"{sufixo}-{base[:40]}-{evento.agendamento_id}.ics"


# ----------------------------------------------------------------- validacao

def validar_ics(texto: str) -> list[str]:
    """Confere invariantes que, se violadas, fazem o cliente ignorar o anexo.

    Retorna a lista de problemas; lista vazia significa convite bem formado.
    Nao substitui um parser RFC completo — cobre o que ja nos mordeu.
    """
    problemas: list[str] = []

    if not texto.startswith("BEGIN:VCALENDAR"):
        problemas.append("nao comeca com BEGIN:VCALENDAR")
    if not texto.rstrip().endswith("END:VCALENDAR"):
        problemas.append("nao termina com END:VCALENDAR")
    if "\r\n" not in texto:
        problemas.append("linhas precisam terminar em CRLF")

    for obrigatorio in ("VERSION:2.0", "PRODID:", "METHOD:", "UID:", "DTSTART:", "DTEND:"):
        if obrigatorio not in texto:
            problemas.append(f"falta {obrigatorio}")

    if texto.count("BEGIN:VEVENT") != 1:
        problemas.append("deve haver exatamente um VEVENT")
    if texto.count("BEGIN:VCALENDAR") != 1:
        problemas.append("deve haver exatamente um VCALENDAR")

    # nenhuma linha pode passar de 75 octetos (fora o CRLF)
    for i, linha in enumerate(texto.split("\r\n"), 1):
        if len(linha.encode("utf-8")) > LIMITE_OCTETOS:
            problemas.append(f"linha {i} tem {len(linha.encode('utf-8'))} octetos (max 75)")
            break

    if "ATTENDEE" not in texto and "METHOD:REQUEST" in texto:
        problemas.append("REQUEST sem ATTENDEE nao entrega convite a ninguem")

    return problemas


def participantes_do_ics(texto: str) -> Iterable[str]:
    """Le os e-mails dos ATTENDEE — usado nos testes e na auditoria."""
    for linha in texto.split("\r\n"):
        if linha.startswith("ATTENDEE") and "mailto:" in linha:
            yield linha.split("mailto:", 1)[1].strip()
