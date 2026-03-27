"""
Geocodes businesses using Google Places API (New).
Resolves business names and gets lat/lng coordinates.
"""
import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Confidence threshold — below this we flag for admin review
GEOCODE_CONFIDENCE_THRESHOLD = 0.7
REQUEST_DELAY_SECONDS = 0.3  # respect rate limits

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Fields to request from Text Search
TEXT_SEARCH_FIELDS = "places.id,places.displayName,places.formattedAddress,places.location"

# Fields to request from Place Details
DETAILS_FIELDS = "id,displayName,formattedAddress,location,businessStatus,types"


def search_place(
    business_name: str,
    city_name: str,
    country: str,
) -> dict[str, Any] | None:
    """
    Searches Google Places (New) Text Search for a business.
    Returns the first place result dict or None.
    """
    settings = get_settings()
    query = f"{business_name} {city_name} {country}"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": TEXT_SEARCH_FIELDS,
    }
    body = {"textQuery": query}

    try:
        response = httpx.post(PLACES_TEXT_SEARCH_URL, json=body, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        places = data.get("places", [])
        if places:
            return places[0]

        logger.info(f"No Places results for: {query}")
        return None

    except httpx.HTTPStatusError as e:
        logger.warning(f"Places Text Search HTTP {e.response.status_code} for '{query}': {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Places Text Search error for '{business_name}': {e}")
        return None
    finally:
        time.sleep(REQUEST_DELAY_SECONDS)


def get_place_details(place_id: str) -> dict[str, Any] | None:
    """
    Fetches detailed info for a place by place_id (New API format).
    Returns place details dict or None.
    """
    settings = get_settings()
    url = PLACES_DETAILS_URL.format(place_id=place_id)

    headers = {
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": DETAILS_FIELDS,
    }

    try:
        response = httpx.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as e:
        logger.warning(f"Place Details HTTP {e.response.status_code} for {place_id}: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Place Details error for {place_id}: {e}")
        return None
    finally:
        time.sleep(REQUEST_DELAY_SECONDS)


def name_similarity(a: str, b: str) -> float:
    """
    Simple name similarity score — ratio of matching chars.
    Used to validate that Places result matches our expected business.
    """
    a = a.lower().strip()
    b = b.lower().strip()
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.8
    # Character-level overlap
    common = sum(1 for c in a if c in b)
    return common / max(len(a), len(b), 1)


def geocode_business(
    canonical_name: str,
    city_name: str,
    country: str,
    llm_confidence: float = 1.0,
) -> dict[str, Any]:
    """
    Geocodes a business using Google Places (New).
    Returns dict with geocoding results and a needs_review flag.

    Return structure:
    {
        "name": str,
        "lat": float | None,
        "lng": float | None,
        "google_place_id": str | None,
        "address": str | None,
        "website": str | None,
        "category": str | None,
        "is_closed": bool,
        "needs_review": bool,
        "geocode_confidence": float,
    }
    """
    result = {
        "name": canonical_name,
        "lat": None,
        "lng": None,
        "google_place_id": None,
        "address": None,
        "website": None,
        "category": None,
        "is_closed": False,
        "needs_review": False,
        "geocode_confidence": 0.0,
    }

    place = search_place(canonical_name, city_name, country)
    if not place:
        result["needs_review"] = True
        logger.info(f"No geocode result for '{canonical_name}' — flagging for review")
        return result

    # New API: place_id is under "id", display name under "displayName.text"
    place_id = place.get("id")
    if not place_id:
        result["needs_review"] = True
        return result

    places_name = place.get("displayName", {}).get("text", "")
    similarity = name_similarity(canonical_name, places_name)

    # Fetch full details
    details = get_place_details(place_id)
    if details:
        location = details.get("location", {})
        result["lat"] = location.get("latitude")
        result["lng"] = location.get("longitude")
        result["google_place_id"] = place_id
        result["address"] = details.get("formattedAddress")
        result["name"] = details.get("displayName", {}).get("text", canonical_name)

        business_status = details.get("businessStatus", "")
        result["is_closed"] = business_status in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY")

        types = details.get("types", [])
        result["category"] = _map_types_to_category(types)
    else:
        # Fall back to text search result
        location = place.get("location", {})
        result["lat"] = location.get("latitude")
        result["lng"] = location.get("longitude")
        result["google_place_id"] = place_id
        result["address"] = place.get("formattedAddress")
        result["name"] = places_name or canonical_name

    # Overall confidence: combine LLM confidence and name similarity
    geocode_confidence = (llm_confidence + similarity) / 2
    result["geocode_confidence"] = geocode_confidence

    if geocode_confidence < GEOCODE_CONFIDENCE_THRESHOLD:
        result["needs_review"] = True
        logger.info(
            f"Low confidence ({geocode_confidence:.2f}) for '{canonical_name}' → '{places_name}' — flagging"
        )

    return result


def geocode_address(address_str: str) -> dict[str, Any]:
    """
    Geocodes a raw address string (e.g. manually entered by admin).
    Returns {"address": str, "lat": float|None, "lng": float|None}.
    Uses Places Text Search with the full address as the query.
    """
    place = search_place(address_str, "", "")
    if not place:
        return {"address": address_str, "lat": None, "lng": None}

    location = place.get("location", {})
    formatted = place.get("formattedAddress") or address_str

    # Try to get more accurate coords from Details
    place_id = place.get("id")
    if place_id:
        details = get_place_details(place_id)
        if details:
            location = details.get("location", location)
            formatted = details.get("formattedAddress", formatted)

    return {
        "address": formatted,
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
    }


def _map_types_to_category(types: list[str]) -> str:
    """Maps Google Places types to our simplified categories."""
    type_map = {
        "restaurant": "restaurant",
        "cafe": "cafe",
        "bakery": "bakery",
        "bar": "bar",
        "food": "restaurant",
        "meal_takeaway": "restaurant",
        "meal_delivery": "restaurant",
        "night_club": "bar",
        "liquor_store": "shop",
        "grocery_or_supermarket": "market",
        "supermarket": "market",
        "convenience_store": "shop",
        "shopping_mall": "shop",
        "clothing_store": "shop",
        "book_store": "shop",
        "tourist_attraction": "attraction",
        "museum": "attraction",
        "park": "attraction",
        "amusement_park": "attraction",
        "stadium": "attraction",
        "movie_theater": "attraction",
    }
    for t in types:
        if t in type_map:
            return type_map[t]
    return "other"
