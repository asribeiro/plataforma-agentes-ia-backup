"""Patch parcial de campos: distingue "nao enviado" de "enviado como null".

Por que existe: os PUT de procedimentos e profissionais faziam

    for campo in (...):
        valor = getattr(dados, campo)
        if valor is not None:
            setattr(obj, campo, valor)

e com isso era IMPOSSIVEL limpar um campo opcional. Mandar `price_cents: null`
mantinha o preco antigo — o dono da clinica removia o preco na tela, a tela
dizia "removido" e o agente continuava citando valor ao paciente. O mesmo valia
para `phone` e `cro` de profissional.

`valor is not None` nao consegue diferenciar:

    {"name": "Clareamento"}                      -> nao falou do preco, PRESERVA
    {"price_cents": null}                        -> pediu para APAGAR o preco

O Pydantic sabe a diferenca: `model_fields_set` lista os campos que vieram no
corpo da requisicao. Este helper usa isso, e so aceita null nos campos que o
banco permite anular (`anulaveis`): mandar `duration_minutes: null` continua
sendo ignorado, porque a coluna e NOT NULL e aplicar seria trocar um dado por
um erro 500.
"""
from typing import Any, Iterable

# pydantic v2 -> model_fields_set | pydantic v1 -> __fields_set__
_ATRIBUTOS_DE_CAMPOS_ENVIADOS = ("model_fields_set", "__fields_set__")


def campos_enviados(dados: Any) -> set:
    """Quais campos vieram no corpo da requisicao (nao quais sao != None)."""
    for atributo in _ATRIBUTOS_DE_CAMPOS_ENVIADOS:
        enviados = getattr(dados, atributo, None)
        if enviados is not None:
            return set(enviados)
    return set()


def aplicar_patch(
    obj: Any,
    dados: Any,
    campos: Iterable[str],
    anulaveis: Iterable[str] = (),
) -> None:
    """Aplica em `obj` só os campos presentes em `dados`.

    - campo ausente na requisicao   -> nao toca
    - campo presente com valor      -> aplica
    - campo presente como null      -> aplica APENAS se estiver em `anulaveis`
    """
    anulaveis = set(anulaveis)
    enviados = campos_enviados(dados)
    for campo in campos:
        if campo not in enviados:
            continue
        valor = getattr(dados, campo)
        if valor is None and campo not in anulaveis:
            continue
        setattr(obj, campo, valor)
