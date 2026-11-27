"""Persist Extracta reports without changing legacy orders.

Revision ID: 20261126_0003
Revises: 20261122_0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261126_0003"
down_revision = "20261122_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "extracta_lote",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_extracta_lote_criado_em", "extracta_lote", ["criado_em"])


def downgrade():
    op.drop_table("extracta_lote")
