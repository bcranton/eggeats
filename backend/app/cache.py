"""
Simple server-side in-memory TTL cache using cachetools.

Values are stored as UTF-8 JSON bytes rather than Python objects. This cuts
RAM usage by 3-5x because Python dicts/lists carry significant pointer and
object-header overhead that disappears when serialised to a compact string.
The CPU cost of json.dumps/loads is negligible given that CF handles most
traffic and Railway only sees occasional cache misses.

Admin writes call cache_invalidate_prefix() / cache_clear() immediately so
changes are visible on the next request without waiting for TTL expiry.
"""
import json
import threading
from cachetools import TTLCache
from fastapi.encoders import jsonable_encoder

# 2-hour TTL, max 256 cached entries (more than enough for our endpoints)
CACHE_TTL = 7200
_cache: TTLCache = TTLCache(maxsize=256, ttl=CACHE_TTL)
_lock = threading.Lock()


def cache_get(key: str):
    with _lock:
        raw = _cache.get(key)
    if raw is None:
        return None
    return json.loads(raw)


def cache_set(key: str, value) -> None:
    raw = json.dumps(jsonable_encoder(value))
    with _lock:
        _cache[key] = raw


def cache_invalidate_prefix(prefix: str) -> None:
    """Removes all keys that start with the given prefix."""
    with _lock:
        keys_to_delete = [k for k in list(_cache.keys()) if k.startswith(prefix)]
        for k in keys_to_delete:
            del _cache[k]


def cache_clear() -> None:
    with _lock:
        _cache.clear()
