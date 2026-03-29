"""Add indexes on foreign keys and common filter columns

Revision ID: 0015
Revises: 0014
Create Date: 2026-03-29
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Foreign key indexes (prevent slow seq scans on joins)
    op.create_index("ix_playlists_city_id", "playlists", ["city_id"])
    op.create_index("ix_videos_playlist_id", "videos", ["playlist_id"])
    op.create_index("ix_businesses_city_id", "businesses", ["city_id"])
    op.create_index("ix_mentions_business_id", "mentions", ["business_id"])
    op.create_index("ix_mentions_video_id", "mentions", ["video_id"])
    op.create_index("ix_review_queue_mention_id", "review_queue", ["mention_id"])

    # Common filter/sort columns
    op.create_index("ix_businesses_review_status", "businesses", ["review_status"])
    op.create_index("ix_videos_processing_status", "videos", ["processing_status"])
    op.create_index("ix_videos_published_at", "videos", ["published_at"])
    op.create_index("ix_review_queue_status", "review_queue", ["status"])

    # Composite index for the most common map query
    op.create_index(
        "ix_businesses_review_city",
        "businesses",
        ["review_status", "city_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_businesses_review_city", "businesses")
    op.drop_index("ix_review_queue_status", "review_queue")
    op.drop_index("ix_videos_published_at", "videos")
    op.drop_index("ix_videos_processing_status", "videos")
    op.drop_index("ix_businesses_review_status", "businesses")
    op.drop_index("ix_review_queue_mention_id", "review_queue")
    op.drop_index("ix_mentions_video_id", "mentions")
    op.drop_index("ix_mentions_business_id", "mentions")
    op.drop_index("ix_businesses_city_id", "businesses")
    op.drop_index("ix_videos_playlist_id", "videos")
    op.drop_index("ix_playlists_city_id", "playlists")
