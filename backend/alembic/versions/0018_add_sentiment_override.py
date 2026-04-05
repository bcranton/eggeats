"""Add sentiment_override to businesses

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("sentiment_override", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("businesses", "sentiment_override")
