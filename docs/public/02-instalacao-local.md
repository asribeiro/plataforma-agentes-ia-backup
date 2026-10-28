# 2. Instalação local

## 1. Clone o repositório

```bash
git clone https://github.com/matheusmontelro/plataforma-agentes-ia.git sua-plataforma
cd sua-plataforma
```

Confirme que o clone não trouxe arquivos locais ou dados de outra instalação:

```bash
git status --short
git ls-files | grep -E '(^|/)(\.env|.*\.(db|sqlite|sqlite3))$' || true
```

O primeiro comando deve ficar vazio. O segundo não deve listar segredos nem bancos de runtime.

## 2. Crie o ambiente Python

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

Ative o mesmo ambiente virtual em cada novo terminal:

```bash
source .venv/bin/activate
```

## 3. Instale o frontend

```bash
npm --prefix frontend ci
```

`npm ci` respeita `frontend/package-lock.json` e falha se o lockfile estiver incoerente. Essa falha deve ser corrigida no repositório; não troque por uma atualização automática de pacotes durante o primeiro clone.

## 4. Crie configurações locais

```bash
cp .env.development.example backend/.env
cp frontend/.env.development.example frontend/.env.local
```

Edite os arquivos copiados. Eles são ignorados pelo Git. Gere os segredos marcados como vazios, cada um separadamente:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Para a chave de criptografia das credenciais BYOK:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Não cole o resultado em commits, issues, capturas de tela ou mensagens de suporte.

## 5. Prepare diretórios de runtime

Os caminhos do exemplo de desenvolvimento ficam dentro de `var/`, que é ignorado pelo Git:

```bash
mkdir -p \
  var/media/waha \
  var/chatmemory \
  var/logs \
  var/logos \
  var/account-profiles
```

## 6. Crie o banco e o administrador

Siga [Banco de dados e primeiro administrador](03-banco-de-dados.md). Não inicie a aplicação antes de aplicar a migration.

Se estiver usando a opção Docker das dependências, inicie-a antes:

```bash
cp .env.dependencies.example .env.dependencies
```

Preencha `POSTGRES_PASSWORD` em `.env.dependencies` antes de subir os containers:

```bash
docker compose --env-file .env.dependencies -f compose.dependencies.yml up -d
docker compose --env-file .env.dependencies -f compose.dependencies.yml ps
```

Esse Compose não inicia a aplicação nem o WAHA.

## 7. Inicie em desenvolvimento

Com PostgreSQL e Redis ativos, em um terminal na raiz:

```bash
source .venv/bin/activate
python -m uvicorn backend.main:app --env-file backend/.env --reload --host 127.0.0.1 --port 8002
```

Em outro terminal:

```bash
npm --prefix frontend start
```

Use a URL exibida pelo Vite, normalmente `http://localhost:3004`. As chamadas para `/api`, `/auth`, `/webhook`, `/health`, `/ws`, `/media` e `/agents-sdk` são encaminhadas ao backend pelo proxy de desenvolvimento.

## 8. Verificação mínima

Em desenvolvimento, o endpoint de banco não exige o token de monitoramento:

```bash
curl -fsS http://127.0.0.1:8002/health/db-connections
```

Depois, abra o frontend, entre com o administrador criado e confirme que a tela inicial carrega sem erros no console do navegador.

## 9. (Opcional) Stack isolada com Docker Compose

Para subir `web`, `api`, `postgres` e `redis` via Compose usando o arquivo raiz `compose.yml`, ajuste antes o `.env.docker`:

```dotenv
WEB_BIND_HOST=0.0.0.0
WEB_PORT=8083
API_BIND_HOST=0.0.0.0
API_PORT=8002
```

Depois:

```bash
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
```

No exemplo acima, o frontend fica em `http://SEU_HOST:8083` e a API em `http://SEU_HOST:8002`.

Se precisar de HTTPS no acesso externo, use o serviço `edge` descrito em [Deploy no servidor](06-deploy.md).
