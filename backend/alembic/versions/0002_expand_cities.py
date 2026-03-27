"""Expand default cities: Metro Vancouver suburbs + Orlando, LA, Seattle, Bellingham

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand Vancouver keywords to include Burnaby and key Metro Vancouver suburbs
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Vancouver,Van,YVR,Vangroover,Burnaby,Richmond,Surrey,Coquitlam,North Vancouver,West Vancouver,New Westminster,Langley,Delta,Metrotown,Lougheed,Brentwood,Steveston'
        WHERE name = 'Vancouver' AND country = 'CA'
    """)

    # Add Orlando, FL
    op.execute("""
        INSERT INTO cities (name, country, search_keywords, center_lat, center_lng, default_zoom)
        VALUES (
            'Orlando',
            'US',
            'Orlando,Disney,Disney World,Universal,Sea World,Orange County,Lake Buena Vista,Celebration,Kissimmee,Windermere',
            28.5383,
            -81.3792,
            12
        )
        ON CONFLICT DO NOTHING
    """)

    # Add Los Angeles, CA
    op.execute("""
        INSERT INTO cities (name, country, search_keywords, center_lat, center_lng, default_zoom)
        VALUES (
            'Los Angeles',
            'US',
            'Los Angeles,LA,Hollywood,West Hollywood,Silver Lake,Echo Park,Koreatown,DTLA,Santa Monica,Venice,Culver City,Pasadena,Burbank,Glendale,Sherman Oaks,Studio City',
            34.0522,
            -118.2437,
            11
        )
        ON CONFLICT DO NOTHING
    """)

    # Add Seattle, WA
    op.execute("""
        INSERT INTO cities (name, country, search_keywords, center_lat, center_lng, default_zoom)
        VALUES (
            'Seattle',
            'US',
            'Seattle,Capitol Hill,Fremont,Ballard,Queen Anne,Belltown,Pioneer Square,South Lake Union,Eastlake,Wallingford,Redmond,Bellevue,Kirkland,Tacoma',
            47.6062,
            -122.3321,
            12
        )
        ON CONFLICT DO NOTHING
    """)

    # Add Bellingham, WA
    op.execute("""
        INSERT INTO cities (name, country, search_keywords, center_lat, center_lng, default_zoom)
        VALUES (
            'Bellingham',
            'US',
            'Bellingham,Fairhaven,Whatcom,Barkley,Cordata,Birchwood,Ferndale,Lynden,Mount Vernon,Skagit',
            48.7519,
            -122.4787,
            13
        )
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    # Revert Vancouver keywords
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Vancouver,Van,YVR,Vangroover'
        WHERE name = 'Vancouver' AND country = 'CA'
    """)

    # Remove added cities
    op.execute("DELETE FROM cities WHERE name IN ('Orlando', 'Los Angeles', 'Seattle', 'Bellingham') AND country = 'US'")
