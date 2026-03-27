"""Move Vancouver default map center slightly south

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE cities
        SET center_lat = 49.22
        WHERE name = 'Vancouver' AND country = 'CA'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE cities
        SET center_lat = 49.2827
        WHERE name = 'Vancouver' AND country = 'CA'
    """)
