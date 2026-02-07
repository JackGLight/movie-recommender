import requests

TMDB_BASE = "https://api.themoviedb.org/3"

def fetch_genres(api_key: str) -> list[dict]:
    r = requests.get(
        f"{TMDB_BASE}/genre/movie/list",
        params={"api_key": api_key, "language": "en-US"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("genres", [])