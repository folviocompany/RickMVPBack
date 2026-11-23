"""Initial clean ADI schema.

Revision ID: 20261122_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261122_0001"
down_revision = None
branch_labels = None
depends_on = None

status_processamento = postgresql.ENUM(
    "RECEBIDO",
    "EXTRAINDO",
    "MAPEANDO",
    "CONCLUIDO",
    "PARCIAL",
    "ERRO",
    name="status_processamento",
    create_type=False,
)
status_pedido = postgresql.ENUM(
    "PENDENTE",
    "PROCESSANDO",
    "REVISAO",
    "APROVADO",
    "EXPORTADO",
    "ERRO",
    name="status_pedido",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    status_processamento.create(bind, checkfirst=True)
    status_pedido.create(bind, checkfirst=True)

    op.create_table(
        "industria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("cnpj", sa.String(14), nullable=False, unique=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "razao_social",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "industria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("industria.id"),
            nullable=False,
        ),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("cnpj_base", sa.String(8), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_razao_social_industria_id", "razao_social", ["industria_id"])
    op.create_index("ix_razao_social_cnpj_base", "razao_social", ["cnpj_base"])

    op.create_table(
        "cliente",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "razao_social_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("razao_social.id"),
            nullable=False,
        ),
        sa.Column("cnpj", sa.String(14), nullable=False, unique=True),
        sa.Column("nome_fantasia", sa.String(200)),
        sa.Column("bandeira", sa.String(100)),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cliente_razao_social_id", "cliente", ["razao_social_id"])
    op.create_index("ix_cliente_cnpj", "cliente", ["cnpj"], unique=True)

    op.create_table(
        "produto_industria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "industria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("industria.id"),
            nullable=False,
        ),
        sa.Column("codigo", sa.String(50), nullable=False),
        sa.Column("ean", sa.String(14)),
        sa.Column("descricao", sa.String(300), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("industria_id", "codigo"),
    )
    op.create_index("ix_produto_industria_industria_id", "produto_industria", ["industria_id"])
    op.create_index("ix_produto_industria_ean", "produto_industria", ["ean"])

    op.create_table(
        "mapeamento_produto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cliente_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id"), nullable=False
        ),
        sa.Column(
            "produto_industria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("produto_industria.id"),
            nullable=False,
        ),
        sa.Column("codigo_cliente", sa.String(50)),
        sa.Column("ean_cliente", sa.String(14)),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cliente_id", "codigo_cliente"),
        sa.UniqueConstraint("cliente_id", "ean_cliente"),
    )
    op.create_index("ix_mapeamento_produto_cliente_id", "mapeamento_produto", ["cliente_id"])

    op.create_table(
        "processamento",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("arquivo_nome", sa.String(300), nullable=False),
        sa.Column("arquivo_path", sa.String(500), nullable=False),
        sa.Column("status", status_processamento, nullable=False),
        sa.Column("progresso", sa.Integer(), nullable=False),
        sa.Column("mensagem", sa.String(500)),
        sa.Column("erro", sa.Text()),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "pedido",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "processamento_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processamento.id"),
            nullable=False,
        ),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id")),
        sa.Column("numero_pdf", sa.String(100)),
        sa.Column("status", status_pedido, nullable=False),
        sa.Column("prazo_pagamento", sa.String(50)),
        sa.Column("data_emissao", sa.String(20)),
        sa.Column("previsao_entrega", sa.String(20)),
        sa.Column("data_limite_entrega", sa.String(20)),
        sa.Column("condicao_frete", sa.String(30)),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pedido_processamento_id", "pedido", ["processamento_id"])
    op.create_index("ix_pedido_cliente_id", "pedido", ["cliente_id"])

    op.create_table(
        "item_pedido",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pedido_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pedido.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "produto_industria_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("produto_industria.id"),
        ),
        sa.Column("codigo_original", sa.String(50)),
        sa.Column("ean_extraido", sa.String(14)),
        sa.Column("descricao", sa.Text()),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("embalagem_cx", sa.Integer()),
        sa.Column("valor_unitario", sa.Numeric(15, 2)),
        sa.Column("valor_total", sa.Numeric(15, 2)),
        sa.Column("observacao", sa.Text()),
        sa.Column("mapeado", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantidade > 0", name="ck_item_pedido_quantidade_positiva"),
    )
    op.create_index("ix_item_pedido_pedido_id", "item_pedido", ["pedido_id"])


def downgrade() -> None:
    op.drop_table("item_pedido")
    op.drop_table("pedido")
    op.drop_table("processamento")
    op.drop_table("mapeamento_produto")
    op.drop_table("produto_industria")
    op.drop_table("cliente")
    op.drop_table("razao_social")
    op.drop_table("industria")
    bind = op.get_bind()
    status_pedido.drop(bind, checkfirst=True)
    status_processamento.drop(bind, checkfirst=True)
