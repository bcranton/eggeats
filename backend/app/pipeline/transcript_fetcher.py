"""
Fetches YouTube video transcripts via hosted transcript API.
Uses https://github.com/jaypaun007/youtube-transcript-api to avoid
IP-based rate limiting on the Railway server.

The API returns plain text (no timestamps), so we split into word-chunk
segments and estimate timestamps from average speaking rate.
"""
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Video, ProcessingStatus

logger = logging.getLogger(__name__)

TRANSCRIPT_API_URL = "https://youtube-transcript-api-tau-one.vercel.app/transcript"

# 5 requests/minute limit on the hosted API → minimum 12s between requests.
# Using 13s for a small safety buffer.
REQUEST_DELAY_SECONDS = 13.0

# Retry settings for transient errors (429, 5xx, timeouts)
MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 30  # 30s, 60s, 120s, 240s

# Plain-text splitting: ~150 wpm = 2.5 words/second; 50 words ≈ 20s per chunk
_WORDS_PER_CHUNK = 50
_WORDS_PER_SECOND = 2.5


def _plain_text_to_segments(text: str) -> list[dict]:
    """
    Splits a plain-text transcript into word-chunk pseudo-segments with
    estimated timestamps. Timestamps are approximated from average speaking
    rate since the hosted API returns no timing data.
    """
    words = text.split()
    segments = []
    for i in range(0, len(words), _WORDS_PER_CHUNK):
        chunk = " ".join(words[i:i + _WORDS_PER_CHUNK])
        estimated_start = i / _WORDS_PER_SECOND
        segments.append({
            "text": chunk,
            "start": estimated_start,
            "duration": _WORDS_PER_CHUNK / _WORDS_PER_SECOND,
        })
    return segments


def _fetch_transcript_with_retry(video_id: str) -> list[dict] | None:
    """
    Fetches transcript from the hosted API with exponential backoff on errors.
    Returns a list of {text, start, duration} pseudo-segments, or None if unavailable.
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    last_exc = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = httpx.post(
                TRANSCRIPT_API_URL,
                json={"url": video_url},
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

            text = data.get("transcript", "").strip() if isinstance(data, dict) else ""
            if not text:
                logger.warning(f"Empty transcript returned for {video_id}")
                return None

            segments = _plain_text_to_segments(text)
            logger.info(f"Fetched transcript for {video_id}: {len(text.split())} words → {len(segments)} segments")
            return segments

        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                logger.warning(
                    f"Transcript fetch failed for {video_id} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}. "
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
