"""Prova de RLS no ambiente dev: dado existe, mas só aparece com o contexto certo.

O banco do dev nasce vazio, então o script cria as dependências mínimas (lead) descobrindo as colunas
NOT NULL em vez de adivinhar, insere um agendamento como OWNER e testa a leitura com o papel de
aplicação (plataforma_app, sem superuser e sem bypassrls) usando a chave `app.clinic_id`.
Limpa tudo no fim.
"""
import os
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, "/app")

e_owner = create_engine(os.environ["ALEMBIC_DATABASE_URL"], future=True)
e_app = create_engine(os.environ["DATABASE_URL"], future=True)

CLIENTE, EMPRESA_CERTA, EMPRESA_ERRADA = 1, 1, 999


# Colunas de FK precisam de valor que exista; o resto pode ser sintético.
OVERRIDES = {"client_id": "1", "company_id": "1", "clinic_id": "1"}


def valores_sinteticos(tipo: str, nome: str = ""):
    if nome in OVERRIDES:
        return OVERRIDES[nome]
    t = tipo.lower()
    if t in ("integer", "bigint", "smallint", "numeric", "double precision", "real"):
        return "0"
    if t in ("boolean",):
        return "false"
    if t.startswith("timestamp"):
        return "now()"
    if t == "date":
        return "current_date"
    if t == "uuid":
        return "gen_random_uuid()"
    if t in ("json", "jsonb"):
        return "'{}'::jsonb"
    return "'prova-rls'"


def not_null(conn, tabela: str):
    return conn.execute(text("""
        SELECT column_name, data_type FROM information_schema.columns
         WHERE table_name = :t AND is_nullable = 'NO' AND column_default IS NULL
           AND is_identity = 'NO' AND column_name <> 'id'
         ORDER BY ordinal_position
    """), {"t": tabela}).fetchall()


print("=== 0) preparando dependências como owner")
with e_owner.begin() as c:
    existe = c.execute(text("SELECT count(*) FROM leads WHERE id = 1")).scalar()
    if not existe:
        cols = not_null(c, "leads")
        nomes = [n for n, _ in cols]
        expr = [valores_sinteticos(t, n) for n, t in cols]
        sql = f"INSERT INTO leads (id, {', '.join(nomes)}) VALUES (1, {', '.join(expr)})"
        c.execute(text(sql))
        print(f"   lead 1 criado com colunas obrigatórias: {nomes}")
    else:
        print("   lead 1 já existia")

    c.execute(text("DELETE FROM agendamentos WHERE lead_id = 1 AND client_id = 1"))
    c.execute(text("""
        INSERT INTO agendamentos (client_id, company_id, lead_id, agendamento_realizado_em, status)
        VALUES (:cl, :co, 1, now(), 'SCHEDULED')
    """), {"cl": CLIENTE, "co": EMPRESA_CERTA})
    print(f"   agendamento de prova criado; total no banco: {c.execute(text('SELECT count(*) FROM agendamentos')).scalar()}")

print("\n=== 1) papel de aplicação, SEM contexto")
with e_app.connect() as c:
    qtd = c.execute(text("SELECT count(*) FROM agendamentos")).scalar()
    print(f"   visíveis: {qtd}  -> {'OK (não vê nada)' if qtd == 0 else 'FALHOU'}")

print(f"\n=== 2) papel de aplicação, contexto da empresa {EMPRESA_CERTA}")
with e_app.begin() as c:
    c.execute(text("SELECT set_config('app.clinic_id', :v, false)"), {"v": str(EMPRESA_CERTA)})
    qtd = c.execute(text("SELECT count(*) FROM agendamentos")).scalar()
    print(f"   visíveis: {qtd}  -> {'OK (vê o próprio)' if qtd >= 1 else 'FALHOU'}")

print(f"\n=== 3) papel de aplicação, contexto da empresa {EMPRESA_ERRADA}")
with e_app.begin() as c:
    c.execute(text("SELECT set_config('app.clinic_id', :v, false)"), {"v": str(EMPRESA_ERRADA)})
    qtd = c.execute(text("SELECT count(*) FROM agendamentos")).scalar()
    print(f"   visíveis: {qtd}  -> {'OK (não vê o do vizinho)' if qtd == 0 else 'FALHOU'}")

print("\n=== 4) escrita sem contexto")
try:
    with e_app.begin() as c:
        c.execute(text("""
            INSERT INTO agendamentos (client_id, company_id, lead_id, agendamento_realizado_em, status)
            VALUES (:cl, :co, 1, now(), 'SCHEDULED')
        """), {"cl": CLIENTE, "co": EMPRESA_CERTA})
    print("   FALHOU: o insert passou sem contexto")
except Exception as exc:  # noqa: BLE001
    print(f"   OK: negado ({type(exc).__name__}: {str(exc).splitlines()[0][:100]})")

print("\n=== 5) limpeza")
with e_owner.begin() as c:
    c.execute(text("DELETE FROM agendamentos WHERE lead_id = 1 AND client_id = 1"))
    c.execute(text("DELETE FROM leads WHERE id = 1"))
    print(f"   agendamentos restantes: {c.execute(text('SELECT count(*) FROM agendamentos')).scalar()}"
          f" | leads restantes: {c.execute(text('SELECT count(*) FROM leads')).scalar()}")
