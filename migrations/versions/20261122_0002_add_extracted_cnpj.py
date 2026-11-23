"""Store the CNPJ extracted from each order.

Revision ID: 20261122_0002
Revises: 20261122_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20261122_0002"
down_revision = "20261122_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pedido", sa.Column("cnpj_extraido", sa.String(14), nullable=True))


def downgrade() -> None:
    op.drop_column("pedido", "cnpj_extraido")
