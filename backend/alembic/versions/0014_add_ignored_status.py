"""Add 'ignored' value to processingstatus enum

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-28
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE processingstatus ADD VALUE IF NOT EXISTS 'ignored'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; leave in place
    pass
