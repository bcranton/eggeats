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

def _process_video_for_city(
    db: Session,
    video: Video,
    city: City,
    transcript: list[dict],
) -> int:
    """
    Runs LLM extraction + geocoding for one city against an already-fetched transcript.
    Returns the number of businesses extracted (0 if no keyword matches).
    """
    keywords = city.keyword_list
    windows = find_keyword_windows(transcript, keywords, window_seconds=180)
    if not windows:
        return 0

    logger.info(f"  [{city.name}] {len(windows)} keyword window(s) in {video.youtube_video_id}")

    published_date = video.published_at.strftime("%Y-%m-%d") if video.published_at else "unknown"
    extractions = extract_businesses_from_video(
        transcript=transcript,
        keyword_windows=windows,
        video_title=video.title,
        published_date=published_date,
        city_name=city.name,
        country=city.country,
    )
    logger.info(f"  [{city.name}] LLM extracted {len(extractions)} business(es)")

    for extraction in extractions:
        canonical_name = extraction.get("canonical_name", "").strip()
        if not canonical_name:
            continue

        is_chain = extraction.get("is_chain", False)

        if is_chain:
            # Generic chain opinion — skip geocoding, store with no coordinates.
            # These represent NL's general views on a chain, not a specific location.
            geocode_result = {
                "name": canonical_name,
                "lat": None,
                "lng": None,
                "google_place_id": None,
                "address": None,
                "website": None,
                "category": extraction.get("category"),
                "is_closed": False,
                "needs_review": False,
                "geocode_confidence": 1.0,
            }
            logger.info(f"  [{city.name}] Chain mention (no geocode): {canonical_name}")
        else:
            geocode_result = geocode_business(
                canonical_name=canonical_name,
                city_name=city.name,
                country=city.country,
                llm_confidence=extraction.get("confidence", 0.5),
            )

        if extraction.get("is_closed") and not geocode_result.get("is_closed"):
            geocode_result["is_closed"] = True

        business, created = _get_or_create_business(db, geocode_result, city)
        if created:
            logger.info(f"  [{city.name}] Created new business: {business.name}")

        if extraction.get("is_closed") and not business.is_closed:
            business.is_closed = True

        mention = _create_mention(db, business, video, extraction, geocode_result)

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

    return len(extractions)


def process_video(db: Session, video: Video, cities: list[City]) -> bool:
    """
    Processes a single video against all cities.
    Fetches the transcript once, then checks keyword windows for each city.
    Returns True on success, False on failure.
    """
    logger.info(f"Processing video: {video.youtube_video_id} - {video.title}")
    video.processing_status = ProcessingStatus.processing
    db.commit()

    try:
        # Step 1: Get transcript (cached or fetch)
        transcript = get_cached_transcript(video)
        if transcript is None:
            transcript = fetch_transcript(video, db)

        if transcript is None:
            logger.warning(f"No transcript for {video.youtube_video_id}, skipping")
            video.processing_status = ProcessingStatus.skipped
            video.error_message = "No transcript available"
            db.commit()
            return False

        # Step 2–4: For each city, find keyword windows and extract businesses
        total_extractions = 0
        for city in cities:
            total_extractions += _process_video_for_city(db, video, city, transcript)

        if total_extractions == 0:
            logger.info(f"No keyword matches in any city for {video.youtube_video_id}")

        # Step 5: Mark video complete, clear any previous error
        video.processing_status = ProcessingStatus.completed
        video.processed_at = datetime.now(timezone.utc)
        video.error_message = None
        db.commit()
        logger.info(f"Completed {video.youtube_video_id} ({total_extractions} extraction(s) across all cities)")
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

    # Reset any videos stuck in "processing" state from a previously interrupted run
    stuck = db.query(Video).filter(Video.processing_status == ProcessingStatus.processing).all()
    for v in stuck:
        v.processing_status = ProcessingStatus.pending
        v.error_message = "Reset: previous run was interrupted"
    if stuck:
        db.commit()
        logger.info(f"Reset {len(stuck)} stuck video(s) from 'processing' to 'pending'")

    # Load all real (non-virtual) cities — virtual cities are for manual assignment only
    all_cities = db.query(City).filter(City.is_virtual == False).all()  # noqa: E712
    if not all_cities:
        logger.warning("No cities configured — pipeline has nothing to process against")

    # Step 1: Fetch new videos from playlists
    if video_id is None:
        playlist_query = db.query(Playlist)
        if playlist_id:
            playlist_query = playlist_query.filter(Playlist.id == playlist_id)
        playlists = playlist_query.all()

        for playlist in playlists:
            new_ids = fetch_playlist_videos(db, playlist)
            summary["playlists_checked"] += 1
            summary["new_videos_found"] += len(new_ids)

    # Step 2: Process videos
    if video_id:
        videos_to_process = db.query(Video).filter(Video.id == video_id).all()
    else:
        # Always retry failed videos — they may have failed due to transient errors
        # (e.g. exhausted API credits). only_new=False additionally re-runs completed videos.
        statuses = [ProcessingStatus.pending, ProcessingStatus.failed]
        if not only_new:
            statuses.append(ProcessingStatus.completed)

        video_query = db.query(Video).filter(Video.processing_status.in_(statuses))
        if playlist_id:
            video_query = video_query.filter(Video.playlist_id == playlist_id)
        videos_to_process = video_query.all()

    for video in videos_to_process:
        success = process_video(db, video, all_cities)
        if success:
            if video.processing_status == ProcessingStatus.skipped:
                summary["skipped"] += 1
            else:
                summary["processed"] += 1
        else:
            summary["failed"] += 1

    # Invalidate server-side cache so the map reflects new data immediately
    if summary["processed"] > 0:
        from app.cache import cache_clear
        cache_clear()
        logger.info("Server cache cleared after pipeline run")

    logger.info(f"Pipeline complete: {summary}")
    return summary
