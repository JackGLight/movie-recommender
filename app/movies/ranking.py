from datetime import datetime
import math

def rank_movies(movies: list[dict]) -> list[dict]:
    """
    Rank movies so that well-known / widely-rated movies rise to the top.
    Uses log vote_count to avoid a few mega-hits dominating too hard.
    """
    current_year = datetime.now().year

    def score(m: dict) -> float:
        vote_avg = float(m.get("vote_average") or 0)
        vote_count = float(m.get("vote_count") or 0)
        popularity = float(m.get("popularity") or 0)

        year = 0
        if m.get("release_date"):
            try:
                year = int(m["release_date"][:4])
            except ValueError:
                year = 0

        # 0..1-ish boost for last 15 years
        recency_boost = max(0.0, year - (current_year - 15)) / 15.0

        # log scales for “mainstream signal”
        vc = math.log10(vote_count + 1.0)     # 0..6ish
        pop = math.log10(popularity + 1.0)   # 0..3ish

        return (
            0.55 * vote_avg +   # still important
            0.30 * vc +         # mainstream signal (strong)
            0.12 * pop +        # secondary mainstream signal
            0.03 * recency_boost
        )

    return sorted(movies, key=score, reverse=True)