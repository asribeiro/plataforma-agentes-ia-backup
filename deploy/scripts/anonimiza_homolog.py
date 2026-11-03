"""Anonimiza o banco de homologação depois de restaurar o retrato de produção.

Regras:
  * determinístico por valor (md5), então o mesmo telefone/nome vira o mesmo rótulo em qualquer tabela —
    é isso que mantém o fluxo coerente (mensagem aponta para o contato certo);
  * texto livre (mensagem, nota clínica) é substituído: homolog não pode carregar conversa real;
  * credencial e token são zerados, para o homolog nunca autenticar em serviço real;

Guarda de segurança: só roda em banco cujo nome termina em `_homolog`. Senão aborta.
"""
import os
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, "/app")

URL = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ["DATABASE_URL"]
BANCO = URL.rsplit("/", 1)[-1].split("?")[0]

if not BANCO.endswith("_homolog"):
    print(f"ABORTADO: o alvo é {BANCO!r}, que não é um banco de homologação.")
    print("Esta rotina destrói dado de propósito — em produção seria perda irreversível.")
    sys.exit(1)

print(f"alvo: {BANCO} (confirmado como homolog)\n")
e = create_engine(URL, future=True, isolation_level="AUTOCOMMIT")


def seq(expr: str, modulo: int) -> str:
    """Sequência determinística a partir do próprio valor.

    `abs()` é obrigatório: `bit(32)::int` no Postgres é assinado e devolve negativo em metade dos casos —
    sem isso o rótulo sai como "Pessoa -21664" e o lpad gasta uma posição com o sinal, virando
    telefone inválido ("55199-7087599").
    """
    return f"(abs((('x' || substr(md5(coalesce({expr}::text, '')), 1, 8))::bit(32)::int)::bigint) % {modulo})"


def num(expr: str, mod: int, largura: int) -> str:
    return f"lpad(({seq(expr, mod)})::text, {largura}, '0')"


# nome de pessoa -> rótulo estável
NOME = "('Pessoa ' || " + num("{}", 900000, 6) + ")"
# telefone -> sufixo numérico estável, prefixo de telefone fictício
FONE = "('55199' || " + num("{}", 100000000, 8) + ")"
EMAIL = "('pessoa' || " + num("{}", 900000, 6) + " || '@exemplo.test')"
DOC = "(" + num("{}", 100000000000, 11) + ")"
TEXTO = "('[anonimizado na homologação — ' || coalesce(length({}::text), 0) || ' caracteres]')"
ENDERECO = "'Rua Anonimizada, 100'"
VAZIO = "NULL"

# (tabela, coluna) -> expressão SQL
REGRAS: dict[tuple[str, str], str] = {}

# --- nomes de pessoa (só nas tabelas onde o campo é gente, não nome de configuração)
for tabela, coluna in [
    ("patients", "name"), ("contacts", "name"), ("leads", "name"), ("users", "name"),
    ("agendamentos", "nome"), ("comparecimentos", "nome"), ("agendas", "name"),
    ("patient_timeline_events", "title"), ("satisfaction_surveys", "patient_name"),
]:
    REGRAS[(tabela, coluna)] = NOME.format(f"{tabela}.{coluna}")

# --- telefones
for tabela, coluna in [
    ("contacts", "phone"), ("agendamentos", "phone"), ("comparecimentos", "phone"),
    ("agent_executions", "phone"), ("ai_usage_events", "phone"),
    ("agents_sdk_memory", "contact_phone"), ("agents_sdk_runs", "contact_phone"),
    ("companies", "fixed_phone"), ("companies", "administrative_responsible_phone"),
]:
    REGRAS[(tabela, coluna)] = FONE.format(f"{tabela}.{coluna}")

# --- e-mails
for tabela, coluna in [
    ("clients", "email"), ("users", "email"), ("agendamentos", "patient_email"),
    ("companies", "billing_email"), ("companies", "administrative_responsible_email"),
    ("agendas", "google_account_email"), ("calendar_integrations", "google_account_email"),
    ("clinical_access_log", "user_email"),
]:
    REGRAS[(tabela, coluna)] = EMAIL.format(f"{tabela}.{coluna}")

# --- documentos e CEP
for tabela, coluna in [
    ("companies", "cnpj"), ("companies", "postal_code"),
    ("patients", "cpf"), ("patients", "document"), ("patients", "document_number"),
    ("companies", "technical_responsible_cro"),
]:
    REGRAS[(tabela, coluna)] = DOC.format(f"{tabela}.{coluna}")

# --- endereço
for tabela, coluna in [
    ("agendamentos", "endereco"), ("companies", "address"), ("companies", "address_complement"),
    ("patients", "address"), ("patients", "address_complement"),
]:
    REGRAS[(tabela, coluna)] = ENDERECO

# --- texto livre: conversa real não vai para homolog
for tabela, coluna in [
    ("messages", "content"), ("agents_sdk_messages", "content"),
    ("confirmation_messages", "content"), ("contact_notes", "content"),
    ("clinical_notes", "note_text"), ("clinical_note_addenda", "content"),
    ("agent_dynamic_followup_executions", "generated_message"),
]:
    REGRAS[(tabela, coluna)] = TEXTO.format(f"{tabela}.{coluna}")

# --- credencial e token: zerados, para não autenticar em nada real
for tabela, coluna in [
    ("clients", "password"), ("clients", "api_key"),
    ("agendas", "google_oauth_token"), ("calendar_integrations", "google_oauth_token"),
    ("calendar_integrations", "clinicorp_password"), ("calendar_integrations", "clinicorp_username"),
    ("companies", "zapi_token"), ("companies", "wppconnect_secret_key"),
    ("companies", "waha_session_name"), ("companies", "wppconnect_session_name"),
    ("companies", "zapi_instance_id"),
    ("clinical_notes", "signature_hash"),
]:
    REGRAS[(tabela, coluna)] = VAZIO

# Colunas NOT NULL não aceitam NULL. Marcador inválido cumpre o papel: não autentica e não descriptografa.
# `users.password` é NOT NULL — com NULL o UPDATE falha calado (fica o hash de produção, que é dado
# sensível de verdade: bcrypt de senha real pode ser atacado offline).
for tabela, coluna in [
    ("ai_provider_credentials", "api_key_encrypted"),
    ("users", "password"),
]:
    REGRAS[(tabela, coluna)] = "'[removido-na-homologacao]'"

print("=== aplicando anonimização")
aplicadas, ausentes, total_linhas = 0, [], 0
with e.connect() as c:
    existentes = {
        (t, col)
        for t, col in c.execute(text("""
            SELECT table_name, column_name FROM information_schema.columns
             WHERE table_schema = 'public'
        """)).fetchall()
    }
    for (tabela, coluna), expr in REGRAS.items():
        if (tabela, coluna) not in existentes:
            ausentes.append(f"{tabela}.{coluna}")
            continue
        sql = f'UPDATE "{tabela}" SET "{coluna}" = {expr} WHERE "{coluna}" IS NOT NULL'
        try:
            r = c.execute(text(sql))
            aplicadas += 1
            total_linhas += r.rowcount or 0
            print(f"   {tabela}.{coluna:32} {r.rowcount:5} linha(s)")
        except Exception as exc:  # noqa: BLE001
            print(f"   {tabela}.{coluna:32} FALHOU: {type(exc).__name__}: {str(exc)[:80]}")

    print(f"\n   colunas anonimizadas: {aplicadas} | linhas tocadas: {total_linhas}")
    if ausentes:
        print(f"   colunas previstas que não existem neste schema: {', '.join(ausentes)}")

    print("\n=== conferência (amostra, valores já anonimizados)")
    amostra = c.execute(text("""
        SELECT id, nome, phone, patient_email FROM agendamentos ORDER BY id LIMIT 3
    """)).fetchall()
    for linha in amostra:
        print(f"   agendamento {linha[0]}: nome={linha[1]} phone={linha[2]} email={linha[3]}")

    msg = c.execute(text("SELECT content FROM messages ORDER BY id LIMIT 2")).fetchall()
    for i, linha in enumerate(msg, 1):
        print(f"   mensagem {i}: {linha[0]}")

    contatos = c.execute(text("SELECT id, name, phone FROM contacts ORDER BY id LIMIT 3")).fetchall()
    for linha in contatos:
        print(f"   contato {linha[0]}: nome={linha[1]} phone={linha[2]}")

    print("\n=== nenhum resíduo de e-mail real?")
    residuo = c.execute(text("""
        SELECT count(*) FROM users WHERE email NOT LIKE '%@exemplo.test'
    """)).scalar()
    print(f"   usuários com e-mail não anonimizado: {residuo}")
