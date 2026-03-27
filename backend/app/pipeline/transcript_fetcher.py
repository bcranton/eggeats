"""
Fetches YouTube video transcripts using youtube-transcript-api.
Prefers manually-created transcripts; falls back to auto-generated.
"""
import json
import logging
import time
from datetime import datetime, timezone

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
)
from sqlalchemy.orm import Session

from app.models import Video, ProcessingStatus

logger = logging.getLogger(__name__)

# Delay between successful API calls to avoid rate limiting
REQUEST_DELAY_SECONDS = 2.0

# Retry settings for 429 / transient errors
MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 30  # first retry after 30s, then 60s, 120s, 240s


def _fetch_transcript_with_retry(video_id: str):
    """
    Fetches transcript with exponential backoff on 429 / transient errors.
    Returns (transcript_list, transcript) or raises on non-retryable error.
    """
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

            transcript = None
            try:
                transcript = transcript_list.find_manually_created_transcript(["en", "en-US", "en-GB"])
            except NoTranscriptFound:
                try:
                    transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
                except NoTranscriptFound:
                    # Try any available transcript
                    for t in transcript_list:
                        transcript = t
                        break

            return transcript

        except (TranscriptsDisabled, NoTranscriptFound):
            raise  # Non-retryable — surface immediately
        except Exception as e:
            last_exc = e
            err_str = str(e)
            is_rate_limit = "429" in err_str or "Too Many Requests" in err_str or "sorry" in err_str.lower()

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
        transcript = _fetch_transcript_with_retry(video.youtube_video_id)

        if transcript is None:
            logger.warning(f"No transcript found for {video.youtube_video_id}")
            return None

        data = transcript.fetch()
        # Convert FetchedTranscript to plain list of dicts
        parsed = [{"text": item["text"], "start": item["start"], "duration": item["duration"]}
                  for item in data]

        video.transcript_raw = json.dumps(parsed)
        video.transcript_fetched_at = datetime.now(timezone.utc)
        db.commit()

        time.sleep(REQUEST_DELAY_SECONDS)
        return parsed

    except TranscriptsDisabled:
        logger.warning(f"Transcripts disabled for {video.youtube_video_id}")
        return None
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
