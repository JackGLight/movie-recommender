# app/movies/dtdd.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import time
import requests
from urllib.parse import quote_plus

DTDD_BASE = "https://www.doesthedogdie.com"

# In-memory caches (good enough for MVP)
_search_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_media_cache: Dict[int, tuple[float, Dict[str, Any]]] = {}

TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _fresh(ts: float) -> bool:
    return (time.time() - ts) < TTL_SECONDS


def _headers(api_key: str) -> Dict[str, str]:
    return {"Accept": "application/json", "X-API-KEY": api_key}


def dtdd_search(api_key: str, query: str) -> Optional[Dict[str, Any]]:
    """
    Calls /dddsearch?q=... and returns the JSON payload.
    Cached by query string.
    """
    if not api_key:
        return None

    q = (query or "").strip().lower()
    if not q:
        return None

    cached = _search_cache.get(q)
    if cached and _fresh(cached[0]):
        return cached[1]

    url = f"{DTDD_BASE}/dddsearch?q={quote_plus(q)}"
    r = requests.get(url, headers=_headers(api_key), timeout=15)
    r.raise_for_status()
    payload = r.json()

    _search_cache[q] = (time.time(), payload)
    return payload


def dtdd_search_imdb(api_key: str, imdb_id: str) -> Optional[Dict[str, Any]]:
    if not api_key:
        return None
    imdb_id = (imdb_id or "").strip()
    if not imdb_id:
        return None

    cache_key = f"imdb:{imdb_id.lower()}"
    cached = _search_cache.get(cache_key)
    if cached and _fresh(cached[0]):
        return cached[1]

    url = f"{DTDD_BASE}/dddsearch?imdb={quote_plus(imdb_id)}"
    r = requests.get(url, headers=_headers(api_key), timeout=15)
    r.raise_for_status()
    payload = r.json()

    _search_cache[cache_key] = (time.time(), payload)
    return payload



def dtdd_media(api_key: str, item_id: int) -> Optional[Dict[str, Any]]:
    """
    Calls /media/{itemId} and returns the JSON payload.
    Cached by item_id.
    """
    if not api_key:
        return None

    cached = _media_cache.get(item_id)
    if cached and _fresh(cached[0]):
        return cached[1]

    url = f"{DTDD_BASE}/media/{item_id}"
    r = requests.get(url, headers=_headers(api_key), timeout=15)
    r.raise_for_status()
    payload = r.json()

    _media_cache[item_id] = (time.time(), payload)
    return payload


def pick_best_item(items: list[dict], tmdb_id: int | None, year: int | None) -> Optional[dict]:
    """
    Choose the best DTDD item from /dddsearch results.
    Priority:
      1) exact tmdbId match
      2) matching releaseYear
      3) first item
    """
    if not items:
        return None

    if tmdb_id is not None:
        for it in items:
            if it.get("tmdbId") == tmdb_id:
                return it

    if year is not None:
        for it in items:
            try:
                if int(it.get("releaseYear") or 0) == year:
                    return it
            except Exception:
                pass

    return items[0]


def get_release_year(tmdb_movie: dict) -> Optional[int]:
    rd = tmdb_movie.get("release_date") or ""
    if len(rd) >= 4 and rd[:4].isdigit():
        return int(rd[:4])
    return None


def dog_dies_from_media(media_payload):
    """
    Return:
      True  -> dog dies (unsafe)
      False -> dog does NOT die (safe)
      None  -> unknown
    """
    if not media_payload:
        return None

    stats = media_payload.get("topicItemStats") or []
    # TEMP DEBUG: show first ~20 topics returned by DTDD
    # print("[DTDD TOPICS]",
    #   [( (e.get("topic") or {}).get("doesName"),
    #      (e.get("topic") or {}).get("name"),
    #      (e.get("topic") or {}).get("legacyId"),
    #      e.get("isYes"))
    #    for e in stats[:20]])
    for entry in stats:
        topic = entry.get("topic") or {}

        legacy_id = topic.get("legacyId")
        does_name = (topic.get("doesName") or "").strip().lower()
        topic_name = (topic.get("name") or "").strip().lower()

        # Most stable: legacyId for "Does the dog die" topic appears as 25 in your example
        is_dog_dies_topic = (
            legacy_id == 25
            or "does the dog die" in does_name
            or topic_name == "a dog dies"
            or "dog die" in topic_name
        )

        if is_dog_dies_topic:
            # Prefer explicit isYes if present
            is_yes = entry.get("isYes")
            if isinstance(is_yes, bool):
                return is_yes
            if isinstance(is_yes, int):
                return bool(is_yes)

            # Otherwise infer from vote totals
            yes_sum = entry.get("yesSum")
            no_sum = entry.get("noSum")

            if isinstance(yes_sum, int) and isinstance(no_sum, int):
                if yes_sum == 0 and no_sum == 0:
                    return None  # truly unknown / no votes
                return yes_sum > no_sum

            # If missing totals, unknown
            return None

    return None


def is_animal_safe_v1(api_key: str, tmdb_movie: dict, imdb_id: str | None = None) -> Optional[bool]:
    """
    Determine if movie is animal-safe w.r.t. 'a dog dies' topic.
    Returns:
      True  -> safe (dog does not die)
      False -> unsafe (dog dies)
      None  -> unknown
    """
    title = (tmdb_movie.get("title") or "").strip()
    if not title:
        return None

    tmdb_id = tmdb_movie.get("id")
    year = get_release_year(tmdb_movie)

    if imdb_id:
        search_payload = dtdd_search_imdb(api_key, imdb_id)
    else:
        search_payload = dtdd_search(api_key, title)

    if not search_payload:
        return None

    items = search_payload.get("items") or []
    best = pick_best_item(items, tmdb_id=tmdb_id, year=year)
    if not best:
        return None

    item_id = best.get("id")
    if not item_id:
        return None

    media_payload = dtdd_media(api_key, int(item_id))
    dog_dies = dog_dies_from_media(media_payload)
    if dog_dies is None:
        return None

    # safe if dog does NOT die
    return (dog_dies is False)