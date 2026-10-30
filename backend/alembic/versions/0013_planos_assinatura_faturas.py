"""Planos, assinatura por empresa e faturas (bloco cobranca)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30

POR QUE ESTA MIGRATION EXISTE

Nao havia nada de cobranca neste banco: nem plano, nem contrato, nem fatura. O unico
dado comercial era `companies.professional_tier` — o LIMITE TECNICO de profissionais
(migration 0011), que nao diz quanto o cliente paga.

Tres decisoes do dono (30/10) moldam o desenho:

1. O REGISTRO e manual; a cobranca de verdade e feita por parceiro com plataforma de
   pagamento. Entao este banco guarda o que foi combinado e o que foi quitado — nao
   conversa com adquirente, nao tem token de gateway, nao trata webhook.
2. A fatura e MENSAL, uma por competencia, e o valor que interessa e o do plano: e o
   numero que o parceiro debita no cartao. Por isso `faturas.valor_centavos` e
   SNAPSHOT — copia do preco no momento da emissao. Mudar o preco do plano depois
   nao pode reescrever o passado; se reescrevesse, o historico viraria ficcao.
3. PLANO e MODALIDADE sao coisas diferentes, ligadas pela faixa: Consultorio = 1
   profissional, Clinica = ate 4, Clinica Plus = ate 10. A modalidade continua sendo
   o teto TECNICO (`companies.max_professionals`); o plano e o comercial. Separar
   permite vender o mesmo teto com preco diferente (promocao, anual) sem duplicar
   limite.

`preco_centavos` nasce NULO de proposito: preco combinado caso a caso, e o sistema
recusa emitir fatura de plano sem preco em vez de emitir com zero.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLANOS = (
    ("Plano Consultorio", "mono"),
    ("Plano Clinica", "up_to_4"),
    ("Plano Clinica Plus", "up_to_10"),
)


def _existe(tabela: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(tabela)


def upgrade() -> None:
    # ------------------------------------------------------------------ planos
    if not _existe("planos"):
        op.create_table(
            "planos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nome", sa.String(80), nullable=False),
            sa.Column("tier", sa.String(20), nullable=False),
            sa.Column("preco_centavos", sa.Integer(), nullable=True),
            sa.Column("ciclo", sa.String(20), nullable=False, server_default="mensal"),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("nome", name="uq_planos_nome"),
            sa.CheckConstraint(
                "tier IN ('mono','up_to_4','up_to_10')",
                name="ck_planos_tier",
            ),
            sa.CheckConstraint(
                "preco_centavos IS NULL OR preco_centavos >= 0",
                name="ck_planos_preco_nao_negativo",
            ),
        )
        op.create_index("ix_planos_tier", "planos", ["tier"])

    # ------------------------------------------------------------- assinaturas
    if not _existe("company_assinaturas"):
        op.create_table(
            "company_assinaturas",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "company_id",
                sa.BigInteger(),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "plano_id",
                sa.Integer(),
                sa.ForeignKey("planos.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("status", sa.String(20), nullable=False, server_default="ativa"),
            sa.Column("dia_vencimento", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("inicio", sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column("observacao", sa.Text(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint(
                "status IN ('ativa','suspensa','encerrada')",
                name="ck_assinatura_status",
            ),
            # Dia 29-31 em todo mes e armadilha de calendario: fevereiro nao tem.
            sa.CheckConstraint(
                "dia_vencimento BETWEEN 1 AND 28",
                name="ck_assinatura_dia_vencimento",
            ),
        )
        op.create_index("ix_assinatura_company", "company_assinaturas", ["company_id"])
        # Uma assinatura ATIVA por empresa. Encerradas ficam no historico.
        op.execute(
            "CREATE UNIQUE INDEX uq_assinatura_ativa_por_empresa "
            "ON company_assinaturas (company_id) WHERE status = 'ativa'"
        )

    # ---------------------------------------------------------------- faturas
    if not _existe("faturas"):
        op.create_table(
            "faturas",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "company_id",
                sa.BigInteger(),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "assinatura_id",
                sa.Integer(),
                sa.ForeignKey("company_assinaturas.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("competencia", sa.String(7), nullable=False),
            # Snapshot do preco na emissao: nao acompanha mudanca de plano.
            sa.Column("valor_centavos", sa.Integer(), nullable=False),
            sa.Column("vencimento", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="aberta"),
            sa.Column("pago_em", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("observacao", sa.Text(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("company_id", "competencia", name="uq_fatura_competencia"),
            sa.CheckConstraint(
                "status IN ('aberta','paga','cancelada')",
                name="ck_faturas_status",
            ),
            sa.CheckConstraint(
                "competencia ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'",
                name="ck_faturas_competencia",
            ),
            sa.CheckConstraint("valor_centavos >= 0", name="ck_faturas_valor"),
        )
        op.create_index("ix_faturas_company_competencia", "faturas", ["company_id", "competencia"])
        op.create_index("ix_faturas_status", "faturas", ["status"])

    # Semeia o catalogo (idempotente: nome e unico).
    conexao = op.get_bind()
    for nome, tier in PLANOS:
        conexao.execute(
            sa.text(
                "INSERT INTO planos (nome, tier, preco_centavos, ciclo, ativo) "
                "SELECT :nome, :tier, NULL, 'mensal', true "
                "WHERE NOT EXISTS (SELECT 1 FROM planos WHERE nome = :nome)"
            ),
            {"nome": nome, "tier": tier},
        )


def downgrade() -> None:
    # Ordem inversa por causa das FKs: fatura -> assinatura -> plano.
    if _existe("faturas"):
        op.drop_index("ix_faturas_status", table_name="faturas")
        op.drop_index("ix_faturas_company_competencia", table_name="faturas")
        op.drop_table("faturas")
    if _existe("company_assinaturas"):
        op.execute("DROP INDEX IF EXISTS uq_assinatura_ativa_por_empresa")
        op.drop_index("ix_assinatura_company", table_name="company_assinaturas")
        op.drop_table("company_assinaturas")
    if _existe("planos"):
        op.drop_index("ix_planos_tier", table_name="planos")
        op.drop_table("planos")
