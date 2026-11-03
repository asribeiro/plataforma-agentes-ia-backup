"""Verificação final do homolog: resíduo de dado real e isolamento por RLS."""
import os
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, "/app")

URL = os.environ["ALEMBIC_DATABASE_URL"]
BANCO = URL.rsplit("/", 1)[-1]
if not BANCO.endswith("_homolog"):
    print(f"ABORTADO: alvo {BANCO!r} não é homolog")
    sys.exit(1)

e_owner = create_engine(URL, future=True)
e_app = create_engine(os.environ["DATABASE_URL"], future=True)

TERMOS = ["anderson", "ribeiro", "flávio", "flavio", "maya", "thomaz", "tatiana", "laselva"]
TABELAS_TEXTO = [
    ("patients", ["name"]),
    ("contacts", ["name", "phone"]),
    ("leads", ["name"]),
    ("agendamentos", ["nome", "phone"]),
    ("messages", ["content"]),
    ("clinical_notes", ["note_text"]),
    ("comparecimentos", ["nome", "phone"]),
]

print("=== 1) resíduo de nome/telefone real no banco do homolog")
total_residuo = 0
with e_owner.connect() as c:
    for tabela, colunas in TABELAS_TEXTO:
        for coluna in colunas:
            for termo in TERMOS:
                try:
                    qtd = c.execute(text(
                        f'SELECT count(*) FROM "{tabela}" WHERE lower("{coluna}"::text) LIKE :t'
                    ), {"t": f"%{termo}%"}).scalar()
                except Exception as exc:  # noqa: BLE001
                    print(f"   {tabela}.{coluna}: consulta falhou ({type(exc).__name__})")
                    continue
                if qtd:
                    total_residuo += qtd
                    print(f"   RESÍDUO: {tabela}.{coluna} contém '{termo}' em {qtd} linha(s)")
print(f"   total de linhas com resíduo: {total_residuo}")

print("\n=== 2) o que está no lugar dos dados reais")
with e_owner.connect() as c:
    print("   pacientes:", c.execute(text("SELECT name FROM patients LIMIT 2")).scalars().all())
    print("   contatos :", c.execute(text("SELECT name, phone FROM contacts ORDER BY id LIMIT 3")).fetchall())
    print("   mensagem :", c.execute(text("SELECT content FROM messages ORDER BY id LIMIT 1")).scalar())
    print("   agendam. :", c.execute(text("SELECT nome, phone FROM agendamentos ORDER BY id LIMIT 3")).fetchall())

print("\n=== 3) RLS com os dados restaurados (papel de aplicação)")
with e_app.connect() as c:
    print(f"   sem contexto            : {c.execute(text('SELECT count(*) FROM agendamentos')).scalar()} (esperado 0)")
with e_app.begin() as c:
    c.execute(text("SELECT set_config('app.clinic_id', '1', false)"))
    print(f"   contexto da empresa 1   : {c.execute(text('SELECT count(*) FROM agendamentos')).scalar()} (esperado 12)")
with e_app.begin() as c:
    c.execute(text("SELECT set_config('app.clinic_id', '999', false)"))
    print(f"   contexto da empresa 999 : {c.execute(text('SELECT count(*) FROM agendamentos')).scalar()} (esperado 0)")

print("\n=== 4) escrita sem contexto")
try:
    with e_app.begin() as c:
        c.execute(text("""
            INSERT INTO agendamentos (client_id, company_id, lead_id, agendamento_realizado_em, status)
            VALUES (1, 1, (SELECT min(id) FROM leads), now(), 'SCHEDULED')
        """))
    print("   FALHOU: passou sem contexto")
except Exception as exc:  # noqa: BLE001
    print(f"   OK: negado ({type(exc).__name__})")
