# app/movies/ranking.py
from datetime import datetime

def rank_movies(movies: list[dict]) -> list[dict]:
    """
    Compute a simple weighted score and return movies sorted best → worst.
    """
    current_year = datetime.now().year

    def score(m: dict) -> float:
        vote_avg = m.get("vote_average") or 0
        vote_count = m.get("vote_count") or 0
        popularity = m.get("popularity") or 0

        year = 0
        if m.get("release_date"):
            try:
                year = int(m["release_date"][:4])
            except ValueError:
                year = 0

        recency_boost = max(0, year - (current_year - 10)) / 10

        return (
            0.5 * vote_avg +
            0.2 * (vote_count ** 0.5) +
            0.2 * (popularity ** 0.3) +
            0.1 * recency_boost
        )

    return sorted(movies, key=score, reverse=True)