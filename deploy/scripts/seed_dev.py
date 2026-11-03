"""Seed mínimo do ambiente de desenvolvimento.

Cria empresa, conta master (Client) e usuário admin da empresa. Idempotente: rodar de novo não duplica.
Conecta como OWNER (ALEMBIC_DATABASE_URL) porque isto é setup de ambiente, não operação da aplicação.

A senha gerada NÃO é impressa: vai para /etc/plataforma-agentes/app-dev/senha-dev.txt (600).
"""
import os
import secrets
import sys

sys.path.insert(0, "/app")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.auth import hash_password  # noqa: E402
from backend.models import Client, Company, User  # noqa: E402

URL = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ["DATABASE_URL"]
EMAIL_MASTER = "anderson.ribeiro@transformativa.com.br"
EMAIL_ADMIN = "admin@dev.local"
SENHA_ARQUIVO = "/tmp/senha-dev.txt"

engine = create_engine(URL, future=True)
Sessao = sessionmaker(bind=engine, future=True, expire_on_commit=False)

CNPJ_DEV = "00000000000100"

with Sessao() as db:
    empresa = db.query(Company).filter(Company.cnpj == CNPJ_DEV).one_or_none()
    if empresa is None:
        empresa = Company(
            name="Clínica Demo (dev)",
            name_company="Clínica Demo (dev)",
            cnpj=CNPJ_DEV,
            city="Campinas",
            state="SP",
            operational_status="active",
        )
        db.add(empresa)
        db.commit()
        print(f"empresa criada: id={empresa.id}")
    else:
        print(f"empresa já existia: id={empresa.id}")

    master = db.query(Client).filter(Client.email == EMAIL_MASTER).one_or_none()
    senha_master = None
    if master is None:
        senha_master = secrets.token_urlsafe(18)
        master = Client(
            email=EMAIL_MASTER,
            password=hash_password(senha_master),
            company_id=empresa.id,
            ownership_company_id=empresa.id,
            is_active=True,
        )
        db.add(master)
        db.commit()
        print(f"conta master criada: id={master.id} email={EMAIL_MASTER}")
    else:
        print(f"conta master já existia: id={master.id} email={master.email}")

    admin = db.query(User).filter(User.email == EMAIL_ADMIN).one_or_none()
    senha_admin = None
    if admin is None:
        senha_admin = secrets.token_urlsafe(18)
        admin = User(
            email=EMAIL_ADMIN,
            password=hash_password(senha_admin),
            name="Admin Dev",
            role="admin",
            client_id=master.id,
            company_id=empresa.id,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"usuário admin criado: id={admin.id} email={EMAIL_ADMIN}")
    else:
        print(f"usuário admin já existia: id={admin.id}")

    # conferência final (o que o frontend vai encontrar no login)
    print("\n--- estado do seed")
    print(f"  empresa : id={empresa.id} nome={empresa.name!r} cnpj={empresa.cnpj}")
    print(f"  master  : id={master.id} email={master.email} ativo={master.is_active}")
    print(f"  admin   : id={admin.id} email={admin.email} role={admin.role} ativo={admin.is_active}")
    print(f"  senhas  : {'geradas' if (senha_master or senha_admin) else 'já existiam (não alteradas)'}")

if senha_master or senha_admin:
    with open(SENHA_ARQUIVO, "w", encoding="utf-8") as fh:
        if senha_master:
            fh.write(f"{EMAIL_MASTER}\t{senha_master}\n")
        if senha_admin:
            fh.write(f"{EMAIL_ADMIN}\t{senha_admin}\n")
    os.chmod(SENHA_ARQUIVO, 0o600)
    print(f"\nsenhas gravadas em {SENHA_ARQUIVO} (600)")
