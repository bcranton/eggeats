"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("country", sa.String(10), nullable=False),
        sa.Column("search_keywords", sa.Text, nullable=False),
        sa.Column("center_lat", sa.Float, nullable=False),
        sa.Column("center_lng", sa.Float, nullable=False),
        sa.Column("default_zoom", sa.Integer, default=12),
    )

    op.create_table(
        "playlists",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("youtube_playlist_id", sa.String(100), unique=True, nullable=False),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("last_checked_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("youtube_video_id", sa.String(20), unique=True, nullable=False),
        sa.Column("playlist_id", sa.Integer, sa.ForeignKey("playlists.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("transcript_raw", sa.Text, nullable=True),
        sa.Column("transcript_fetched_at", sa.DateTime, nullable=True),
        sa.Column(
            "processing_status",
            sa.Enum("pending", "processing", "completed", "failed", "skipped",
                    name="processingstatus"),
            default="pending",
        ),
        sa.Column("processed_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "businesses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("google_place_id", sa.String(255), unique=True, nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("is_closed", sa.Boolean, default=False),
        sa.Column(
            "review_status",
            sa.Enum("approved", "pending_review", "rejected", name="reviewstatus"),
            default="pending_review",
        ),
        sa.Column("admin_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "mentions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("business_id", sa.Integer, sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("video_id", sa.Integer, sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("timestamp_seconds", sa.Integer, nullable=True),
        sa.Column("raw_business_name", sa.String(255), nullable=False),
        sa.Column("transcript_excerpt", sa.Text, nullable=True),
        sa.Column(
            "sentiment",
            sa.Enum("positive", "negative", "neutral", "mixed", name="sentiment"),
            nullable=True,
        ),
        sa.Column("sentiment_score", sa.Float, nullable=True),
        sa.Column("quotes_json", sa.Text, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("needs_review", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "review_queue",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mention_id", sa.Integer, sa.ForeignKey("mentions.id"), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "resolved", "dismissed", name="reviewqueuestatus"),
            default="pending",
        ),
        sa.Column("suggested_correction", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Seed initial data
    op.execute("""
        INSERT INTO cities (name, country, search_keywords, center_lat, center_lng, default_zoom)
        VALUES ('Vancouver', 'CA', 'Vancouver,Van,YVR,Vangroover', 49.2827, -123.1207, 12)
    """)

    op.execute("""
        INSERT INTO playlists (youtube_playlist_id, city_id, name)
        VALUES (
            'PLvswIqZLpR-VpoMuxzO9oT3F9-FtHScpn',
            (SELECT id FROM cities WHERE name = 'Vancouver'),
            'Northernlion Vancouver Videos'
        )
    """)


def downgrade() -> None:
    op.drop_table("admin_sessions")
    op.drop_table("review_queue")
    op.drop_table("mentions")
    op.drop_table("businesses")
    op.drop_table("videos")
    op.drop_table("playlists")
    op.drop_table("cities")

    op.execute("DROP TYPE IF EXISTS processingstatus")
    op.execute("DROP TYPE IF EXISTS reviewstatus")
    op.execute("DROP TYPE IF EXISTS sentiment")
    op.execute("DROP TYPE IF EXISTS reviewqueuestatus")
