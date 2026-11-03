"""Nome para usar nas mensagens ao paciente, com queda elegante para o telefone.

`contacts.name` é o pushname do WhatsApp: o contato salvo como "Eu pessoal" fazia o lembrete do paciente
sair "Olá, Eu!". O nome confiável é o do agendamento (`agendamentos.nome`) ou do paciente (`patients.name`);
quando nenhum serve, a saudação vai sem nome em vez de inventar um.
"""
from __future__ import annotations

import re

# Pushname, apelido de agenda ou sobra de importação — nada disso é nome de paciente.
GENERICOS = {
    "eu", "eu pessoal", "eu mesmo", "cliente", "paciente", "contato", "voce", "sem nome",
    "semname", "whatsapp", "usuario", "user", "desconhecido", "na", "n a", "nao informado",
    "test", "foo", "lead", "numero", "telefone",
}

_ACENTOS = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")


def _limpar(nome) -> str:
    texto = re.sub(r"[^\w\s'\-]", " ", str(nome or "")).strip()
    return re.sub(r"\s+", " ", texto)


def primeiro_nome_confiavel(*candidatos, telefone: str = "") -> str | None:
    """Primeiro candidato que serve como nome de pessoa; `None` quando nenhum serve."""
    digitos_telefone = re.sub(r"\D", "", str(telefone or ""))
    for candidato in candidatos:
        limpo = _limpar(candidato)
        if not limpo:
            continue
        digitos = re.sub(r"\D", "", limpo)
        if digitos and digitos == limpo.replace(" ", ""):
            continue  # só números
        if len(digitos_telefone) >= 8 and digitos and digitos_telefone.endswith(digitos[-8:]):
            continue  # é o próprio telefone
        if limpo.lower().translate(_ACENTOS) in GENERICOS:
            continue
        primeiro = limpo.split(" ")[0]
        if len(primeiro) < 2:
            continue
        return primeiro[:1].upper() + primeiro[1:]
    return None


def saudacao_com_nome(nome: str | None, prefixo: str = "Olá") -> str:
    """`Olá, Anderson!` quando há nome; `Olá!` quando não há."""
    return f"{prefixo}, {nome}!" if nome else f"{prefixo}!"
