"""
Fetches YouTube video transcripts via youtubetranscripts.org API.
Returns real timestamped segments — no estimation needed.
Docs: https://youtubetranscripts.org/api#endpoints
"""
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Video, ProcessingStatus

logger = logging.getLogger(__name__)

TRANSCRIPT_API_URL = "https://youtubetranscripts.org/api/transcript"

# Conservative delay between requests (free tier is rate-limited)
REQUEST_DELAY_SECONDS = 2.0

# Retry settings for 429 / transient errors
MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 30  # 30s, 60s, 120s, 240s


def _fetch_transcript_with_retry(video_id: str) -> list[dict] | None:
    """
    Fetches transcript with exponential backoff on 429 / transient errors.
    Returns a list of {text, start, duration} dicts, or None if unavailable.
    """
    from app.config import get_settings
    api_key = get_settings().youtubetranscripts_api_key
    if not api_key:
        raise RuntimeError("YOUTUBETRANSCRIPTS_API_KEY is not configured")

    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = httpx.get(
                TRANSCRIPT_API_URL,
                params={"video_url": video_id, "include_timestamp": "true"},
                headers={"X-API-Key": api_key},
                timeout=30,
            )

            if response.status_code == 404:
                logger.warning(f"No transcript available for {video_id} (404)")
                return None

            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )

            response.raise_for_status()
            data = response.json()

            segments = data.get("transcript", [])
            if not segments:
                logger.warning(f"Empty transcript returned for {video_id}")
                return None

            return [
                {
                    "text": item["text"],
                    "start": float(item["start"]),
                    "duration": float(item["duration"]),
                }
                for item in segments
                if item.get("text")
            ]

        except Exception as e:
            last_exc = e
            err_str = str(e)
            is_rate_limit = "429" in err_str or "Too Many Requests" in err_str

            if attempt < MAX_RETRIES and is_rate_limit:
                delay = RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                logger.warning(
                    f"Rate limited fetching transcript for {video_id} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES + 1}). "
                    f"Retrying in {delay}s…"
                )
                time.sleep(delay)
            else:
                raise

    raise last_exc


def fetch_transcript(video: Video, db: Session) -> list[dict] | None:
    """
    Fetches transcript for a single video and caches it in the DB.
    Returns parsed transcript (list of {text, start, duration}) or None.
    """
    try:
        parsed = _fetch_transcript_with_retry(video.youtube_video_id)

        if parsed is None:
            return None

        video.transcript_raw = json.dumps(parsed)
        video.transcript_fetched_at = datetime.now(timezone.utc)
        db.commit()

        time.sleep(REQUEST_DELAY_SECONDS)
        return parsed

    except Exception as e:
        logger.error(f"Error fetching transcript for {video.youtube_video_id}: {e}")
        return None


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
    Format: [12.34s] Some text here
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
    Returns deduplicated/merged windows as list of:
      {start_time, end_time, text}
    """
    keyword_lower = [k.lower() for k in keywords]

    # Find all timestamps where a keyword appears
    hit_times = []
    for item in transcript:
        text_lower = item.get("text", "").lower()
        if any(kw in text_lower for kw in keyword_lower):
            hit_times.append(item["start"])

    if not hit_times:
        return []

    # Build windows around each hit, then merge overlapping ones
    windows = []
    for t in hit_times:
        window_start = max(0, t - window_seconds / 2)
        window_end = t + window_seconds / 2
        windows.append((window_start, window_end))

    # Merge overlapping windows
    windows.sort()
    merged = [windows[0]]
    for start, end in windows[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # Extract text for each window
    result = []
    for window_start, window_end in merged:
        window_items = [
            item for item in transcript
            if window_start <= item["start"] <= window_end
        ]
        if window_items:
            text = transcript_to_text_with_timestamps(window_items)
            result.append({
                "start_time": window_start,
                "end_time": window_end,
                "text": text,
            })

    return result
