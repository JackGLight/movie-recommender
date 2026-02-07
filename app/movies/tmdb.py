# app/movies/tmdb.py
from typing import Any, Dict, Optional, Set, List
import requests

TMDB_BASE = "https://api.themoviedb.org/3"


def get_movie_details(api_key: str, tmdb_id: int) -> dict:
    url = f"{TMDB_BASE}/movie/{tmdb_id}"
    r = requests.get(url, params={"api_key": api_key}, timeout=15)
    r.raise_for_status()
    return r.json()


def get_movie_credits(api_key: str, tmdb_id: int) -> dict:
    url = f"{TMDB_BASE}/movie/{tmdb_id}/credits"
    r = requests.get(url, params={"api_key": api_key}, timeout=15)
    r.raise_for_status()
    return r.json()


def discover_movies(
    api_key: str,
    *,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    min_vote: Optional[float] = None,
    min_vote_count: int = 50,
    genres_csv: Optional[str] = None,
    with_cast_csv: Optional[str] = None,
    page: int = 1,
    sort_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Discover movies with basic filters (ONE page).
    genres_csv should be TMDB genre ids as comma-separated string (e.g. "28,35").
    """
    params: dict[str, Any] = {
        "api_key": api_key,
        "language": "en-US",
        "include_adult": "false",
        "include_video": "false",
        "page": page,
    }

    # only include sort_by if provided (TMDB doesn't love sort_by=None)
    if sort_by:
        params["sort_by"] = sort_by

    if year_from:
        params["primary_release_date.gte"] = f"{year_from}-01-01"
    if year_to:
        params["primary_release_date.lte"] = f"{year_to}-12-31"

    if min_vote is not None:
        params["vote_average.gte"] = float(min_vote)

    # ✅ IMPORTANT: apply vote_count filter even if min_vote is None
    if min_vote_count is not None and int(min_vote_count) > 0:
        params["vote_count.gte"] = int(min_vote_count)

    if genres_csv:
        params["with_genres"] = genres_csv
    if with_cast_csv:
        params["with_cast"] = with_cast_csv

    r = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def discover_movies_multi(
    api_key: str,
    *,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    min_vote: Optional[float] = None,
    min_vote_count: int = 50,
    genres_csv: Optional[str] = None,
    with_cast_csv: Optional[str] = None,
    pages: int = 3,
    sort_by: Optional[str] = None,
) -> List[dict]:
    """
    Fetch multiple pages from /discover/movie, merge, and de-dupe by TMDB id.
    Returns a flat list of movie dicts.
    """
    pages = max(1, min(int(pages), 20))  # keep it reasonable for speed

    all_results: List[dict] = []
    seen_ids: Set[int] = set()

    for page in range(1, pages + 1):
        data = discover_movies(
            api_key,
            year_from=year_from,
            year_to=year_to,
            min_vote=min_vote,
            min_vote_count=min_vote_count,
            genres_csv=genres_csv,
            with_cast_csv=with_cast_csv,
            page=page,
            sort_by=sort_by,
        )

        results = data.get("results") or []
        if not results:
            break

        for m in results:
            mid = m.get("id")
            if not isinstance(mid, int):
                continue
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            all_results.append(m)

    return all_results


def search_person_id(api_key: str, name: str) -> int | None:
    """
    Returns the best-match TMDB person id for a given name, or None.
    """
    name = (name or "").strip()
    if not name:
        return None

    r = requests.get(
        f"{TMDB_BASE}/search/person",
        params={"api_key": api_key, "query": name, "include_adult": "false"},
        timeout=15,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        return None
    return results[0].get("id")


def get_movie_cast_ids(api_key: str, tmdb_movie_id: int) -> Set[int]:
    """
    Return a set of person IDs in the cast for a movie.
    """
    r = requests.get(
        f"{TMDB_BASE}/movie/{tmdb_movie_id}/credits",
        params={"api_key": api_key},
        timeout=15,
    )
    r.raise_for_status()
    cast = r.json().get("cast", [])
    return {p["id"] for p in cast if "id" in p}


def get_imdb_id(api_key: str, tmdb_movie_id: int) -> str | None:
    r = requests.get(
        f"{TMDB_BASE}/movie/{tmdb_movie_id}/external_ids",
        params={"api_key": api_key},
        timeout=15,
    )
    r.raise_for_status()
    imdb_id = r.json().get("imdb_id")
    return imdb_id or None