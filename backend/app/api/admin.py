"""
Admin API endpoints.
All routes require a valid admin session (Google OAuth).
"""
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.api.auth import get_admin_session
from app.database import get_db
from app.models import (
    AdminSession, Business, City, Mention, Playlist,
    ReviewQueue, ReviewQueueStatus, ReviewStatus, Video, ProcessingStatus,
)
from app.pipeline.processor import run_pipeline

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ReviewQueueItem(BaseModel):
    id: int
    mention_id: int
    reason: str
    status: str
    suggested_correction: Optional[str]
    created_at: datetime
    # Mention info
    raw_business_name: str
    canonical_business_name: str
    transcript_excerpt: Optional[str]
    confidence_score: Optional[float]
    video_title: str
    video_id: str
    timestamp_seconds: Optional[int]
    youtube_url: str

    class Config:
        from_attributes = True


class ReviewResolveRequest(BaseModel):
    action: str  # "approve" | "correct" | "dismiss"
    corrected_name: Optional[str] = None
    notes: Optional[str] = None


class VideoStatus(BaseModel):
    id: int
    youtube_video_id: str
    title: str
    published_at: Optional[datetime]
    processing_status: str
    processed_at: Optional[datetime]
    error_message: Optional[str]
    mention_count: int

    class Config:
        from_attributes = True


class BusinessAdmin(BaseModel):
    id: int
    name: str
    category: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    address: Optional[str]
    extra_addresses: list[str]
    website: Optional[str]
    is_closed: bool
    review_status: str
    admin_notes: Optional[str]
    city_id: int
    city_name: str
    mention_count: int
    pending_review_count: int

    class Config:
        from_attributes = True


class BusinessUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    city_id: Optional[int] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    extra_addresses: Optional[list[str]] = None
    website: Optional[str] = None
    is_closed: Optional[bool] = None
    review_status: Optional[str] = None
    admin_notes: Optional[str] = None


class MentionDetail(BaseModel):
    id: int
    video_id: str
    video_title: str
    timestamp_seconds: Optional[int]
    youtube_url: str
    sentiment: Optional[str]
    sentiment_score: Optional[float]
    quotes: list[str]

    class Config:
        from_attributes = True


class MentionUpdateRequest(BaseModel):
    sentiment: Optional[str] = None
    quotes: Optional[list[str]] = None


class MergeRequest(BaseModel):
    keep_id: int
    merge_ids: list[int]  # all will be deleted after mentions are migrated


class PipelineRunRequest(BaseModel):
    only_new: bool = True
    playlist_id: Optional[int] = None
    video_id: Optional[int] = None


class SeedRequest(BaseModel):
    city_name: str = "Vancouver"
    country: str = "CA"
    search_keywords: str = "Vancouver,BC,van,yvr,yaletown,gastown,kitsilano"
    center_lat: float = 49.2827
    center_lng: float = -123.1207
    default_zoom: int = 12
    playlist_youtube_id: str = "PLvswIqZLpR-VpoMuxzO9oT3F9-FtHScpn"
    playlist_name: str = "Northernlion Vancouver"


# ---------------------------------------------------------------------------
# Setup / Seed
# ---------------------------------------------------------------------------

@router.post("/seed")
def seed_database(
    request: SeedRequest,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """
    Seeds the database with an initial city and playlist.
    Safe to call multiple times — skips rows that already exist.
    """
    # City
    city = db.query(City).filter(City.name == request.city_name).first()
    created_city = False
    if not city:
        city = City(
            name=request.city_name,
            country=request.country,
            search_keywords=request.search_keywords,
            center_lat=request.center_lat,
            center_lng=request.center_lng,
            default_zoom=request.default_zoom,
        )
        db.add(city)
        db.flush()
        created_city = True

    # Playlist
    playlist = db.query(Playlist).filter(
        Playlist.youtube_playlist_id == request.playlist_youtube_id
    ).first()
    created_playlist = False
    if not playlist:
        playlist = Playlist(
            youtube_playlist_id=request.playlist_youtube_id,
            name=request.playlist_name,
            city_id=city.id,
        )
        db.add(playlist)
        created_playlist = True

    db.commit()

    return {
        "city": {"id": city.id, "name": city.name, "created": created_city},
        "playlist": {"id": playlist.id, "name": playlist.name, "created": created_playlist},
    }


@router.post("/cities/virtual")
def create_virtual_city(
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """
    Creates the 'No Fixed Location' virtual city if it doesn't already exist.
    Virtual cities are shown as a list view on the frontend (no map).
    """
    existing = db.query(City).filter(City.is_virtual == True).first()  # noqa: E712
    if existing:
        return {"city": {"id": existing.id, "name": existing.name}, "created": False}

    city = City(
        name="No Fixed Location",
        country="–",
        search_keywords="",
        center_lat=0.0,
        center_lng=0.0,
        default_zoom=2,
        is_virtual=True,
    )
    db.add(city)
    db.commit()

    from app.cache import cache_clear
    cache_clear()

    return {"city": {"id": city.id, "name": city.name}, "created": True}


@router.get("/seed/status")
def seed_status(
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Returns current seed state so the UI can show what's configured."""
    cities = db.query(City).all()
    playlists = db.query(Playlist).all()
    return {
        "cities": [{"id": c.id, "name": c.name, "country": c.country} for c in cities],
        "playlists": [{"id": p.id, "name": p.name, "youtube_playlist_id": p.youtube_playlist_id, "city_id": p.city_id} for p in playlists],
    }


# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

@router.get("/review-queue", response_model=list[ReviewQueueItem])
def get_review_queue(
    status: str = Query("pending"),
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Returns review queue items."""
    try:
        status_enum = ReviewQueueStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    items = (
        db.query(ReviewQueue)
        .filter(ReviewQueue.status == status_enum)
        .options(
            joinedload(ReviewQueue.mention)
            .joinedload(Mention.business),
            joinedload(ReviewQueue.mention)
            .joinedload(Mention.video),
        )
        .order_by(ReviewQueue.created_at.desc())
        .all()
    )

    result = []
    for item in items:
        mention = item.mention
        video = mention.video
        youtube_url = f"https://www.youtube.com/watch?v={video.youtube_video_id}"
        if mention.timestamp_seconds:
            youtube_url += f"&t={mention.timestamp_seconds}s"

        result.append(ReviewQueueItem(
            id=item.id,
            mention_id=mention.id,
            reason=item.reason,
            status=item.status.value,
            suggested_correction=item.suggested_correction,
            created_at=item.created_at,
            raw_business_name=mention.raw_business_name,
            canonical_business_name=mention.business.name,
            transcript_excerpt=mention.transcript_excerpt,
            confidence_score=mention.confidence_score,
            video_title=video.title,
            video_id=video.youtube_video_id,
            timestamp_seconds=mention.timestamp_seconds,
            youtube_url=youtube_url,
        ))

    return result


@router.put("/review-queue/{item_id}")
def resolve_review_item(
    item_id: int,
    request: ReviewResolveRequest,
    db: Session = Depends(get_db),
    admin: AdminSession = Depends(get_admin_session),
):
    """Resolves a review queue item."""
    item = db.query(ReviewQueue).filter(ReviewQueue.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    mention = item.mention
    business = mention.business

    if request.action == "approve":
        # Mark business as approved
        business.review_status = ReviewStatus.approved
        item.status = ReviewQueueStatus.resolved

    elif request.action == "correct":
        if not request.corrected_name:
            raise HTTPException(status_code=400, detail="corrected_name required for 'correct' action")
        # Update business name
        business.name = request.corrected_name
        business.review_status = ReviewStatus.approved
        item.suggested_correction = request.corrected_name
        item.status = ReviewQueueStatus.resolved
        mention.needs_review = False

    elif request.action == "dismiss":
        item.status = ReviewQueueStatus.dismissed
        business.review_status = ReviewStatus.rejected

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

    item.resolved_at = datetime.now(timezone.utc)
    item.resolution_notes = request.notes
    db.commit()

    return {"message": f"Review item {item_id} {request.action}d"}


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

@router.get("/videos", response_model=list[VideoStatus])
def get_videos(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Lists videos with processing status."""
    query = db.query(Video).options(joinedload(Video.mentions)).filter(
        Video.title != "Private video"
    )

    if status:
        try:
            status_enum = ProcessingStatus(status)
            query = query.filter(Video.processing_status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    videos = query.order_by(Video.published_at.desc()).all()

    return [
        VideoStatus(
            id=v.id,
            youtube_video_id=v.youtube_video_id,
            title=v.title,
            published_at=v.published_at,
            processing_status=v.processing_status.value,
            processed_at=v.processed_at,
            error_message=v.error_message,
            mention_count=len(v.mentions),
        )
        for v in videos
    ]


@router.post("/videos/{video_id}/reprocess")
def reprocess_video(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Triggers reprocessing of a specific video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Reset status so pipeline will pick it up
    video.processing_status = ProcessingStatus.pending
    video.error_message = None
    db.commit()

    background_tasks.add_task(_run_pipeline_bg, video_id=video_id)
    return {"message": f"Video {video_id} queued for reprocessing"}


@router.delete("/videos/{video_id}/extractions")
def delete_video_extractions(
    video_id: int,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """
    Deletes all mentions and review queue items extracted from a video,
    then deletes any businesses that have no remaining mentions.
    Resets the video to pending so it can be reprocessed cleanly.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    mentions = db.query(Mention).filter(Mention.video_id == video_id).all()
    business_ids = {m.business_id for m in mentions}

    # Delete review queue items for these mentions
    mention_ids = [m.id for m in mentions]
    if mention_ids:
        db.query(ReviewQueue).filter(ReviewQueue.mention_id.in_(mention_ids)).delete(synchronize_session=False)

    # Delete the mentions themselves
    db.query(Mention).filter(Mention.video_id == video_id).delete(synchronize_session=False)

    # Delete businesses that now have no mentions left
    deleted_businesses = 0
    for biz_id in business_ids:
        remaining = db.query(Mention).filter(Mention.business_id == biz_id).count()
        if remaining == 0:
            db.query(Business).filter(Business.id == biz_id).delete()
            deleted_businesses += 1

    # Reset video to pending for reprocessing
    video.processing_status = ProcessingStatus.pending
    video.error_message = None

    db.commit()

    from app.cache import cache_clear
    cache_clear()

    return {
        "message": f"Cleared extractions for video {video_id}",
        "mentions_deleted": len(mention_ids),
        "businesses_deleted": deleted_businesses,
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@router.post("/pipeline/run")
def run_pipeline_endpoint(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    _: AdminSession = Depends(get_admin_session),
):
    """Triggers the processing pipeline in the background."""
    background_tasks.add_task(
        _run_pipeline_bg,
        only_new=request.only_new,
        playlist_id=request.playlist_id,
        video_id=request.video_id,
    )
    return {"message": "Pipeline started in background"}


@router.post("/pipeline/run-sync")
def run_pipeline_sync(
    request: PipelineRunRequest,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Runs pipeline synchronously and returns summary (for small runs)."""
    summary = run_pipeline(
        db=db,
        only_new=request.only_new,
        playlist_id=request.playlist_id,
        video_id=request.video_id,
    )
    return summary


def _run_pipeline_bg(
    only_new: bool = True,
    playlist_id: Optional[int] = None,
    video_id: Optional[int] = None,
):
    """Background task wrapper for pipeline."""
    import logging
    _logger = logging.getLogger(__name__)
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        run_pipeline(db=db, only_new=only_new, playlist_id=playlist_id, video_id=video_id)
    except Exception:
        _logger.exception("Pipeline background task failed")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Businesses
# ---------------------------------------------------------------------------

@router.get("/businesses", response_model=list[BusinessAdmin])
def get_businesses(
    review_status: Optional[str] = Query(None),
    city_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Lists all businesses including pending/rejected ones."""
    query = (
        db.query(Business)
        .options(joinedload(Business.city), joinedload(Business.mentions))
    )

    if review_status:
        try:
            rs = ReviewStatus(review_status)
            query = query.filter(Business.review_status == rs)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid review_status: {review_status}")

    if city_id:
        query = query.filter(Business.city_id == city_id)

    businesses = query.order_by(Business.created_at.desc()).all()

    result = []
    for b in businesses:
        pending_reviews = sum(
            1 for m in b.mentions
            for r in m.review_items
            if r.status == ReviewQueueStatus.pending
        )
        extra_addresses = []
        if b.extra_addresses_json:
            try:
                for e in json.loads(b.extra_addresses_json):
                    if isinstance(e, dict) and e.get("address"):
                        extra_addresses.append(e["address"])
                    elif isinstance(e, str) and e:
                        extra_addresses.append(e)
            except (ValueError, TypeError):
                pass
        result.append(BusinessAdmin(
            id=b.id,
            name=b.name,
            category=b.category,
            lat=b.lat,
            lng=b.lng,
            address=b.address,
            extra_addresses=extra_addresses,
            website=b.website,
            is_closed=b.is_closed,
            review_status=b.review_status.value,
            admin_notes=b.admin_notes,
            city_id=b.city_id,
            city_name=b.city.name,
            mention_count=len(b.mentions),
            pending_review_count=pending_reviews,
        ))

    return result


@router.put("/businesses/{business_id}")
def update_business(
    business_id: int,
    request: BusinessUpdateRequest,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Updates business fields."""
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    if request.name is not None:
        business.name = request.name
    if request.category is not None:
        business.category = request.category
    if request.city_id is not None:
        city = db.query(City).filter(City.id == request.city_id).first()
        if not city:
            raise HTTPException(status_code=400, detail=f"City {request.city_id} not found")
        business.city_id = request.city_id
    if request.lat is not None:
        business.lat = request.lat
    if request.lng is not None:
        business.lng = request.lng
    if request.address is not None:
        from app.pipeline.geocoder import geocode_address as _geo_addr
        new_addr = (request.address or "").strip()
        current_addr = (business.address or "").strip()
        if not new_addr:
            # Clearing the primary address
            business.address = None
            business.lat = None
            business.lng = None
        elif new_addr != current_addr or not business.lat:
            # Address changed or lat/lng missing — geocode to get coordinates.
            # First check if this address was previously stored as an extra (reuse cached coords).
            cached_extra: dict | None = None
            if business.extra_addresses_json:
                try:
                    for entry in json.loads(business.extra_addresses_json):
                        if isinstance(entry, dict) and entry.get("address", "").strip() == new_addr:
                            cached_extra = entry
                            break
                except (ValueError, TypeError):
                    pass

            if cached_extra:
                business.address = cached_extra["address"]
                business.lat = cached_extra.get("lat")
                business.lng = cached_extra.get("lng")
            else:
                geo = _geo_addr(new_addr)
                business.address = geo["address"] or new_addr
                business.lat = geo["lat"]
                business.lng = geo["lng"]
        else:
            business.address = new_addr

    if request.extra_addresses is not None:
        if not request.extra_addresses:
            business.extra_addresses_json = None
        else:
            from app.pipeline.geocoder import geocode_address
            # Load existing geocoded entries so we don't re-geocode unchanged addresses
            existing: dict[str, dict] = {}
            if business.extra_addresses_json:
                try:
                    for entry in json.loads(business.extra_addresses_json):
                        if isinstance(entry, dict) and entry.get("address"):
                            existing[entry["address"].strip()] = entry
                except (ValueError, TypeError):
                    pass

            geocoded = []
            for addr in request.extra_addresses:
                addr = addr.strip()
                if not addr:
                    continue
                if addr in existing:
                    geocoded.append(existing[addr])
                else:
                    geocoded.append(geocode_address(addr))

            business.extra_addresses_json = json.dumps(geocoded) if geocoded else None
    if request.website is not None:
        business.website = request.website
    if request.is_closed is not None:
        business.is_closed = request.is_closed
    if request.review_status is not None:
        try:
            business.review_status = ReviewStatus(request.review_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid review_status")
    if request.admin_notes is not None:
        business.admin_notes = request.admin_notes

    business.updated_at = datetime.now(timezone.utc)
    db.commit()

    from app.cache import cache_clear
    cache_clear()
    return {"message": "Business updated"}


@router.get("/businesses/{business_id}/mentions", response_model=list[MentionDetail])
def get_business_mentions(
    business_id: int,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Returns all mentions for a business with video info and quotes."""
    mentions = (
        db.query(Mention)
        .filter(Mention.business_id == business_id)
        .options(joinedload(Mention.video))
        .order_by(Mention.id)
        .all()
    )

    result = []
    for m in mentions:
        video = m.video
        youtube_url = f"https://www.youtube.com/watch?v={video.youtube_video_id}"
        if m.timestamp_seconds:
            youtube_url += f"&t={m.timestamp_seconds}s"
        quotes = []
        if m.quotes_json:
            try:
                quotes = json.loads(m.quotes_json)
            except json.JSONDecodeError:
                pass
        result.append(MentionDetail(
            id=m.id,
            video_id=video.youtube_video_id,
            video_title=video.title,
            timestamp_seconds=m.timestamp_seconds,
            youtube_url=youtube_url,
            sentiment=m.sentiment.value if m.sentiment else None,
            sentiment_score=m.sentiment_score,
            quotes=quotes,
        ))

    return result


@router.delete("/mentions/{mention_id}")
def delete_mention(
    mention_id: int,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """
    Deletes a single mention and its review queue items.
    If the parent business has no remaining mentions after deletion, it is also deleted.
    """
    from app.cache import cache_clear

    mention = db.query(Mention).filter(Mention.id == mention_id).first()
    if not mention:
        raise HTTPException(status_code=404, detail="Mention not found")

    business_id = mention.business_id

    # Delete associated review queue items first
    db.query(ReviewQueue).filter(ReviewQueue.mention_id == mention_id).delete(synchronize_session=False)

    db.delete(mention)
    db.flush()

    # Delete the business if it now has no mentions
    remaining = db.query(Mention).filter(Mention.business_id == business_id).count()
    business_deleted = False
    if remaining == 0:
        db.query(Business).filter(Business.id == business_id).delete()
        business_deleted = True

    db.commit()
    cache_clear()

    return {"message": "Mention deleted", "business_deleted": business_deleted}


@router.put("/mentions/{mention_id}")
def update_mention(
    mention_id: int,
    request: MentionUpdateRequest,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Updates sentiment and/or quotes on a mention."""
    from app.models import Sentiment as SentimentEnum
    from app.cache import cache_clear

    mention = db.query(Mention).filter(Mention.id == mention_id).first()
    if not mention:
        raise HTTPException(status_code=404, detail="Mention not found")

    if request.sentiment is not None:
        try:
            mention.sentiment = SentimentEnum(request.sentiment)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid sentiment: {request.sentiment}")
        mention.sentiment_score = {"positive": 0.8, "negative": -0.8, "neutral": 0.0, "mixed": 0.1}.get(request.sentiment, 0.0)

    if request.quotes is not None:
        mention.quotes_json = json.dumps(request.quotes)

    db.commit()
    cache_clear()
    return {"message": "Mention updated"}


@router.post("/businesses/merge")
def merge_businesses(
    request: MergeRequest,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """
    Merges one or more businesses into a single target (keep_id).
    - All mentions are reassigned to keep_id.
    - All unique addresses are combined (deduplicated case-insensitively).
    - keep_id's primary address/lat/lng is preferred; falls back to merge sources
      if keep has no coordinates.
    - Merged businesses are then deleted.
    """
    keep = db.query(Business).filter(Business.id == request.keep_id).first()
    if not keep:
        raise HTTPException(status_code=404, detail=f"Business {request.keep_id} not found")

    merges = db.query(Business).filter(Business.id.in_(request.merge_ids)).all()
    if len(merges) != len(request.merge_ids):
        raise HTTPException(status_code=404, detail="One or more merge businesses not found")

    # ── Build a combined, deduplicated address list ──────────────────────────
    # Each entry is {address: str, lat: float|None, lng: float|None}.
    # We start with keep's addresses (primary + extras), then append merge sources.
    def _collect_addresses(biz: Business) -> list[dict]:
        entries = []
        if biz.address:
            entries.append({"address": biz.address, "lat": biz.lat, "lng": biz.lng})
        if biz.extra_addresses_json:
            try:
                for e in json.loads(biz.extra_addresses_json):
                    if isinstance(e, dict) and e.get("address"):
                        entries.append({
                            "address": e["address"],
                            "lat": e.get("lat"),
                            "lng": e.get("lng"),
                        })
                    elif isinstance(e, str) and e:
                        entries.append({"address": e, "lat": None, "lng": None})
            except (ValueError, TypeError):
                pass
        return entries

    combined: list[dict] = []
    seen: set[str] = set()
    for entry in _collect_addresses(keep) + [a for biz in merges for a in _collect_addresses(biz)]:
        key = entry["address"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            combined.append(entry)

    # Apply combined addresses back to keep
    if combined:
        first = combined[0]
        keep.address = first["address"]
        # Prefer keep's existing coords; fall back to whichever source has them
        if not keep.lat:
            keep.lat = first.get("lat")
            keep.lng = first.get("lng")
        extras = combined[1:]
        keep.extra_addresses_json = json.dumps(extras) if extras else None
    else:
        # No addresses anywhere — try to inherit coords from a merge source
        if not keep.lat:
            for biz in merges:
                if biz.lat:
                    keep.lat = biz.lat
                    keep.lng = biz.lng
                    break

    # ── Migrate mentions ─────────────────────────────────────────────────────
    for biz in merges:
        db.query(Mention).filter(Mention.business_id == biz.id).update(
            {"business_id": keep.id}, synchronize_session=False
        )

    # ── Delete merged businesses ─────────────────────────────────────────────
    for biz in merges:
        db.delete(biz)

    db.commit()

    from app.cache import cache_clear
    cache_clear()

    return {
        "message": f"Merged {len(merges)} business(es) into {keep.name} (id={keep.id})",
        "keep_id": keep.id,
        "merged_ids": request.merge_ids,
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """Returns dashboard stats."""
    return {
        "total_videos": db.query(Video).count(),
        "pending_videos": db.query(Video).filter(Video.processing_status == ProcessingStatus.pending).count(),
        "completed_videos": db.query(Video).filter(Video.processing_status == ProcessingStatus.completed).count(),
        "failed_videos": db.query(Video).filter(Video.processing_status == ProcessingStatus.failed).count(),
        "total_businesses": db.query(Business).count(),
        "approved_businesses": db.query(Business).filter(Business.review_status == ReviewStatus.approved).count(),
        "pending_review_businesses": db.query(Business).filter(Business.review_status == ReviewStatus.pending_review).count(),
        "total_mentions": db.query(Mention).count(),
        "pending_review_queue": db.query(ReviewQueue).filter(ReviewQueue.status == ReviewQueueStatus.pending).count(),
    }
