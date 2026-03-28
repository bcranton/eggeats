"""Remove Bellingham city and all associated data

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-28
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM review_queue
        WHERE mention_id IN (
            SELECT m.id FROM mentions m
            JOIN businesses b ON m.business_id = b.id
            JOIN cities c ON b.city_id = c.id
            WHERE c.name = 'Bellingham' AND c.country = 'US'
        )
    """)
    op.execute("""
        DELETE FROM mentions
        WHERE business_id IN (
            SELECT b.id FROM businesses b
            JOIN cities c ON b.city_id = c.id
            WHERE c.name = 'Bellingham' AND c.country = 'US'
        )
    """)
    op.execute("""
        DELETE FROM businesses
        WHERE city_id IN (
            SELECT id FROM cities WHERE name = 'Bellingham' AND country = 'US'
        )
    """)
    op.execute("""
        DELETE FROM playlists
        WHERE city_id IN (
            SELECT id FROM cities WHERE name = 'Bellingham' AND country = 'US'
        )
    """)
    op.execute("DELETE FROM cities WHERE name = 'Bellingham' AND country = 'US'")


def downgrade() -> None:
    op.execute("""
        INSERT INTO cities (name, country, center_lat, center_lng, default_zoom, search_keywords)
        VALUES (
            'Bellingham', 'US', 48.7519, -122.4787, 13,
            'Bellingham,Fairhaven,Whatcom,Barkley,Cordata,Birchwood,Ferndale,Lynden,Mount Vernon,Skagit'
        )
    """)
