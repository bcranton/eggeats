"""Add indexes on businesses.category and mentions.sentiment

Revision ID: 0017
Revises: 0016
Create Date: 2026-03-30
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_businesses_category", "businesses", ["category"])
    op.create_index("ix_mentions_sentiment", "mentions", ["sentiment"])


def downgrade() -> None:
    op.drop_index("ix_mentions_sentiment", "mentions")
    op.drop_index("ix_businesses_category", "businesses")
