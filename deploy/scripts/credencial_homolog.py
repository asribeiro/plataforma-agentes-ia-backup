"""Define a credencial de acesso do homolog (as senhas foram zeradas na anonimização).

O e-mail do dono vale no homolog; a senha é nova, gerada aqui e gravada em arquivo 600 no host.
Ninguém herda senha de produção — os hashes do retrato foram removidos de propósito.
"""
import os
import secrets
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, "/app")

from backend.auth import hash_password  # noqa: E402

URL = os.environ["ALEMBIC_DATABASE_URL"]
BANCO = URL.rsplit("/", 1)[-1]
if not BANCO.endswith("_homolog"):
    print(f"ABORTADO: alvo {BANCO!r} não é homolog")
    sys.exit(1)

EMAIL = "anderson.ribeiro@transformativa.com.br"
ARQ = "/tmp/senha-homolog.txt"

senha = secrets.token_urlsafe(18)
e = create_engine(URL, future=True)

with e.begin() as c:
    # conta master (Client) — é ela que abre a plataforma
    r = c.execute(text("""
        UPDATE clients SET email = :email, password = :senha
         WHERE id = (SELECT min(id) FROM clients)
    """), {"email": EMAIL, "senha": hash_password(senha)})
    print(f"conta master atualizada: {r.rowcount} linha(s)")

    # usuário admin da empresa, para telas que exigem usuário de empresa
    r2 = c.execute(text("""
        UPDATE users SET email = 'admin@homolog.test', password = :senha
         WHERE id = (SELECT min(id) FROM users)
    """), {"senha": hash_password(senha)})
    print(f"usuário admin atualizado: {r2.rowcount} linha(s)")

    print("\n--- como ficou")
    for linha in c.execute(text("SELECT id, email, company_id FROM clients ORDER BY id LIMIT 2")):
        print(f"   client {linha[0]}: {linha[1]} (empresa {linha[2]})")
    for linha in c.execute(text("SELECT id, email, role, company_id FROM users ORDER BY id LIMIT 2")):
        print(f"   user   {linha[0]}: {linha[1]} role={linha[2]} (empresa {linha[3]})")

    print("\n--- estado do dado anonimizado")
    for linha in c.execute(text("SELECT id, nome, phone, status FROM agendamentos ORDER BY id LIMIT 3")):
        print(f"   agendamento {linha[0]}: {linha[1]} / {linha[2]} / {linha[3]}")
    total_msg = c.execute(text("SELECT count(*) FROM messages")).scalar()
    amostra = c.execute(text("SELECT content FROM messages ORDER BY id LIMIT 1")).scalar()
    print(f"   mensagens: {total_msg} | exemplo: {amostra}")

with open(ARQ, "w", encoding="utf-8") as fh:
    fh.write(f"{EMAIL}\t{senha}\n")
os.chmod(ARQ, 0o600)
print(f"\nsenha gravada em {ARQ} (600)")
