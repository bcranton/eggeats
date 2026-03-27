"""
Uses Claude API to extract business mentions from transcript segments.
Handles typo resolution, sentiment analysis, and uncertainty flagging.
"""
import json
import logging
import time
from typing import Any

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are analyzing a YouTube video transcript from Northernlion (NL), a content creator based in Vancouver, BC, Canada who also travels to other cities. He frequently mentions local businesses, restaurants, cafes, bars, attractions, and other places.

Transcript segment with timestamps (format: [Ns] text):
<transcript>
{transcript_text}
</transcript>

Video title: "{video_title}"
Published: {published_date}
City context: {city_name}, {country}

Your task: Extract every mention of a local business, restaurant, cafe, bar, attraction, shop, or place in or near {city_name}. Focus on named businesses/places only (not generic mentions like "a restaurant" or "the mall").

For each mention, return a JSON object with these fields:
- "raw_name": the name exactly as spoken/written in the transcript (may have typos/errors)
- "canonical_name": your best guess at the correct business name (fix typos, use full proper name)
- "category": one of "restaurant", "cafe", "bar", "shop", "attraction", "bakery", "market", "other"
- "sentiment": one of "positive", "negative", "neutral", "mixed"
- "sentiment_score": float from -1.0 (very negative) to 1.0 (very positive)
- "quotes": array of verbatim transcript quotes (1-3 sentences max each) that express an opinion about this place
- "timestamp_seconds": approximate timestamp in seconds from the video start (use the [Ns] markers)
- "confidence": float 0.0-1.0 — how confident you are that "canonical_name" is correct
- "is_closed": true if the transcript implies the business is/was closed or no longer exists, false otherwise, null if unknown
- "needs_review": true if confidence < 0.7 OR you are uncertain about the name OR multiple businesses could match
- "notes": brief note about any uncertainty (empty string if none)

Rules:
- Include closed/defunct businesses (NL's opinion is still historically valuable)
- Transcript auto-captions often have errors — use context to determine the real business name
- Common Vancouver/Metro Vancouver businesses: La Glace (candy shop), Tacofino, Burdock & Co, Odd Society Spirits, etc. Burnaby and surrounding suburbs (Richmond, Surrey, North Vancouver, etc.) are part of the Metro Vancouver area.
- Only include places NL actually talks about with some specificity — not passing one-word mentions with no context
- If a business is mentioned multiple times in the segment, only include it once (use the richest context)
- Do NOT invent sentiment — if NL doesn't express an opinion, use "neutral"

Return ONLY a valid JSON array. Return [] if no businesses are mentioned. No markdown, no explanation."""


def extract_businesses_from_segment(
    transcript_text: str,
    video_title: str,
    published_date: str,
    city_name: str,
    country: str,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """
    Calls Claude API to extract business mentions from a transcript segment.
    Returns list of business mention dicts.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    prompt = EXTRACTION_PROMPT.format(
        transcript_text=transcript_text,
        video_title=video_title,
        published_date=published_date,
        city_name=city_name,
        country=country,
    )

    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = message.content[0].text.strip()

            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[-1]
                if raw_text.endswith("```"):
                    raw_text = raw_text.rsplit("```", 1)[0]

            results = json.loads(raw_text)
            if not isinstance(results, list):
                logger.warning("LLM returned non-list response, wrapping in list")
                results = [results] if results else []

            return results

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except anthropic.RateLimitError:
            wait = 2 ** (attempt + 2)
            logger.warning(f"Rate limited, waiting {wait}s before retry {attempt + 1}")
            time.sleep(wait)
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    logger.error("All LLM extraction attempts failed")
    return []


def extract_businesses_from_video(
    transcript: list[dict],
    keyword_windows: list[dict],
    video_title: str,
    published_date: str,
    city_name: str,
    country: str,
) -> list[dict[str, Any]]:
    """
    Processes all keyword windows for a video and returns combined extractions.
    Deduplicates by canonical_name (keeps the one with higher confidence).
    """
    all_results: list[dict] = []

    for window in keyword_windows:
        logger.info(
            f"Processing window {window['start_time']:.0f}s - {window['end_time']:.0f}s"
        )
        results = extract_businesses_from_segment(
            transcript_text=window["text"],
            video_title=video_title,
            published_date=published_date,
            city_name=city_name,
            country=country,
        )
        all_results.extend(results)

    # Deduplicate by canonical_name (case-insensitive), keeping highest confidence
    seen: dict[str, dict] = {}
    for result in all_results:
        key = result.get("canonical_name", "").lower().strip()
        if not key:
            continue
        if key not in seen or result.get("confidence", 0) > seen[key].get("confidence", 0):
            seen[key] = result

    return list(seen.values())
