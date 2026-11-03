# Scripts operacionais dos ambientes

Utilitários que preparam e verificam os ambientes. Nenhum deles é chamado pela aplicação: rodam como
tarefa de operação, com `docker compose run --rm --no-deps`.

Todos têm **guarda de alvo**: o script de anonimização e o de credencial abortam se o banco não terminar
em `_homolog`. Isso é deliberado — são scripts que destroem dado de propósito, e um alvo errado seria
perda irreversível.

## Preparar um ambiente novo

| script | para quê |
|---|---|
| `seed_dev.py` | semeia empresa, conta master e usuário admin num banco vazio (idempotente) |
| `credencial_homolog.py` | define e-mail/senha de acesso do homolog depois da anonimização |
| `anonimiza_homolog.py` | anonimiza o retrato de produção restaurado em homolog |

## Verificar

| script | para quê |
|---|---|
| `prova_rls_dev2.py` | RLS com dado real: sem contexto = 0, empresa dona = N, outra empresa = 0, escrita negada |
| `verifica_homolog.py` | varredura de resíduo de dado real + isolamento por RLS no homolog |

## Como rodar

```bash
# dentro do diretório do ambiente, com os dois env-files
docker compose \
  --env-file deploy/environments/homolog.env \
  --env-file /etc/plataforma-agentes/postgres-homolog/env \
  run --rm --no-deps \
  -v /caminho/do/script.py:/tmp/script.py:ro \
  -w /app -e PYTHONPATH=/app \
  api python -W ignore /tmp/script.py
```

## Anonimização: as três decisões que importam

1. **Determinístico por valor (`md5`)**, não por linha. O mesmo telefone vira o mesmo número sintético em
   qualquer tabela — sem isso o fluxo quebra (mensagem aponta para um contato que não existe mais).
2. **`abs()` é obrigatório** no `bit(32)::int`: o Postgres interpreta como assinado e devolve negativo em
   metade dos casos. Sem isso o rótulo sai "Pessoa -21664" e o `lpad` gasta uma posição com o sinal,
   gerando telefone inválido ("55199-7087599").
3. **Texto livre é substituído, não embaralhado.** Conversa de paciente e nota clínica não podem ir para
   homolog. Fica um marcador com o tamanho original, o suficiente para testar layout.

Credencial e token (`password`, `api_key`, `google_oauth_token`, sessão de WhatsApp, chave de IA) são
zerados ou recebem marcador inválido: homolog nunca deve autenticar em serviço real. Colunas `NOT NULL`
não aceitam `NULL` — nesses casos, marcador inválido cumpre o papel.

## Depois do restore, antes de subir a aplicação

1. `ALTER ROLE plataforma_app PASSWORD …` + `LOGIN` (a migration 0025 cria o papel `NOLOGIN` e sem senha).
2. Anonimizar.
3. Definir credencial de acesso.
4. Só então `up -d api worker beat web`.
