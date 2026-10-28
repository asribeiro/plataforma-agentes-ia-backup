"""Cliente Redis centralizado.

P2-12: havia dois problemas no codigo.

1. Sete modulos criavam o cliente com host fixo no literal 'localhost':
       redis_client = redis.Redis(host='localhost', port=6379, db=0)
   Dentro de um container, 'localhost' e o proprio container, nao o servico
   redis. Medido em producao: `ping()` levanta
   `ConnectionError: Error 111 connecting to localhost:6379. Connection refused`.
   Como a conexao e preguicosa, isso nao estoura no import — quebra em silencio
   na hora do uso.

2. Outros pontos usavam os.getenv("REDIS_URL", "redis://localhost:6379/0"), ou
   seja, o default tambem apontava para localhost. Funcionava so porque o
   .env.backend define REDIS_URL; sem essa variavel, tudo caia em localhost.

Este modulo resolve os dois: le REDIS_URL e, quando ausente, assume o nome do
servico no compose (`redis`), que e o default correto para a aplicacao.
"""
from __future__ import annotations

import os

import redis

# Nome do servico no compose.yml. Correto dentro da rede do Docker.
REDIS_URL_PADRAO = "redis://redis:6379/0"


def redis_url() -> str:
    """URL do Redis, com fallback para o servico do compose."""
    for nome in ("REDIS_URL", "MESSAGE_TRACKER_REDIS_URL"):
        valor = (os.getenv(nome) or "").strip()
        if valor:
            return valor
    return REDIS_URL_PADRAO


def get_redis_client(decode_responses: bool = False, db: int = 0):
    """Cliente Redis apontando para o servico certo.

    Conexao preguicosa: o primeiro comando estabelece a conexao. Timeout curto
    para nao travar a requisicao quando o Redis estiver fora.
    """
    url = redis_url()
    if db:
        base = url.rsplit("/", 1)[0]
        url = f"{base}/{db}"
    return redis.from_url(
        url,
        decode_responses=decode_responses,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
