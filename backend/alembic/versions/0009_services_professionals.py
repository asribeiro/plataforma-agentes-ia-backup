"""services, professionals, professional_services e vinculos de agenda

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-28

Modelo de agenda inteligente por profissional. Decisoes de 28/10:
  - 1 profissional = 1 agenda (unique parcial onde professional_id nao e nulo)
  - preco opcional no catalogo (price_cents nulo = agente nao cita valor)
  - avaliacao de diagnostico e servico de primeira classe (is_evaluation)

IMPORTANTE — porque as colunas nascem NULLABLE:

  agendas.professional_id e company_slots.agenda_id NAO podem ser NOT NULL nesta
  migration. Duas razoes concretas, ambas verificadas no codigo:

  1. As rotas de CRUD de agenda criam Agenda sem professional_id. NOT NULL
     quebraria a criacao de agenda no mesmo deploy.
  2. A task periodica update_all_companies_availabilities
     (backend/worker/tasks_scheduling.py) faz INSERT em company_slots sem
     agenda_id. NOT NULL quebraria a atualizacao de disponibilidade de todas
     as empresas, silenciosamente, no ciclo de 5 minutos.

  O vinculo 1:1 e garantido pelo indice unico parcial
  uq_agendas_professional_active (WHERE active IS TRUE), que aceita varios NULL
  mas impede dois registros ativos para o mesmo profissional. A promocao para
  NOT NULL fica para a migration que ajustar o codigo criador.
"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------- services
    op.create_table(
        'services',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False,
                  server_default=sa.text('30')),
        sa.Column('price_cents', sa.Integer(), nullable=True),
        sa.Column('is_evaluation', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('active', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'name', name='uq_services_company_name'),
    )
    op.create_index('idx_services_company_active', 'services', ['company_id', 'active'])
    op.create_index('idx_services_evaluation', 'services', ['company_id', 'is_evaluation'])

    # ----------------------------------------------------------- professionals
    op.create_table(
        'professionals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('cro', sa.String(length=30), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'email', name='uq_professionals_company_email'),
    )
    op.create_index('idx_professionals_company_active', 'professionals',
                    ['company_id', 'active'])

    # ----------------------------------------------------- professional_services
    op.create_table(
        'professional_services',
        sa.Column('professional_id', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('duration_override_minutes', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['professional_id'], ['professionals.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('professional_id', 'service_id'),
    )
    op.create_index('idx_professional_services_service', 'professional_services',
                    ['service_id'])

    # --------------------------------------------------- agendas.professional_id
    op.add_column('agendas', sa.Column('professional_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_agendas_professional', 'agendas', 'professionals',
        ['professional_id'], ['id'], ondelete='RESTRICT',
    )
    # 1:1 garantido aqui: aceita varios NULL, impede dois ativos pro mesmo profissional
    op.create_index(
        'uq_agendas_professional_active', 'agendas', ['professional_id'],
        unique=True, postgresql_where=sa.text('active IS TRUE AND professional_id IS NOT NULL'),
    )

    # -------------------------------------------------------- company_slots
    op.add_column('company_slots', sa.Column('agenda_id', sa.Integer(), nullable=True))
    op.add_column('company_slots', sa.Column('service_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_company_slots_agenda', 'company_slots', 'agendas',
        ['agenda_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_company_slots_service', 'company_slots', 'services',
        ['service_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('idx_company_slots_agenda_date', 'company_slots',
                    ['agenda_id', 'slot_date', 'is_available'])

    # --------------------------------------------------------- agendamentos
    # NAO adicionar google_event_id/google_calendar_id: o modelo ja tem
    # event_id (String 255) e google_calendar_id (String 255). Faltam apenas o
    # servico e a prova de que o convite saiu.
    op.add_column('agendamentos', sa.Column('service_id', sa.Integer(), nullable=True))
    op.add_column('agendamentos', sa.Column('invite_sent_at',
                                            sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_agendamentos_service', 'agendamentos', 'services',
        ['service_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('idx_agendamentos_invite', 'agendamentos', ['invite_sent_at'])

    # ------------------------------------------------- backfill: servico Avaliacao
    # Cria "Avaliacao" para toda empresa que ja tenha agenda ativa. Hoje isso e
    # no-op (producao com 0 agendas), mas protege qualquer ambiente com dados.
    op.execute(sa.text("""
        INSERT INTO services (company_id, name, duration_minutes, is_evaluation, active)
        SELECT DISTINCT a.company_id, 'Avaliação', 30, true, true
          FROM agendas a
         WHERE a.active IS TRUE
           AND NOT EXISTS (
               SELECT 1 FROM services s
                WHERE s.company_id = a.company_id
                  AND s.is_evaluation IS TRUE
           )
    """))


def downgrade() -> None:
    op.drop_index('idx_agendamentos_invite', table_name='agendamentos')
    op.drop_constraint('fk_agendamentos_service', 'agendamentos', type_='foreignkey')
    op.drop_column('agendamentos', 'invite_sent_at')
    op.drop_column('agendamentos', 'service_id')

    op.drop_index('idx_company_slots_agenda_date', table_name='company_slots')
    op.drop_constraint('fk_company_slots_service', 'company_slots', type_='foreignkey')
    op.drop_constraint('fk_company_slots_agenda', 'company_slots', type_='foreignkey')
    op.drop_column('company_slots', 'service_id')
    op.drop_column('company_slots', 'agenda_id')

    op.drop_index('uq_agendas_professional_active', table_name='agendas')
    op.drop_constraint('fk_agendas_professional', 'agendas', type_='foreignkey')
    op.drop_column('agendas', 'professional_id')

    op.drop_index('idx_professional_services_service', table_name='professional_services')
    op.drop_table('professional_services')

    op.drop_index('idx_professionals_company_active', table_name='professionals')
    op.drop_table('professionals')

    op.drop_index('idx_services_evaluation', table_name='services')
    op.drop_index('idx_services_company_active', table_name='services')
    op.drop_table('services')
