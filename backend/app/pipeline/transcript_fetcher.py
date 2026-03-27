"""
Fetches YouTube video transcripts.

Primary:  Supadata SDK (https://supadata.ai) — avoids IP blocking on Railway
          and other datacenter hosts. Set SUPADATA_API_KEY in env to use.
          Uses mode="native" so only actual captions are returned (no AI generation).
Fallback: youtube-transcript-api — works on local/residential IPs.
"""
import json
import logging
import re
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Video

logger = logging.getLogger(__name__)

# Delay between successful fetches to be polite
REQUEST_DELAY_SECONDS = 1.0


# ---------------------------------------------------------------------------
# Supadata fetcher
# ---------------------------------------------------------------------------

def _fetch_via_supadata(video_id: str, api_key: str) -> list[dict] | None:
    """
    Fetch transcript via Supadata SDK using native mode (captions only, no AI).
    Returns list of {text, start, duration} dicts (start/duration in seconds),
    or None if no transcript is available.
    """
    from supadata import Supadata, SupadataError

    client = Supadata(api_key=api_key)
    try:
        result = client.youtube.transcript(video_id=video_id, lang="en")
    except SupadataError as e:
        logger.warning(f"Supadata: no transcript for {video_id}: {e}")
        return None

    content = getattr(result, "content", None) or []
    if not content:
        logger.warning(f"Supadata returned empty content for {video_id}")
        return None

    # Supadata returns offset/duration in milliseconds — convert to seconds
    return [
        {
            "text": seg.text,
            "start": seg.offset / 1000.0,
            "duration": seg.duration / 1000.0,
        }
        for seg in content
        if getattr(seg, "text", "").strip()
    ]


# ---------------------------------------------------------------------------
# youtube-transcript-api fallback (local / residential IPs only)
# ---------------------------------------------------------------------------

def _fetch_via_yta(video_id: str) -> list[dict] | None:
    """
    Fetch transcript using youtube-transcript-api.
    Works on residential IPs; frequently blocked on datacenter IPs.
    """
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        IpBlocked,
        NoTranscriptFound,
        TranscriptsDisabled,
    )

    api = YouTubeTranscriptApi()

    try:
        transcript_list = api.list(video_id)
    except (NoTranscriptFound, TranscriptsDisabled):
        logger.warning(f"youtube-transcript-api: no transcript for {video_id}")
        return None
    except IpBlocked:
        logger.warning(
            f"youtube-transcript-api: IP blocked for {video_id}. "
            "Set SUPADATA_API_KEY to avoid this on Railway."
        )
        return None

    # Prefer manual EN → auto EN → any
    best = None
    generated_en = None
    fallback = None
    for t in transcript_list:
        lang = t.language_code.lower()
        if not t.is_generated and lang.startswith("en"):
            best = t
            break
        if t.is_generated and lang.startswith("en") and generated_en is None:
            generated_en = t
        if fallback is None:
            fallback = t

    transcript = best or generated_en or fallback
    if transcript is None:
        return None

    data = transcript.fetch()
    return [
        {"text": s.text, "start": s.start, "duration": s.duration}
        for s in data
    ]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_transcript(video: Video, db: Session) -> list[dict] | None:
    """
    Fetches transcript for a single video and caches it in the DB.
    Uses Supadata if SUPADATA_API_KEY is set, otherwise falls back to
    youtube-transcript-api (suitable for local/residential IPs).
    Returns parsed transcript (list of {text, start, duration}) or None.
    """
    from app.config import get_settings
    settings = get_settings()

    video_id = video.youtube_video_id
    parsed = None

    try:
        if settings.supadata_api_key:
            logger.info(f"Fetching transcript via Supadata for {video_id}")
            parsed = _fetch_via_supadata(video_id, settings.supadata_api_key)
        else:
            logger.info(f"Fetching transcript via youtube-transcript-api for {video_id} (no SUPADATA_API_KEY set)")
            parsed = _fetch_via_yta(video_id)

    except Exception as e:
        logger.error(f"Error fetching transcript for {video_id}: {e}")
        return None

    if parsed is None:
        logger.warning(f"No transcript available for {video_id}")
        return None

    video.transcript_raw = json.dumps(parsed)
    video.transcript_fetched_at = datetime.now(timezone.utc)
    db.commit()

    time.sleep(REQUEST_DELAY_SECONDS)
    return parsed


def get_cached_transcript(video: Video) -> list[dict] | None:
    """Returns parsed transcript from DB cache, or None if not cached."""
    if video.transcript_raw:
        try:
            return json.loads(video.transcript_raw)
        except json.JSONDecodeError:
            return None
    return None


def transcript_to_text_with_timestamps(transcript: list[dict]) -> str:
    """
    Converts transcript list to a string with timestamps embedded.
    Format: [12s] Some text here
    """
    lines = []
    for item in transcript:
        start = item.get("start", 0)
        text = item.get("text", "").replace("\n", " ").strip()
        if text:
            lines.append(f"[{start:.0f}s] {text}")
    return "\n".join(lines)


def find_keyword_windows(
    transcript: list[dict],
    keywords: list[str],
    window_seconds: int = 180,
) -> list[dict]:
    """
    Finds windows of transcript text around keyword mentions.
    Returns deduplicated/merged windows as list of {start_time, end_time, text}.
    """
    # Word-boundary patterns prevent substring false matches
    # e.g. "van" won't match inside "advantage", "la" won't match "place"
    keyword_patterns = [
        re.compile(r'\b' + re.escape(k.lower()) + r'\b')
        for k in keywords
    ]

    hit_times = []
    for item in transcript:
        text_lower = item.get("text", "").lower()
        if any(pat.search(text_lower) for pat in keyword_patterns):
            hit_times.append(item["start"])

    if not hit_times:
        return []

    # Build windows around each hit, then merge overlapping ones
    windows = [(max(0, t - window_seconds / 2), t + window_seconds / 2) for t in hit_times]
    windows.sort()
    merged = [windows[0]]
    for start, end in windows[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    result = []
    for window_start, window_end in merged:
        window_items = [
            item for item in transcript
            if window_start <= item["start"] <= window_end
        ]
        if window_items:
            result.append({
                "start_time": window_start,
                "end_time": window_end,
                "text": transcript_to_text_with_timestamps(window_items),
            })

    return result
