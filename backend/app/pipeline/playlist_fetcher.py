"""
Fetches video IDs from a YouTube playlist and stores new ones in the database.
Uses YouTube Data API v3.
"""
import logging
from datetime import datetime, timezone

from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Playlist, Video, ProcessingStatus

logger = logging.getLogger(__name__)


def fetch_playlist_videos(db: Session, playlist: Playlist) -> list[str]:
    """
    Fetches all video IDs from the YouTube playlist.
    Inserts any new videos into the DB with status=pending.
    Returns list of newly added youtube_video_ids.
    """
    settings = get_settings()
    youtube = build("youtube", "v3", developerKey=settings.youtube_api_key)

    all_items = []
    next_page_token = None

    while True:
        request = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist.youtube_playlist_id,
            maxResults=50,
            pageToken=next_page_token,
        )
        response = request.execute()
        all_items.extend(response.get("items", []))
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    newly_added = []
    for item in all_items:
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        video_id = content_details.get("videoId") or snippet.get("resourceId", {}).get("videoId")
        if not video_id:
            continue

        # Skip if already known
        existing = db.query(Video).filter(Video.youtube_video_id == video_id).first()
        if existing:
            continue

        title = snippet.get("title", "Unknown Title")
        published_str = snippet.get("publishedAt") or content_details.get("videoPublishedAt")
        published_at = None
        if published_str:
            try:
                published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        video = Video(
            youtube_video_id=video_id,
            playlist_id=playlist.id,
            title=title,
            published_at=published_at,
            processing_status=ProcessingStatus.pending,
        )
        db.add(video)
        newly_added.append(video_id)
        logger.info(f"New video queued: {video_id} - {title}")

    playlist.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"Playlist {playlist.youtube_playlist_id}: {len(newly_added)} new video(s) queued.")
    return newly_added
