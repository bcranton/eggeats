"""
Public map/business API endpoints.
No authentication required.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel

from app.database import get_db
from app.models import Business, City, Mention, ReviewStatus, Video

router = APIRouter(prefix="/api", tags=["map"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CitySchema(BaseModel):
    id: int
    name: str
    country: str
    center_lat: float
    center_lng: float
    default_zoom: int

    class Config:
        from_attributes = True


class MentionSummary(BaseModel):
    id: int
    video_id: str
    video_title: str
    timestamp_seconds: Optional[int]
    sentiment: Optional[str]
    sentiment_score: Optional[float]
    quotes: list[str]
    youtube_url: str

    class Config:
        from_attributes = True


class BusinessMapPin(BaseModel):
    """Lightweight payload for map markers."""
    id: int
    name: str
    category: Optional[str]
    lat: float
    lng: float
    is_closed: bool
    sentiment_summary: Optional[str]
    mention_count: int
    city_id: int

    class Config:
        from_attributes = True


class BusinessDetail(BaseModel):
    id: int
    name: str
    category: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    address: Optional[str]
    website: Optional[str]
    is_closed: bool
    city: CitySchema
    mentions: list[MentionSummary]

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dominant_sentiment(mentions: list[Mention]) -> Optional[str]:
    """Returns the most common non-neutral sentiment across mentions."""
    if not mentions:
        return None
    counts: dict[str, int] = {}
    for m in mentions:
        if m.sentiment:
            counts[m.sentiment.value] = counts.get(m.sentiment.value, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def _mention_to_summary(mention: Mention) -> MentionSummary:
    quotes = []
    if mention.quotes_json:
        try:
            quotes = json.loads(mention.quotes_json)
        except json.JSONDecodeError:
            pass

    video: Video = mention.video
    youtube_url = f"https://www.youtube.com/watch?v={video.youtube_video_id}"
    if mention.timestamp_seconds:
        youtube_url += f"&t={mention.timestamp_seconds}s"

    return MentionSummary(
        id=mention.id,
        video_id=video.youtube_video_id,
        video_title=video.title,
        timestamp_seconds=mention.timestamp_seconds,
        sentiment=mention.sentiment.value if mention.sentiment else None,
        sentiment_score=mention.sentiment_score,
        quotes=quotes,
        youtube_url=youtube_url,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/cities", response_model=list[CitySchema])
def get_cities(db: Session = Depends(get_db)):
    """List all cities."""
    return db.query(City).all()


@router.get("/map-data", response_model=list[BusinessMapPin])
def get_map_data(
    city_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns all approved businesses with coordinates for map rendering.
    Filtered by city, category, and/or sentiment.
    Only includes businesses that have coordinates.
    """
    query = (
        db.query(Business)
        .filter(
            Business.review_status == ReviewStatus.approved,
            Business.lat.isnot(None),
            Business.lng.isnot(None),
        )
        .options(joinedload(Business.mentions))
    )

    if city_id:
        query = query.filter(Business.city_id == city_id)
    if category:
        query = query.filter(Business.category == category)

    businesses = query.all()

    # Filter by sentiment if needed (requires checking mentions)
    if sentiment:
        businesses = [
            b for b in businesses
            if _dominant_sentiment(b.mentions) == sentiment
        ]

    pins = []
    for b in businesses:
        pins.append(BusinessMapPin(
            id=b.id,
            name=b.name,
            category=b.category,
            lat=b.lat,
            lng=b.lng,
            is_closed=b.is_closed,
            sentiment_summary=_dominant_sentiment(b.mentions),
            mention_count=len(b.mentions),
            city_id=b.city_id,
        ))

    return pins


@router.get("/businesses/{business_id}", response_model=BusinessDetail)
def get_business(business_id: int, db: Session = Depends(get_db)):
    """Full business detail including all mentions and quotes."""
    business = (
        db.query(Business)
        .filter(
            Business.id == business_id,
            Business.review_status == ReviewStatus.approved,
        )
        .options(
            joinedload(Business.city),
            joinedload(Business.mentions).joinedload(Mention.video),
        )
        .first()
    )

    if not business:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Business not found")

    return BusinessDetail(
        id=business.id,
        name=business.name,
        category=business.category,
        lat=business.lat,
        lng=business.lng,
        address=business.address,
        website=business.website,
        is_closed=business.is_closed,
        city=CitySchema.model_validate(business.city),
        mentions=[_mention_to_summary(m) for m in business.mentions],
    )


@router.get("/config")
def get_frontend_config():
    """Returns public config values needed by frontend (Maps API key)."""
    from app.config import get_settings
    settings = get_settings()
    return {"google_maps_api_key": settings.google_maps_api_key}
