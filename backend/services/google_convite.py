"""Quem recebe o convite do evento e com que aviso (card F1-02).

O problema que isto resolve: `create_google_event` criava o evento SEM
`attendees` e SEM `sendUpdates`. O evento nascia no calendario da clinica e o
Google nao notificava ninguem — nem o profissional, nem o paciente. Do ponto de
vista de quem foi atendido pela IA, o agendamento "nao existia".

Decisoes que estao codificadas aqui (28/10):

- Paciente SEM e-mail NAO impede o agendamento. O profissional vinculado a agenda
  continua sendo convidado e o aviso ao paciente vai por WhatsApp. `invite_sent_at`
  fica NULL nesse caso, porque nao houve convite — e NULL com significado e melhor
  que data inventada.
- `sendUpdates` e "all" sempre que houver pelo menos um convidado: `none` com
  `attendees` e exatamente o bug que este modulo fecha (Google recebe a lista e
  nao avisa).
- E-mail e comparado em minusculas e sem espaco. Convidado duplicado faz o Google
  mandar dois avisos, e o segundo parece erro do sistema.
"""
import re
from typing import Iterable, List, Optional

PADRAO_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalizar_email(valor: Optional[str]) -> Optional[str]:
    """Devolve o e-mail em forma canonica ou None se nao for e-mail utilizavel.

    Nao tenta "consertar" e-mail torto: convidar endereco invalido gera erro de
    API no Google e um agendamento marcado como falha por causa de dado ruim.
    """
    if not valor or not isinstance(valor, str):
        return None
    limpo = valor.strip().strip("<>").strip().lower()
    if not limpo or not PADRAO_EMAIL.match(limpo):
        return None
    return limpo


def montar_attendees(*emails: Optional[str]) -> List[str]:
    """Lista unica e ordenada de convidados validos (ordem de chegada)."""
    vistos = set()
    convidados: List[str] = []
    for bruto in emails:
        email = normalizar_email(bruto)
        if email and email not in vistos:
            vistos.add(email)
            convidados.append(email)
    return convidados


def montar_attendees_de_lista(emails: Iterable[Optional[str]]) -> List[str]:
    return montar_attendees(*list(emails))


def politica_de_aviso(attendees: Optional[List[str]]) -> str:
    """`sendUpdates` para o Google: 'all' com convidado, 'none' sem.

    Devolver 'none' quando EXISTS convidado seria repetir o defeito que este
    modulo fecha: o Google aceitaria a lista e nao avisaria ninguem.
    """
    return "all" if attendees else "none"


def descrever_convite(attendees: Optional[List[str]], profissional: Optional[str] = None) -> str:
    """Frase para log/descricao do evento: quem foi convidado, sem inventar."""
    if not attendees:
        if profissional:
            return f"Sem convite por e-mail. Aviso ao paciente por WhatsApp; {profissional} não recebeu convite."
        return "Sem convite por e-mail (paciente sem e-mail; aviso por WhatsApp)."
    return "Convite enviado para: " + ", ".join(attendees)
