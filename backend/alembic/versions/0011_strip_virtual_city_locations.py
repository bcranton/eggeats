"""Strip address/lat/lng from businesses assigned to virtual cities

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-28
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE businesses
        SET address = NULL,
            lat = NULL,
            lng = NULL,
            extra_addresses_json = NULL
        WHERE city_id IN (
            SELECT id FROM cities WHERE is_virtual = TRUE
        )
    """)


def downgrade() -> None:
    # Location data is unrecoverable once stripped
    pass
