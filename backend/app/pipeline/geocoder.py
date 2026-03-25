"""
Geocodes businesses using Google Places API.
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
REQUEST_DELAY_SECONDS = 0.3  # respect 1 QPS limit

PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def search_place(
    business_name: str,
    city_name: str,
    country: str,
) -> dict[str, Any] | None:
    """
    Searches Google Places Text Search for a business.
    Returns place result dict or None.
    """
    settings = get_settings()
    query = f"{business_name} {city_name} {country}"

    params = {
        "query": query,
        "key": settings.google_places_api_key,
    }

    try:
        response = httpx.get(PLACES_TEXT_SEARCH_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "OK" and data.get("results"):
            return data["results"][0]
        elif data.get("status") == "ZERO_RESULTS":
            logger.info(f"No Places results for: {query}")
            return None
        else:
            logger.warning(f"Places API status: {data.get('status')} for query: {query}")
            return None

    except Exception as e:
        logger.error(f"Places Text Search error for '{business_name}': {e}")
        return None
    finally:
        time.sleep(REQUEST_DELAY_SECONDS)


def get_place_details(place_id: str) -> dict[str, Any] | None:
    """
    Fetches detailed info for a place by place_id.
    Returns place details dict or None.
    """
    settings = get_settings()
    params = {
        "place_id": place_id,
        "fields": "name,formatted_address,website,geometry,business_status,types",
        "key": settings.google_places_api_key,
    }

    try:
        response = httpx.get(PLACES_DETAILS_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "OK":
            return data.get("result")
        else:
            logger.warning(f"Place Details API status: {data.get('status')} for {place_id}")
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
    Geocodes a business using Google Places.
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

    place_id = place.get("place_id")
    if not place_id:
        result["needs_review"] = True
        return result

    # Check name similarity between our name and Places result
    places_name = place.get("name", "")
    similarity = name_similarity(canonical_name, places_name)

    # Fetch full details
    details = get_place_details(place_id)
    if details:
        geometry = details.get("geometry", {}).get("location", {})
        result["lat"] = geometry.get("lat")
        result["lng"] = geometry.get("lng")
        result["google_place_id"] = place_id
        result["address"] = details.get("formatted_address")
        result["website"] = details.get("website")
        result["name"] = details.get("name", canonical_name)

        # Determine if closed
        business_status = details.get("business_status", "")
        result["is_closed"] = business_status in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY")

        # Map Google types to our categories
        types = details.get("types", [])
        result["category"] = _map_types_to_category(types)
    else:
        # Fall back to text search result
        geometry = place.get("geometry", {}).get("location", {})
        result["lat"] = geometry.get("lat")
        result["lng"] = geometry.get("lng")
        result["google_place_id"] = place_id
        result["address"] = place.get("formatted_address")
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
