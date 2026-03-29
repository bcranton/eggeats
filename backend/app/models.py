from datetime import datetime
from typing import Optional
import enum

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer,
    String, Text, func, ARRAY
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProcessingStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    ignored = "ignored"


class ReviewStatus(str, enum.Enum):
    approved = "approved"
    pending_review = "pending_review"
    rejected = "rejected"


class Sentiment(str, enum.Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"
    mixed = "mixed"


class ReviewQueueStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"
    dismissed = "dismissed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(10), nullable=False)
    # comma-separated keywords to search in transcripts, e.g. "Vancouver,Van,YVR"
    search_keywords: Mapped[str] = mapped_column(Text, nullable=False)
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    center_lng: Mapped[float] = mapped_column(Float, nullable=False)
    default_zoom: Mapped[int] = mapped_column(Integer, default=12)
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False)

    playlists: Mapped[list["Playlist"]] = relationship(back_populates="city")
    businesses: Mapped[list["Business"]] = relationship(back_populates="city")

    @property
    def keyword_list(self) -> list[str]:
        return [k.strip() for k in self.search_keywords.split(",") if k.strip()]


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_playlist_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    city: Mapped["City"] = relationship(back_populates="playlists")
    videos: Mapped[list["Video"]] = relationship(back_populates="playlist")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    playlist_id: Mapped[int] = mapped_column(Integer, ForeignKey("playlists.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Raw transcript stored as JSON string
    transcript_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus), default=ProcessingStatus.pending
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    playlist: Mapped["Playlist"] = relationship(back_populates="videos")
    mentions: Mapped[list["Mention"]] = relationship(back_populates="video")


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    google_place_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Admin-added extra addresses (JSON array of strings)
    extra_addresses_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending_review
    )
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    city: Mapped["City"] = relationship(back_populates="businesses")
    mentions: Mapped[list["Mention"]] = relationship(back_populates="business")


class Mention(Base):
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    timestamp_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_business_name: Mapped[str] = mapped_column(Text, nullable=False)
    transcript_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentiment: Mapped[Optional[Sentiment]] = mapped_column(Enum(Sentiment), nullable=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # JSON array stored as text: ["quote 1", "quote 2"]
    quotes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    business: Mapped["Business"] = relationship(back_populates="mentions")
    video: Mapped["Video"] = relationship(back_populates="mentions")
    review_items: Mapped[list["ReviewQueue"]] = relationship(back_populates="mention")


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mention_id: Mapped[int] = mapped_column(Integer, ForeignKey("mentions.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReviewQueueStatus] = mapped_column(
        Enum(ReviewQueueStatus), default=ReviewQueueStatus.pending
    )
    suggested_correction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    mention: Mapped["Mention"] = relationship(back_populates="review_items")


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
