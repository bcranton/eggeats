"""Add extra_addresses_json to businesses

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("extra_addresses_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("businesses", "extra_addresses_json")
