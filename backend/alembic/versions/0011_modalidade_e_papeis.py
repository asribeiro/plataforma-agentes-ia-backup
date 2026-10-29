"""modalidade da clinica por limite e papeis de acesso

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-29

Substitui o booleano `companies.multi_professional_enabled` (0010) pelas duas
colunas que a decisao de 29/10 exige e cria a base dos quatro papeis.

1. companies.professional_tier + companies.max_professionals
   Tres modalidades: mono (1), up_to_4 (1 a 4), up_to_10 (5 a 10).
   Quem escolhe e o admin da PLATAFORMA, nunca o cliente. O rotulo comercial
   (tier) e a regra de negocio (numero) ficam separados de proposito: mudar a
   faixa de "5 a 10" para "5 a 12" nao exige migration nova nem altera codigo.
   Backfill: flag TRUE -> up_to_4, flag FALSE -> mono.

2. SANEAMENTO DO BACKFILL (guarda de consistencia)
   A regra "FALSE -> mono" foi escrita antes de olhar os dados. Se uma empresa
   com a flag FALSE tiver mais profissionais ATIVOS do que a faixa comporta, o
   backfill ao pe da letra deixaria o banco contradizendo a si mesmo: uma
   clinica "monoprofissional" com dois profissionais ativos, e o segundo
   bloqueado para sempre. Por isso, depois do backfill, o limite e ELEVADO
   quando a contagem real de profissionais ativos nao cabe na faixa. O limite
   nunca fica menor do que o numero de profissionais que ja existem.
   MEDIDO NA PRODUCAO antes de aplicar (29/10): a unica empresa tem flag FALSE e
   2 profissionais cadastrados, AMBOS INATIVOS. O saneamento nao disparou ali —
   a empresa ficou mono/1, que e o correto — e existe como guarda para qualquer
   base com ativos de verdade. Profissional inativo nao ocupa vaga.
   Caso a empresa tenha mais de 10 ativos, ela fica em up_to_10 (o teto das
   modalidades) e o cadastro novo e bloqueado pela rota — o dado existente nao
   e apagado.

3. Remocao do booleano
   A coluna sai nesta migration porque passaria a mentir: duas fontes de
   verdade para a mesma decisao. As rotas company_flag_routes e
   professionals_routes passam a ler professional_tier / max_professionals no
   MESMO deploy — sem isso elas quebram.
   CUSTO DO DOWNGRADE, declarado: ele reconstroi o booleano a partir da
   modalidade (tier <> 'mono' -> true). Uma clinica que estava com flag FALSE e
   foi saneada para up_to_4 volta do downgrade como TRUE. O booleano nao tem
   como representar "mono com dois profissionais" — e essa impossibilidade e
   justamente o motivo de a 0011 existir.

4. users.professional_id + papeis
   `users.role` cresce de 20 para 30 caracteres: 'clinical_professional' tem 21
   e nao cabia. Os valores novos sao clinic_admin, clinical_professional e
   service_professional, somados ao legado (admin, manager, staff) — o CHECK
   aceita a uniao para nao quebrar usuario existente.
   O CHECK ck_users_papel_clinico_tem_profissional exige professional_id nos
   dois papeis clinicos: sem esse vinculo o sistema nao sabe qual profissional
   e o usuario logado e a regra de "so os seus pacientes" nao existe.

5. clinical_access_log
   O Admin Clinica ve o prontuario de toda a clinica (decisao de 29/10). A
   contrapartida e este log. patient_id e professional_id ficam SEM foreign key
   de proposito: o registro precisa sobreviver a exclusao do paciente e do
   profissional, e FK com ON DELETE SET NULL apagaria o dado que se quer
   preservar. user_id tem FK e user_email guarda o snapshot.
   Neste stack paciente = contacts.id; nao existe tabela `patients`.
"""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------- modalidade da clinica
    op.add_column(
        'companies',
        sa.Column('professional_tier', sa.String(length=20), nullable=False,
                  server_default=sa.text("'mono'")),
    )
    op.add_column(
        'companies',
        sa.Column('max_professionals', sa.Integer(), nullable=False,
                  server_default=sa.text('1')),
    )
    op.create_check_constraint(
        'ck_companies_professional_tier', 'companies',
        "professional_tier IN ('mono', 'up_to_4', 'up_to_10')",
    )
    op.create_check_constraint(
        'ck_companies_max_professionals', 'companies', 'max_professionals > 0',
    )

    # backfill a partir do booleano da 0010
    op.execute(sa.text("""
        UPDATE companies
           SET professional_tier = 'up_to_4',
               max_professionals = 4
         WHERE multi_professional_enabled IS TRUE
    """))

    # saneamento: o limite nunca pode ser menor do que a equipe que ja existe
    op.execute(sa.text("""
        UPDATE companies c
           SET professional_tier = 'up_to_4',
               max_professionals  = 4
         WHERE (SELECT count(*) FROM professionals p
                 WHERE p.company_id = c.id AND p.active IS TRUE) BETWEEN 2 AND 4
    """))
    op.execute(sa.text("""
        UPDATE companies c
           SET professional_tier = 'up_to_10',
               max_professionals  = 10
         WHERE (SELECT count(*) FROM professionals p
                 WHERE p.company_id = c.id AND p.active IS TRUE) > 4
    """))

    # duas fontes de verdade para a mesma decisao -> remove o booleano
    op.drop_column('companies', 'multi_professional_enabled')

    # ------------------------------------------------------- papeis de acesso
    op.alter_column(
        'users', 'role',
        existing_type=sa.String(length=20),
        type_=sa.String(length=30),
        existing_nullable=False,
        existing_server_default='staff',
    )
    op.add_column('users', sa.Column('professional_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_users_professional', 'users', 'professionals',
        ['professional_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('idx_users_professional', 'users', ['professional_id'])
    op.create_check_constraint(
        'ck_users_role_valido', 'users',
        "role IN ('admin', 'manager', 'staff', 'clinic_admin', "
        "'clinical_professional', 'service_professional')",
    )
    op.create_check_constraint(
        'ck_users_papel_clinico_tem_profissional', 'users',
        "role NOT IN ('clinical_professional', 'service_professional') "
        "OR professional_id IS NOT NULL",
    )

    # --------------------------------------------- registro de acesso clinico
    op.create_table(
        'clinical_access_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_email', sa.String(length=255), nullable=False),
        sa.Column('professional_id', sa.Integer(), nullable=True),
        sa.Column('patient_id', sa.Integer(), nullable=True),
        sa.Column('resource', sa.String(length=40), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False,
                  server_default=sa.text("'read'")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_clinical_access_company_data', 'clinical_access_log',
                    ['company_id', 'created_at'])
    op.create_index('idx_clinical_access_patient', 'clinical_access_log',
                    ['patient_id', 'created_at'])
    op.create_index('idx_clinical_access_user', 'clinical_access_log',
                    ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('idx_clinical_access_user', table_name='clinical_access_log')
    op.drop_index('idx_clinical_access_patient', table_name='clinical_access_log')
    op.drop_index('idx_clinical_access_company_data', table_name='clinical_access_log')
    op.drop_table('clinical_access_log')

    op.drop_constraint('ck_users_papel_clinico_tem_profissional', 'users',
                       type_='check')
    op.drop_constraint('ck_users_role_valido', 'users', type_='check')
    op.drop_index('idx_users_professional', table_name='users')
    op.drop_constraint('fk_users_professional', 'users', type_='foreignkey')
    op.drop_column('users', 'professional_id')
    # A coluna volta para 20 caracteres, e 'clinical_professional' tem 21.
    # Sem este passo o ALTER TYPE estoura com "value too long" e o downgrade
    # para no meio. Perda declarada: os papeis novos viram equivalentes legados.
    op.execute(sa.text("""
        UPDATE users
           SET role = CASE role
                        WHEN 'clinic_admin' THEN 'admin'
                        ELSE 'staff'
                      END
         WHERE role IN ('clinic_admin', 'clinical_professional',
                        'service_professional')
    """))
    op.alter_column(
        'users', 'role',
        existing_type=sa.String(length=30),
        type_=sa.String(length=20),
        existing_nullable=False,
        existing_server_default='staff',
    )

    # volta o booleano da 0010 e repovoa a partir da modalidade
    op.add_column(
        'companies',
        sa.Column('multi_professional_enabled', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
    )
    op.execute(sa.text("""
        UPDATE companies SET multi_professional_enabled = true
         WHERE professional_tier <> 'mono'
    """))
    op.drop_constraint('ck_companies_max_professionals', 'companies', type_='check')
    op.drop_constraint('ck_companies_professional_tier', 'companies', type_='check')
    op.drop_column('companies', 'max_professionals')
    op.drop_column('companies', 'professional_tier')
