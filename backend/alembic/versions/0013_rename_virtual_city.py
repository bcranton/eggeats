"""Rename virtual city from 'No Fixed Location' to 'Multiple Locations & Other'

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-28
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE cities
        SET name = 'Multiple Locations & Other'
        WHERE is_virtual = TRUE AND name = 'No Fixed Location'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE cities
        SET name = 'No Fixed Location'
        WHERE is_virtual = TRUE AND name = 'Multiple Locations & Other'
    """)
