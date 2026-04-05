"""
Public map/business API endpoints.
No authentication required.
"""
import json
from typing import Optional
from datetime import datetime

import json as _json
from fastapi import APIRouter, Depends, Query, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import exists, and_, select
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel

limiter = Limiter(key_func=get_remote_address)

# Browser cache header: 5-minute TTL, matches server-side cache below.
MAP_DATA_CACHE = "public, max-age=7200"

from sqlalchemy import func as sa_func

from app.database import get_db
from app.models import Business, City, Mention, ReviewStatus, Video
from app.cache import cache_get, cache_set

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
    is_virtual: bool = False
    business_count: int = 0

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


class AddressLocation(BaseModel):
    address: str
    lat: Optional[float]
    lng: Optional[float]


class BusinessDetail(BaseModel):
    id: int
    name: str
    category: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    addresses: list[str]  # kept for backwards compat
    locations: list[AddressLocation]  # address + coords for each location
    website: Optional[str]
    is_closed: bool
    city: CitySchema
    mentions: list[MentionSummary]

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _effective_sentiment(business) -> Optional[str]:
    """Returns the admin override if set, otherwise the computed dominant sentiment."""
    if business.sentiment_override:
        return business.sentiment_override
    return _dominant_sentiment(business.mentions)


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
@limiter.limit("60/minute")
def get_cities(request: Request, response: Response, db: Session = Depends(get_db)):
    """List all cities ordered by number of approved businesses."""
    response.headers["Cache-Control"] = MAP_DATA_CACHE
    cached = cache_get("cities")
    if cached is not None:
        return cached

    # Count approved businesses per city
    counts = dict(
        db.query(Business.city_id, sa_func.count(Business.id))
        .filter(Business.review_status == ReviewStatus.approved)
        .group_by(Business.city_id)
        .all()
    )

    cities = db.query(City).all()
    result = []
    for city in cities:
        schema = CitySchema.model_validate(city)
        schema.business_count = counts.get(city.id, 0)
        result.append(schema)

    # Real cities ordered by business count; virtual cities always at the end
    result.sort(key=lambda c: (c.is_virtual, -c.business_count))

    cache_set("cities", result)
    return result


def _parse_date(value: str, param_name: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid {param_name}: expected YYYY-MM-DD")


def _apply_date_filter(query, date_from: Optional[str], date_to: Optional[str]):
    """Filter businesses to those with at least one mention in the date range."""
    video_conditions = []
    if date_from:
        video_conditions.append(Video.published_at >= _parse_date(date_from, "date_from"))
    if date_to:
        dt_to = _parse_date(date_to, "date_to").replace(hour=23, minute=59, second=59)
        video_conditions.append(Video.published_at <= dt_to)
    if not video_conditions:
        return query
    video_ids = select(Video.id).where(and_(*video_conditions)).scalar_subquery()
    has_mention = exists(
        select(Mention.id).where(
            Mention.business_id == Business.id,
            Mention.video_id.in_(video_ids),
        )
    )
    return query.filter(has_mention)


@router.get("/map-data", response_model=list[BusinessMapPin])
@limiter.limit("30/minute")
def get_map_data(
    request: Request,
    response: Response,
    city_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns all approved businesses with coordinates for map rendering.
    Filtered by city, category, sentiment, and/or date range.
    Only includes businesses that have coordinates.
    """
    response.headers["Cache-Control"] = MAP_DATA_CACHE

    cache_key = f"map-data:{city_id}:{category}:{sentiment}:{date_from}:{date_to}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

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
    if date_from or date_to:
        query = _apply_date_filter(query, date_from, date_to)

    businesses = query.all()

    if sentiment:
        businesses = [
            b for b in businesses
            if _effective_sentiment(b) == sentiment
        ]

    pins = []
    for b in businesses:
        sentiment = _effective_sentiment(b)
        mention_count = len(b.mentions)
        base = dict(
            id=b.id,
            name=b.name,
            category=b.category,
            is_closed=b.is_closed,
            sentiment_summary=sentiment,
            mention_count=mention_count,
            city_id=b.city_id,
        )
        # Primary pin
        pins.append(BusinessMapPin(lat=b.lat, lng=b.lng, **base))
        # Extra location pins (entries may be {address,lat,lng} dicts or legacy plain strings)
        if b.extra_addresses_json:
            try:
                for loc in _json.loads(b.extra_addresses_json):
                    if isinstance(loc, dict) and loc.get("lat") and loc.get("lng"):
                        pins.append(BusinessMapPin(lat=loc["lat"], lng=loc["lng"], **base))
            except (ValueError, TypeError):
                pass

    cache_set(cache_key, pins)
    return pins


@router.get("/businesses/{business_id}", response_model=BusinessDetail)
@limiter.limit("60/minute")
def get_business(request: Request, business_id: int, response: Response, db: Session = Depends(get_db)):
    """Full business detail including all mentions and quotes."""
    response.headers["Cache-Control"] = MAP_DATA_CACHE

    cache_key = f"business:{business_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

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

    locations = []
    if business.address:
        locations.append(AddressLocation(address=business.address, lat=business.lat, lng=business.lng))
    if business.extra_addresses_json:
        try:
            for loc in _json.loads(business.extra_addresses_json):
                if isinstance(loc, dict) and loc.get("address"):
                    locations.append(AddressLocation(
                        address=loc["address"],
                        lat=loc.get("lat"),
                        lng=loc.get("lng"),
                    ))
        except (ValueError, TypeError):
            pass

    result = BusinessDetail(
        id=business.id,
        name=business.name,
        category=business.category,
        lat=business.lat,
        lng=business.lng,
        addresses=[l.address for l in locations],
        locations=locations,
        website=business.website,
        is_closed=business.is_closed,
        city=CitySchema.model_validate(business.city),
        mentions=[_mention_to_summary(m) for m in business.mentions],
    )
    cache_set(cache_key, result)
    return result


class NoLocationBusiness(BaseModel):
    """Business with no coordinates — chains or unlocated mentions."""
    id: int
    name: str
    category: Optional[str]
    is_closed: bool
    sentiment_summary: Optional[str]
    city_name: str
    mentions: list[MentionSummary]

    class Config:
        from_attributes = True


@router.get("/no-location", response_model=list[NoLocationBusiness])
@limiter.limit("30/minute")
def get_no_location_businesses(
    request: Request,
    response: Response,
    city_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns approved businesses that have no coordinates (chains, unlocated places).
    These are surfaced in a separate list view since they cannot be pinned on the map.
    """
    response.headers["Cache-Control"] = MAP_DATA_CACHE

    cache_key = f"no-location:{city_id}:{date_from}:{date_to}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = (
        db.query(Business)
        .filter(
            Business.review_status == ReviewStatus.approved,
            Business.lat.is_(None),
        )
        .options(
            joinedload(Business.city),
            joinedload(Business.mentions).joinedload(Mention.video),
        )
    )

    if city_id:
        query = query.filter(Business.city_id == city_id)
    if date_from or date_to:
        query = _apply_date_filter(query, date_from, date_to)

    businesses = query.all()

    result = [
        NoLocationBusiness(
            id=b.id,
            name=b.name,
            category=b.category,
            is_closed=b.is_closed,
            sentiment_summary=_effective_sentiment(b),
            city_name=b.city.name,
            mentions=[_mention_to_summary(m) for m in b.mentions],
        )
        for b in businesses
    ]

    cache_set(cache_key, result)
    return result


class ListBusiness(BaseModel):
    """Full business payload for list view."""
    id: int
    name: str
    category: Optional[str]
    is_closed: bool
    sentiment_summary: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    address: Optional[str]
    website: Optional[str]
    mentions: list[MentionSummary]

    class Config:
        from_attributes = True


@router.get("/list-data", response_model=list[ListBusiness])
@limiter.limit("30/minute")
def get_list_data(
    request: Request,
    response: Response,
    city_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Full business data (with mentions) for the list view toggle."""
    response.headers["Cache-Control"] = MAP_DATA_CACHE

    cache_key = f"list-data:{city_id}:{date_from}:{date_to}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = (
        db.query(Business)
        .filter(Business.review_status == ReviewStatus.approved)
        .options(
            joinedload(Business.mentions).joinedload(Mention.video),
        )
    )

    if city_id:
        query = query.filter(Business.city_id == city_id)
    if date_from or date_to:
        query = _apply_date_filter(query, date_from, date_to)

    businesses = query.all()

    result = [
        ListBusiness(
            id=b.id,
            name=b.name,
            category=b.category,
            is_closed=b.is_closed,
            sentiment_summary=_effective_sentiment(b),
            lat=b.lat,
            lng=b.lng,
            address=b.address,
            website=b.website,
            mentions=[_mention_to_summary(m) for m in b.mentions],
        )
        for b in businesses
    ]

    cache_set(cache_key, result)
    return result


@router.get("/sitemap-data", response_model=list[dict])
@limiter.limit("10/minute")
def get_sitemap_data(request: Request, response: Response, db: Session = Depends(get_db)):
    """Returns business IDs and names for sitemap generation."""
    response.headers["Cache-Control"] = MAP_DATA_CACHE
    cached = cache_get("sitemap-data")
    if cached is not None:
        return cached

    businesses = (
        db.query(Business.id, Business.name, Business.updated_at)
        .filter(Business.review_status == ReviewStatus.approved)
        .all()
    )

    result = [
        {"id": b.id, "name": b.name, "updated_at": b.updated_at.isoformat() if b.updated_at else None}
        for b in businesses
    ]
    cache_set("sitemap-data", result)
    return result


