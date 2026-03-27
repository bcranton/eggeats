"""Remove Los Angeles and Seattle cities and all associated data

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-27
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete in dependency order: review_queue → mentions → businesses → playlists → cities
    for city_name in ("Los Angeles", "Seattle"):
        op.execute(f"""
            DELETE FROM review_queue
            WHERE mention_id IN (
                SELECT m.id FROM mentions m
                JOIN businesses b ON m.business_id = b.id
                JOIN cities c ON b.city_id = c.id
                WHERE c.name = '{city_name}' AND c.country = 'US'
            )
        """)
        op.execute(f"""
            DELETE FROM mentions
            WHERE business_id IN (
                SELECT b.id FROM businesses b
                JOIN cities c ON b.city_id = c.id
                WHERE c.name = '{city_name}' AND c.country = 'US'
            )
        """)
        op.execute(f"""
            DELETE FROM businesses
            WHERE city_id IN (
                SELECT id FROM cities WHERE name = '{city_name}' AND country = 'US'
            )
        """)
        op.execute(f"""
            DELETE FROM playlists
            WHERE city_id IN (
                SELECT id FROM cities WHERE name = '{city_name}' AND country = 'US'
            )
        """)
        op.execute(f"DELETE FROM cities WHERE name = '{city_name}' AND country = 'US'")


def downgrade() -> None:
    # Re-insert the cities (without their data — that is unrecoverable)
    op.execute("""
        INSERT INTO cities (name, country, center_lat, center_lng, default_zoom, search_keywords)
        VALUES (
            'Los Angeles', 'US', 34.0522, -118.2437, 11,
            'Los Angeles,Hollywood,West Hollywood,Silver Lake,Echo Park,Koreatown,DTLA,Santa Monica,Venice,Culver City,Pasadena,Burbank,Glendale,Sherman Oaks,Studio City'
        )
    """)
    op.execute("""
        INSERT INTO cities (name, country, center_lat, center_lng, default_zoom, search_keywords)
        VALUES (
            'Seattle', 'US', 47.6062, -122.3321, 12,
            'Seattle,Capitol Hill,Fremont,Ballard,Queen Anne,Belltown,Pioneer Square,South Lake Union,Eastlake,Wallingford,Redmond,Bellevue,Kirkland,Tacoma'
        )
    """)
