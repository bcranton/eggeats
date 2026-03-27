"""Remove ambiguous Toronto keywords that cause false city matches

- 'TO' matches the word 'to' which appears in every English sentence,
  causing the entire transcript to become one giant merged window
- 'Annex' is a common English word (annex a room, annex a building)
- 'GTA' can appear in gaming contexts (Grand Theft Auto)
- Removed 'Portsmouth' from Kingston as it's also a UK city/common word

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove 'TO', 'GTA', and 'Annex' from Toronto keywords
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Toronto,Kensington Market,Queen West,King West,Ossington,Distillery District,Yorkville,Leslieville,Little Italy,Chinatown,Roncesvalles,Parkdale,Liberty Village,Bloor West,North York,Scarborough,Etobicoke,Mississauga,Dundas West'
        WHERE name = 'Toronto' AND country = 'CA'
    """)

    # Remove 'Portsmouth' from Kingston (also a UK city)
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Kingston,Kingston Ontario,K-Town,Queen''s,Queens University,Princess Street,Skeleton Park,Sydenham,Cataraqui'
        WHERE name = 'Kingston' AND country = 'CA'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE cities
        SET search_keywords = 'Toronto,TO,GTA,Kensington Market,Queen West,King West,Ossington,Distillery District,Yorkville,Leslieville,Little Italy,Chinatown,Annex,Roncesvalles,Parkdale,Liberty Village,Bloor West,North York,Scarborough,Etobicoke,Mississauga,Dundas West'
        WHERE name = 'Toronto' AND country = 'CA'
    """)

    op.execute("""
        UPDATE cities
        SET search_keywords = 'Kingston,Kingston Ontario,K-Town,Queen''s,Queens University,Princess Street,Skeleton Park,Sydenham,Portsmouth,Cataraqui'
        WHERE name = 'Kingston' AND country = 'CA'
    """)
