"""Add site_settings table

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "site_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    # Seed default: use mapbox
    op.execute("INSERT INTO site_settings (key, value) VALUES ('map_provider', 'mapbox')")


def downgrade():
    op.drop_table("site_settings")
