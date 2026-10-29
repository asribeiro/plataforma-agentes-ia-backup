"""Reescrita das URLs legadas com "clinic" no nome.

Contexto do defeito (29/10): o middleware `legacy_domain_compatibility_middleware`
em `main.py` trocava `/api/clinic` por `/api/company` em TODO caminho, sem olhar
se aquele caminho existia de verdade. As rotas novas `/api/clinic/users` e
`/api/clinic/access-log` (cards F1-12 e F1-13) eram reescritas para
`/api/company/users` — que nao existe — e o cliente recebia 404. O codigo estava
carregado, as rotas registradas, o teste passando: o middleware comia a URL antes
do roteador.

Regra nova, e a que deve valer para toda compatibilidade de URL: **reescrever so
o que e legado de fato**. Se o caminho ja casa com uma rota registrada, ele nao e
legado e ninguem encosta nele. Compatibilidade que reescreve caminho vivo nao e
compatibilidade, e colisao de nome esperando data para acontecer.
"""
from typing import Callable, Iterable

# Ordem importa: as substituicoes mais especificas vem antes das genericas.
SUBSTITUICOES_LEGADAS: tuple[tuple[str, str], ...] = (
    ("/client-clinics", "/client-companies"),
    ("/clinics-admin", "/companies-admin"),
    ("/complete-clinic", "/complete-company"),
    ("/clinics/", "/companies/"),
    ("/api/clinic/", "/api/company/"),
    ("/api/clinic", "/api/company"),
    ("/clinic/", "/company/"),
    ("/clinic", "/company"),
)


def reescrever_caminho_legado(
    caminho: str,
    caminho_registrado: Callable[[str], bool] | None = None,
) -> str:
    """Devolve o caminho reescrito, ou o mesmo caminho quando nao for legado.

    `caminho_registrado` responde "existe rota para esse caminho?". Quando ele diz
    que sim, a reescrita NAO acontece — e esse o conserto do defeito descrito no
    topo do arquivo.
    """
    if not caminho or "clinic" not in caminho:
        return caminho
    if caminho_registrado is not None and caminho_registrado(caminho):
        return caminho

    novo = caminho
    for antigo, atual in SUBSTITUICOES_LEGADAS:
        novo = novo.replace(antigo, atual)
    return novo


def reescrever_query_legada(query_string: bytes) -> bytes:
    """`clinic_id=` -> `company_id=`. Compatibilidade de nome de parametro."""
    if not query_string or b"clinic_id=" not in query_string:
        return query_string
    return query_string.replace(b"clinic_id=", b"company_id=")


def aplicar_substituicoes(caminho: str, substituicoes: Iterable[tuple[str, str]]) -> str:
    """Utilidade para teste: aplica a lista dada sem a checagem de rota."""
    novo = caminho
    for antigo, atual in substituicoes:
        novo = novo.replace(antigo, atual)
    return novo
