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
    website: Optional[str]
    is_closed: bool
    review_status: str
    admin_notes: Optional[str]
    city_name: str
    mention_count: int
    pending_review_count: int

    class Config:
        from_attributes = True


class BusinessUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    website: Optional[str] = None
    is_closed: Optional[bool] = None
    review_status: Optional[str] = None
    admin_notes: Optional[str] = None


class MergeRequest(BaseModel):
    keep_id: int
    merge_id: int  # will be deleted after mentions are migrated


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
    query = db.query(Video).options(joinedload(Video.mentions))

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
        result.append(BusinessAdmin(
            id=b.id,
            name=b.name,
            category=b.category,
            lat=b.lat,
            lng=b.lng,
            address=b.address,
            website=b.website,
            is_closed=b.is_closed,
            review_status=b.review_status.value,
            admin_notes=b.admin_notes,
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
    if request.lat is not None:
        business.lat = request.lat
    if request.lng is not None:
        business.lng = request.lng
    if request.address is not None:
        business.address = request.address
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
    return {"message": "Business updated"}


@router.post("/businesses/merge")
def merge_businesses(
    request: MergeRequest,
    db: Session = Depends(get_db),
    _: AdminSession = Depends(get_admin_session),
):
    """
    Merges two businesses: migrates all mentions from merge_id to keep_id,
    then deletes the merge_id business.
    """
    keep = db.query(Business).filter(Business.id == request.keep_id).first()
    merge = db.query(Business).filter(Business.id == request.merge_id).first()

    if not keep or not merge:
        raise HTTPException(status_code=404, detail="One or both businesses not found")

    # Migrate mentions
    db.query(Mention).filter(Mention.business_id == merge.id).update(
        {"business_id": keep.id}
    )

    db.delete(merge)
    db.commit()

    return {"message": f"Merged business {request.merge_id} into {request.keep_id}"}


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
