"""
Main pipeline orchestrator.
Processes videos end-to-end: transcript → LLM extraction → geocoding → DB storage.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Business, City, Mention, Playlist, ProcessingStatus,
    ReviewQueue, ReviewQueueStatus, ReviewStatus, Sentiment, Video,
)
from app.pipeline.playlist_fetcher import fetch_playlist_videos
from app.pipeline.transcript_fetcher import (
    fetch_transcript, find_keyword_windows, get_cached_transcript,
)
from app.pipeline.llm_extractor import extract_businesses_from_video
from app.pipeline.geocoder import geocode_business

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Business upsert helpers
# ---------------------------------------------------------------------------

def _get_or_create_business(
    db: Session,
    geocode_result: dict,
    city: City,
) -> tuple[Business, bool]:
    """
    Finds an existing business by google_place_id or creates a new one.
    Returns (business, created).
    """
    place_id = geocode_result.get("google_place_id")

    # Try match by Place ID first
    if place_id:
        existing = db.query(Business).filter(Business.google_place_id == place_id).first()
        if existing:
            return existing, False

    # Fuzzy name match within same city (simple case-insensitive match)
    name = geocode_result.get("name", "")
    if name:
        existing = (
            db.query(Business)
            .filter(
                Business.city_id == city.id,
                Business.name.ilike(name),
            )
            .first()
        )
        if existing:
            # Update place_id if we now have one
            if place_id and not existing.google_place_id:
                existing.google_place_id = place_id
                db.commit()
            return existing, False

    # Create new business
    needs_review = geocode_result.get("needs_review", False)
    business = Business(
        name=name or "Unknown",
        city_id=city.id,
        category=geocode_result.get("category"),
        lat=geocode_result.get("lat"),
        lng=geocode_result.get("lng"),
        google_place_id=place_id,
        address=geocode_result.get("address"),
        website=geocode_result.get("website"),
        is_closed=geocode_result.get("is_closed", False),
        review_status=ReviewStatus.pending_review if needs_review else ReviewStatus.approved,
    )
    db.add(business)
    db.flush()  # get ID without full commit
    return business, True


def _create_mention(
    db: Session,
    business: Business,
    video: Video,
    extraction: dict,
    geocode_result: dict,
) -> Mention:
    """Creates a Mention record from LLM extraction + geocode data."""
    sentiment_str = extraction.get("sentiment", "neutral")
    try:
        sentiment = Sentiment(sentiment_str)
    except ValueError:
        sentiment = Sentiment.neutral

    quotes = extraction.get("quotes", [])
    quotes_json = json.dumps(quotes) if quotes else "[]"

    needs_review = extraction.get("needs_review", False) or geocode_result.get("needs_review", False)

    mention = Mention(
        business_id=business.id,
        video_id=video.id,
        timestamp_seconds=extraction.get("timestamp_seconds"),
        raw_business_name=extraction.get("raw_name", ""),
        transcript_excerpt=extraction.get("notes", ""),
        sentiment=sentiment,
        sentiment_score=extraction.get("sentiment_score"),
        quotes_json=quotes_json,
        confidence_score=geocode_result.get("geocode_confidence", extraction.get("confidence")),
        needs_review=needs_review,
    )
    db.add(mention)
    db.flush()
    return mention


def _create_review_item(db: Session, mention: Mention, reason: str) -> None:
    """Adds a review queue item for a flagged mention."""
    review = ReviewQueue(
        mention_id=mention.id,
        reason=reason,
        status=ReviewQueueStatus.pending,
    )
    db.add(review)


# ---------------------------------------------------------------------------
# Single video processor
# ---------------------------------------------------------------------------

def process_video(db: Session, video: Video, city: City) -> bool:
    """
    Processes a single video through the full pipeline.
    Returns True on success, False on failure.
    """
    logger.info(f"Processing video: {video.youtube_video_id} - {video.title}")
    video.processing_status = ProcessingStatus.processing
    db.commit()

    try:
        # Step 1: Get transcript
        transcript = get_cached_transcript(video)
        if transcript is None:
            transcript = fetch_transcript(video, db)

        if transcript is None:
            logger.warning(f"No transcript for {video.youtube_video_id}, skipping")
            video.processing_status = ProcessingStatus.skipped
            video.error_message = "No transcript available"
            db.commit()
            return False

        # Step 2: Find keyword windows
        keywords = city.keyword_list
        windows = find_keyword_windows(transcript, keywords, window_seconds=180)

        if not windows:
            logger.info(f"No keyword matches in {video.youtube_video_id}, skipping")
            video.processing_status = ProcessingStatus.completed
            video.processed_at = datetime.now(timezone.utc)
            db.commit()
            return True

        logger.info(f"Found {len(windows)} keyword window(s) in {video.youtube_video_id}")

        # Step 3: LLM extraction
        published_date = video.published_at.strftime("%Y-%m-%d") if video.published_at else "unknown"
        extractions = extract_businesses_from_video(
            transcript=transcript,
            keyword_windows=windows,
            video_title=video.title,
            published_date=published_date,
            city_name=city.name,
            country=city.country,
        )

        logger.info(f"LLM extracted {len(extractions)} business(es) from {video.youtube_video_id}")

        # Step 4: Geocode and store each extraction
        for extraction in extractions:
            canonical_name = extraction.get("canonical_name", "").strip()
            if not canonical_name:
                continue

            # Geocode
            geocode_result = geocode_business(
                canonical_name=canonical_name,
                city_name=city.name,
                country=city.country,
                llm_confidence=extraction.get("confidence", 0.5),
            )

            # Update is_closed from LLM if geocoder didn't find it
            if extraction.get("is_closed") and not geocode_result.get("is_closed"):
                geocode_result["is_closed"] = True

            # Get or create business
            business, created = _get_or_create_business(db, geocode_result, city)
            if created:
                logger.info(f"Created new business: {business.name}")

            # Update closed status if LLM says so
            if extraction.get("is_closed") and not business.is_closed:
                business.is_closed = True

            # Create mention
            mention = _create_mention(db, business, video, extraction, geocode_result)

            # Create review queue item if needed
            if mention.needs_review:
                reasons = []
                if extraction.get("needs_review"):
                    reasons.append(f"LLM uncertainty: {extraction.get('notes', '')}")
                if geocode_result.get("needs_review"):
                    reasons.append(
                        f"Geocoding uncertain (confidence={geocode_result.get('geocode_confidence', 0):.2f}). "
                        f"Raw name: '{extraction.get('raw_name')}'"
                    )
                _create_review_item(db, mention, " | ".join(reasons) or "Low confidence match")

        # Step 5: Mark video complete
        video.processing_status = ProcessingStatus.completed
        video.processed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Completed processing {video.youtube_video_id}")
        return True

    except Exception as e:
        logger.error(f"Error processing {video.youtube_video_id}: {e}", exc_info=True)
        video.processing_status = ProcessingStatus.failed
        video.error_message = str(e)
        db.commit()
        return False


# ---------------------------------------------------------------------------
# Full pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(
    db: Session,
    only_new: bool = True,
    playlist_id: Optional[int] = None,
    video_id: Optional[int] = None,
) -> dict:
    """
    Runs the full pipeline.

    Args:
        db: Database session
        only_new: If True, only process pending videos. If False, re-process completed ones too.
        playlist_id: If set, only process videos from this playlist.
        video_id: If set, only process this specific video.

    Returns summary dict.
    """
    summary = {"playlists_checked": 0, "new_videos_found": 0, "processed": 0, "failed": 0, "skipped": 0}

    # Step 1: Fetch new videos from playlists
    if video_id is None:
        playlist_query = db.query(Playlist)
        if playlist_id:
            playlist_query = playlist_query.filter(Playlist.id == playlist_id)
        playlists = playlist_query.all()

        for playlist in playlists:
            city = playlist.city
            new_ids = fetch_playlist_videos(db, playlist)
            summary["playlists_checked"] += 1
            summary["new_videos_found"] += len(new_ids)

    # Step 2: Process videos
    if video_id:
        videos_to_process = db.query(Video).filter(Video.id == video_id).all()
    else:
        statuses = [ProcessingStatus.pending]
        if not only_new:
            statuses.extend([ProcessingStatus.failed, ProcessingStatus.completed])

        video_query = db.query(Video).filter(Video.processing_status.in_(statuses))
        if playlist_id:
            video_query = video_query.filter(Video.playlist_id == playlist_id)
        videos_to_process = video_query.all()

    for video in videos_to_process:
        city = video.playlist.city
        success = process_video(db, video, city)
        if success:
            if video.processing_status == ProcessingStatus.skipped:
                summary["skipped"] += 1
            else:
                summary["processed"] += 1
        else:
            summary["failed"] += 1

    logger.info(f"Pipeline complete: {summary}")
    return summary
