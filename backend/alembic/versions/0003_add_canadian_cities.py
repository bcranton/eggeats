"""Add Kingston Ontario and Toronto

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add Kingston, Ontario
    op.execute("""
        INSERT INTO cities (name, country, search_keywords, center_lat, center_lng, default_zoom)
        VALUES (
            'Kingston',
            'CA',
            'Kingston,Kingston Ontario,K-Town,Queen''s,Queens University,Princess Street,Skeleton Park,Sydenham,Portsmouth,Cataraqui',
            44.2312,
            -76.4860,
            13
        )
        ON CONFLICT DO NOTHING
    """)

    # Add Toronto, Ontario
    op.execute("""
        INSERT INTO cities (name, country, search_keywords, center_lat, center_lng, default_zoom)
        VALUES (
            'Toronto',
            'CA',
            'Toronto,TO,GTA,Kensington Market,Queen West,King West,Ossington,Distillery District,Yorkville,Leslieville,Little Italy,Chinatown,Annex,Roncesvalles,Parkdale,Liberty Village,Bloor West,North York,Scarborough,Etobicoke,Mississauga,Dundas West',
            43.6532,
            -79.3832,
            12
        )
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM cities WHERE name IN ('Kingston', 'Toronto') AND country = 'CA'")
