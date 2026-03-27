"""Remove ambiguous short keywords that cause false city matches

- Remove 'LA' from Los Angeles keywords: two letters match too many
  words ('la grotta', 'large', 'salami', 'place', etc.)
- Remove 'Van' from Vancouver keywords: matches 'advantage', 'vanilla',
  etc. 'Vancouver' and other full names are sufficient.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove 'LA' from Los Angeles — too short, matches unrelated words
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Los Angeles,Hollywood,West Hollywood,Silver Lake,Echo Park,Koreatown,DTLA,Santa Monica,Venice,Culver City,Pasadena,Burbank,Glendale,Sherman Oaks,Studio City'
        WHERE name = 'Los Angeles' AND country = 'US'
    """)

    # Remove 'Van' from Vancouver — matches too many common words
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Vancouver,YVR,Vangroover,Burnaby,Richmond,Surrey,Coquitlam,North Vancouver,West Vancouver,New Westminster,Langley,Delta,Metrotown,Lougheed,Brentwood,Steveston'
        WHERE name = 'Vancouver' AND country = 'CA'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Los Angeles,LA,Hollywood,West Hollywood,Silver Lake,Echo Park,Koreatown,DTLA,Santa Monica,Venice,Culver City,Pasadena,Burbank,Glendale,Sherman Oaks,Studio City'
        WHERE name = 'Los Angeles' AND country = 'US'
    """)

    op.execute("""
        UPDATE cities
        SET search_keywords = 'Vancouver,Van,YVR,Vangroover,Burnaby,Richmond,Surrey,Coquitlam,North Vancouver,West Vancouver,New Westminster,Langley,Delta,Metrotown,Lougheed,Brentwood,Steveston'
        WHERE name = 'Vancouver' AND country = 'CA'
    """)
