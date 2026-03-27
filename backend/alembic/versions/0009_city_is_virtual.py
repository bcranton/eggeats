"""add is_virtual to cities

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cities",
        sa.Column("is_virtual", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("cities", "is_virtual")
