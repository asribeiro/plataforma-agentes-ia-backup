# Ambientes da plataforma (dev · homolog · produção)

Um `compose.yml`, três env-files. O que muda entre ambientes é **dado**, não código.

| | dev | homolog | produção |
|---|---|---|---|
| projeto compose | `plataforma-agentes-dev` | `plataforma-agentes-homolog` | `plataforma-agentes` |
| env-file | `dev.env` | `homolog.env` | `prod.env` |
| web / api (loopback) | :8092 / :8012 | :8082 / :8011 | :8083 / :8002 |
| banco | `plataforma_agentes_dev` | `plataforma_agentes_homolog` | `plataforma_agentes` |
| imagem | `…backend:dev` | `…backend:homolog` | `…backend:prod` |
| worker | concurrency 1 | concurrency 2 | concurrency 2 |
| WhatsApp (WAHA) | desligado | chip próprio | número real |
| hostname | `dev.agente.…` | `homolog.agente.…` | `meu-agente.…` |
| basic auth | sim | sim | não (público) |

## Como subir cada ambiente

```bash
# produção (na VPS, diretório /opt/plataforma-agentes/prod)
docker compose --env-file deploy/environments/prod.env up -d --build

# homologação
docker compose --env-file deploy/environments/homolog.env up -d

# desenvolvimento
docker compose --env-file deploy/environments/dev.env up -d
```

Ver o que o Compose vai realmente fazer, sem subir nada:

```bash
docker compose --env-file deploy/environments/dev.env config
```

## Segredos

Nunca neste diretório. Cada ambiente tem os seus:

- `POSTGRES_PASSWORD` → `/etc/plataforma-agentes/postgres-<ambiente>/env` (modo 600, dono root)
- chaves da aplicação → `.env.backend` no diretório do ambiente (modo 600, gitignored)

O env-file versionado só carrega nome de projeto, portas, banco e concorrência — nada sensível.

O Compose aceita mais de um `--env-file`, e o último vence. É assim que o segredo entra sem estar no repo:

```bash
docker compose \
  --env-file deploy/environments/prod.env \
  --env-file /etc/plataforma-agentes/postgres-prod/env \
  up -d
```

`POSTGRES_PASSWORD` é declarado com `:?` no compose — **sem ele o comando falha na hora**, em vez de subir
banco com senha vazia. Falhar alto é o comportamento desejado.

## Regras que o desenho assume

1. **Uma instância de banco por ambiente.** Nunca o mesmo Postgres para dois ambientes.
2. **Imagem nomeada por ambiente** (`APP_IMAGE`). Build em dev não encosta na imagem de produção.
3. **Banco não publica porta.** Inspeção é `docker exec`, não porta aberta no host.
4. **A borda TLS é outra stack** (`/opt/borda`), dona única de 80/443. O serviço `edge` deste compose
   está no profile `edge-local` e não sobe no `up` normal.
5. **`WORKER_CONCURRENCY` é limitação de recurso, não de fidelidade**: produção e homolog em 2, dev em 1.
