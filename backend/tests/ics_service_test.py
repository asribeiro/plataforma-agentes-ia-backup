"""Testes do gerador de convite iCalendar (RFC 5545).

O que estes testes protegem: um .ics mal formado nao gera erro em lugar nenhum —
o cliente de e-mail simplesmente ignora o anexo, ou mostra a hora errada. E o
paciente nao aparece. Por isso o teste tem que ser explicito.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.ics_service import (
    EventoConvite,
    Participante,
    escapar,
    gerar_ics,
    nome_arquivo,
    participantes_do_ics,
    validar_ics,
)

SAO_PAULO = timezone(timedelta(hours=-3))
INICIO = datetime(2026, 11, 3, 15, 0, tzinfo=SAO_PAULO)  # 18:00 UTC
FIM = datetime(2026, 11, 3, 15, 30, tzinfo=SAO_PAULO)


def _evento(**kwargs):
    base = dict(
        agendamento_id=42,
        inicio=INICIO,
        fim=FIM,
        resumo="Avaliação odontológica",
        participantes=[
            Participante(email="clinica@exemplo.com", nome="Clínica", organizador=True),
            Participante(email="paciente@exemplo.com", nome="Thomaz"),
        ],
        descricao="Avaliação inicial para clareamento.",
        local="Rua Exemplo, 100 - São Paulo",
    )
    base.update(kwargs)
    return EventoConvite(**base)


def _desdobrar(texto: str) -> str:
    """Desfaz a dobra de linha (RFC 5545 3.1) para poder comparar conteúdo inteiro."""
    return texto.replace("\r\n ", "")


# ------------------------------------------------------------------ estrutura

def test_gera_ics_valido():
    texto = gerar_ics(_evento())
    assert validar_ics(texto) == []
    assert texto.startswith("BEGIN:VCALENDAR")
    assert texto.rstrip().endswith("END:VCALENDAR")


def test_usa_crlf():
    texto = gerar_ics(_evento())
    assert "\r\n" in texto
    # nenhuma quebra solta de LF
    assert "\n" not in texto.replace("\r\n", "")


def test_converte_para_utc():
    """15h em São Paulo é 18h UTC. Se isso falhar, o convite chega 3h errado."""
    texto = gerar_ics(_evento())
    assert "DTSTART:20261103T180000Z" in texto
    assert "DTEND:20261103T183000Z" in texto


def test_datetime_ingenuo_e_tratado_como_utc():
    inicio = datetime(2026, 11, 3, 18, 0)
    texto = gerar_ics(_evento(inicio=inicio, fim=inicio + timedelta(minutes=30)))
    assert "DTSTART:20261103T180000Z" in texto


# ---------------------------------------------------------------- participantes

def test_organizador_e_attendees():
    texto = _desdobrar(gerar_ics(_evento()))
    assert "ORGANIZER;CN=Clínica:mailto:clinica@exemplo.com" in texto
    assert "ATTENDEE;CN=Thomaz;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:paciente@exemplo.com" in texto


def test_participante_opcional_tem_papel_diferente():
    ev = _evento()
    ev.participantes.append(
        Participante(email="acompanhante@exemplo.com", nome="Acompanhante", opcional=True)
    )
    texto = _desdobrar(gerar_ics(ev))
    assert "OPT-PARTICIPANT" in texto


def test_convite_sem_participante_falha():
    with pytest.raises(ValueError):
        gerar_ics(_evento(participantes=[]))


def test_quem_nao_e_organizador_vira_attendee():
    texto = gerar_ics(_evento())
    organizadores = [ln for ln in texto.split("\r\n") if ln.startswith("ORGANIZER")]
    assert len(organizadores) == 1
    # o organizador nao aparece duplicado como ATTENDEE
    assert "mailto:clinica@exemplo.com" in organizadores[0]
    attendees = list(participantes_do_ics(texto))
    assert "clinica@exemplo.com" not in attendees


def test_email_qualquer_provedor_e_aceito():
    """O ponto do F1-07: funciona com Outlook, iCloud, corporativo, o que for."""
    for email in ("dr@outlook.com", "dr@icloud.com", "dr@hospital.com.br", "dr@gmail.com"):
        ev = _evento()
        ev.participantes = [
            Participante(email="clinica@exemplo.com", organizador=True),
            Participante(email=email, nome="Dr."),
        ]
        texto = gerar_ics(ev)
        assert validar_ics(texto) == []
        assert email in list(participantes_do_ics(texto))


# ------------------------------------------------------------------- escape

def test_escapa_virgula_ponto_e_virgula_e_barra():
    assert escapar("a,b;c\\d") == "a\\,b\\;c\\\\d"


def test_escapa_quebra_de_linha():
    assert escapar("linha1\nlinha2") == "linha1\\nlinha2"
    assert escapar("linha1\r\nlinha2") == "linha1\\nlinha2"


def test_nome_com_virgula_nao_quebra_o_parse():
    ev = _evento()
    ev.participantes = [
        Participante(email="clinica@exemplo.com", organizador=True),
        Participante(email="p@exemplo.com", nome="Silva, João"),
    ]
    texto = _desdobrar(gerar_ics(ev))
    assert validar_ics(gerar_ics(ev)) == []
    assert "CN=Silva\\, João" in texto


def test_none_vira_vazio():
    assert escapar(None) == ""


# ------------------------------------------------------------------ dobra de linha

def test_todas_as_linhas_cabem_em_75_octetos():
    ev = _evento(descricao="palavra " * 80, local="Avenida Muito Longa " * 20)
    texto = gerar_ics(ev)
    assert validar_ics(texto) == []
    for linha in texto.split("\r\n"):
        assert len(linha.encode("utf-8")) <= 75


def test_dobra_sem_quebrar_acento():
    ev = _evento(resumo="Avaliação " * 30)
    texto = gerar_ics(ev)
    # nenhum caractere de substituição — sinal de que cortou UTF-8 no meio
    assert "\ufffd" not in texto
    assert validar_ics(texto) == []


# ------------------------------------------------------- uid e sequencia

def test_uid_estavel_para_o_mesmo_agendamento():
    a = gerar_ics(_evento(agendamento_id=7))
    b = gerar_ics(_evento(agendamento_id=7, sequencia=1))
    uid_a = [ln for ln in a.split("\r\n") if ln.startswith("UID:")][0]
    uid_b = [ln for ln in b.split("\r\n") if ln.startswith("UID:")][0]
    assert uid_a == uid_b
    assert "agendamento-7@" in uid_a


def test_agendamentos_diferentes_tem_uid_diferente():
    a = [ln for ln in gerar_ics(_evento(agendamento_id=1)).split("\r\n") if ln.startswith("UID:")][0]
    b = [ln for ln in gerar_ics(_evento(agendamento_id=2)).split("\r\n") if ln.startswith("UID:")][0]
    assert a != b


def test_sequencia_aparece_no_convite():
    texto = gerar_ics(_evento(sequencia=3))
    assert "SEQUENCE:3" in texto


# ------------------------------------------------------------------ cancelamento

def test_cancelamento_usa_method_cancel():
    texto = gerar_ics(_evento(cancelado=True, sequencia=1))
    assert "METHOD:CANCEL" in texto
    assert "STATUS:CANCELLED" in texto
    assert "STATUS:CONFIRMED" not in texto


def test_cancelamento_preserva_o_uid():
    normal = gerar_ics(_evento(agendamento_id=9))
    cancelado = gerar_ics(_evento(agendamento_id=9, cancelado=True, sequencia=1))
    uid_n = [ln for ln in normal.split("\r\n") if ln.startswith("UID:")][0]
    uid_c = [ln for ln in cancelado.split("\r\n") if ln.startswith("UID:")][0]
    assert uid_n == uid_c


def test_convite_normal_nao_tem_cancel():
    texto = gerar_ics(_evento())
    assert "METHOD:REQUEST" in texto
    assert "STATUS:CONFIRMED" in texto


# ----------------------------------------------------------------- nome do arquivo

def test_nome_do_arquivo_sem_acento_e_sem_espaco():
    nome = nome_arquivo(_evento())
    assert nome.endswith(".ics")
    assert " " not in nome
    assert nome.isascii()


def test_nome_muda_no_cancelamento():
    assert "cancelamento" in nome_arquivo(_evento(cancelado=True))


# ------------------------------------------------------------------- validacao

def test_validar_pega_ics_sem_evento():
    ruim = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    problemas = validar_ics(ruim)
    assert any("VEVENT" in p for p in problemas)


def test_validar_pega_request_sem_attendee():
    ruim = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REQUEST\r\n"
        "BEGIN:VEVENT\r\nUID:x\r\nDTSTART:20261103T180000Z\r\n"
        "DTEND:20261103T183000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    problemas = validar_ics(ruim)
    assert any("ATTENDEE" in p for p in problemas)
