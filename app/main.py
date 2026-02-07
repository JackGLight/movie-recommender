from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.movies.tmdb import get_movie_details, get_movie_credits

from app.config import TMDB_API_KEY, DTDD_API_KEY
from app.db import engine, SessionLocal
from app.models import Base, WatchedMovie

from app.movies.dtdd import is_animal_safe_v1
from app.movies.genres import fetch_genres
from app.movies.ranking import rank_movies
from app.movies.tmdb import (
    discover_movies_multi,   # ✅ use multi-page helper
    search_person_id,
    get_movie_cast_ids,
    get_imdb_id,
)

# Create DB tables (SQLite) on startup
Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def home(request: Request):
    genres = fetch_genres(TMDB_API_KEY)
    return templates.TemplateResponse(
        "search.html",
        {"request": request, "genres": genres},
    )


@app.get("/watched")
def watched(request: Request):
    db = SessionLocal()
    try:
        rows = db.query(WatchedMovie).filter(WatchedMovie.user_id == 1).all()
    finally:
        db.close()

    return templates.TemplateResponse(
        "watched.html",
        {"request": request, "rows": rows},
    )


@app.get("/movie/{tmdb_id}")
def movie_detail(request: Request, tmdb_id: int):
    movie = get_movie_details(TMDB_API_KEY, tmdb_id)

    # Credits (cast)
    cast = []
    try:
        credits = get_movie_credits(TMDB_API_KEY, tmdb_id)
        cast = credits.get("cast") or []
    except Exception as e:
        print(f"[WARN] credits failed for {tmdb_id}: {e}")
        cast = []

    # Dog safety (DTDD)
    imdb = None
    try:
        imdb = get_imdb_id(TMDB_API_KEY, tmdb_id)
    except Exception as e:
        print(f"[WARN] imdb lookup failed for {tmdb_id}: {e}")

    safe = is_animal_safe_v1(DTDD_API_KEY, movie, imdb_id=imdb)
    if safe is True:
        movie["dtdd_dog_safe"] = "safe"
    elif safe is False:
        movie["dtdd_dog_safe"] = "unsafe"
    else:
        movie["dtdd_dog_safe"] = "unknown"

    # Watched state (for user_id=1 MVP)
    db = SessionLocal()
    try:
        watched = (
            db.query(WatchedMovie)
            .filter_by(user_id=1, tmdb_id=tmdb_id)
            .first()
        )
    finally:
        db.close()

    movie["is_watched"] = watched is not None
    cast = cast[:12]

    return templates.TemplateResponse(
        "movie.html",
        {"request": request, "movie": movie, "cast": cast},
    )


@app.post("/watched")
def mark_watched(
    request: Request,
    tmdb_id: int = Form(...),
    title: str = Form(...),
):
    db = SessionLocal()
    try:
        exists = (
            db.query(WatchedMovie)
            .filter(WatchedMovie.user_id == 1, WatchedMovie.tmdb_id == tmdb_id)
            .first()
        )
        if not exists:
            db.add(WatchedMovie(user_id=1, tmdb_id=tmdb_id, title=title))
            db.commit()
    finally:
        db.close()

    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            f"""
            <div id="watched-{tmdb_id}">
              <p class="muted"><strong>Watched ✅</strong></p>
              <form hx-post="/watched/remove"
                    hx-target="#watched-{tmdb_id}"
                    hx-swap="outerHTML"
                    style="margin:0;">
                <input type="hidden" name="tmdb_id" value="{tmdb_id}">
                <input type="hidden" name="title" value="{title}">
                <button type="submit">Undo</button>
              </form>
            </div>
            """
        )

    return RedirectResponse(url="/watched", status_code=303)


@app.post("/watched/remove")
def remove_watched(
    request: Request,
    tmdb_id: int = Form(...),
    title: str = Form(...),
):
    db = SessionLocal()
    try:
        db.query(WatchedMovie).filter(
            WatchedMovie.user_id == 1,
            WatchedMovie.tmdb_id == tmdb_id,
        ).delete()
        db.commit()
    finally:
        db.close()

    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            f"""
            <div id="watched-{tmdb_id}">
              <form hx-post="/watched"
                    hx-target="#watched-{tmdb_id}"
                    hx-swap="outerHTML"
                    style="margin:0;">
                <input type="hidden" name="tmdb_id" value="{tmdb_id}">
                <input type="hidden" name="title" value="{title}">
                <button type="submit">Mark watched</button>
              </form>
            </div>
            """
        )

    return RedirectResponse(url="/watched", status_code=303)


@app.post("/search")
def search(
    request: Request,
    year_from: int | None = Form(default=None),
    year_to: int | None = Form(default=None),
    min_vote: float | None = Form(default=None),
    genres_csv: str | None = Form(default=None),
    include_actors: str | None = Form(default=None),
    exclude_actors: str | None = Form(default=None),
    no_animal_harm: str | None = Form(default=None),
):
    no_animal_harm = bool(no_animal_harm)

    def split_names(s: str | None) -> list[str]:
        if not s:
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    include_names = split_names(include_actors)
    exclude_names = split_names(exclude_actors)

    include_ids = [search_person_id(TMDB_API_KEY, n) for n in include_names]
    include_ids = [i for i in include_ids if i is not None]

    exclude_ids = [search_person_id(TMDB_API_KEY, n) for n in exclude_names]
    exclude_ids = [i for i in exclude_ids if i is not None]

    with_cast_csv = ",".join(str(i) for i in include_ids) if include_ids else None

    # --- watched IDs for MVP user_id=1 ---
    db = SessionLocal()
    try:
        watched_ids = {
            w.tmdb_id
            for w in db.query(WatchedMovie).filter(WatchedMovie.user_id == 1).all()
        }
    finally:
        db.close()

    SORT_BY = "vote_count.desc"

    # -------------------------
    # Option B: fallback ladder
    # -------------------------
    # What "enough" means for you
    MIN_RESULTS_TARGET = 20

    # Expand pages when filters are strict
    pages = 5
    if min_vote is not None and min_vote >= 8.0:
        pages = 10

    # Build attempts (strict -> loose)
    attempts: list[tuple[float | None, int, str | None]] = [
        (min_vote, 200, None),
        (min_vote, 100, "Too few results — lowered minimum review count to 100."),
        (min_vote, 50,  "Too few results — lowered minimum review count to 50."),
    ]

    # If they set a super-high rating, allow rating fallback too
    if min_vote is not None and min_vote >= 8.5:
        attempts += [
            (8.0, 100, "Too few results at 8.5+ — showing 8.0+ with at least 100 reviews."),
            (7.5, 100, "Still too few — showing 7.5+ with at least 100 reviews."),
        ]

    movies: list[dict] = []
    results_note: str | None = None

    for mv, mvc, note in attempts:
        movies = discover_movies_multi(
            TMDB_API_KEY,
            year_from=year_from,
            year_to=year_to,
            min_vote=mv,
            min_vote_count=mvc,
            genres_csv=genres_csv,
            with_cast_csv=with_cast_csv,
            pages=pages,
            sort_by=SORT_BY,
        )

        # Remove watched movies from results
        movies = [m for m in movies if m.get("id") not in watched_ids]

        # If we have enough, stop here
        if len(movies) >= MIN_RESULTS_TARGET:
            results_note = note
            break

        # Otherwise try next fallback
        results_note = note

    # --- DTDD: annotate + optionally filter unsafe dogs ---
    MAX_DTDD_CHECK = 25
    checked: list[dict] = []

    for m in movies[:MAX_DTDD_CHECK]:
        mid = m.get("id")
        imdb = None

        if mid:
            try:
                imdb = get_imdb_id(TMDB_API_KEY, mid)
            except Exception as e:
                print(f"[WARN] TMDB external_ids failed for {mid}: {e}")

        safe = is_animal_safe_v1(DTDD_API_KEY, m, imdb_id=imdb)

        m["is_watched"] = (m.get("id") in watched_ids)

        if safe is True:
            m["dtdd_dog_safe"] = "safe"
        elif safe is False:
            m["dtdd_dog_safe"] = "unsafe"
        else:
            m["dtdd_dog_safe"] = "unknown"

        if no_animal_harm and safe is False:
            continue

        checked.append(m)

    for m in movies[MAX_DTDD_CHECK:]:
        m.setdefault("dtdd_dog_safe", "unknown")
        m["is_watched"] = (m.get("id") in watched_ids)

    movies = checked + movies[MAX_DTDD_CHECK:]

    # --- Exclude actors (slow MVP: credits lookup) ---
    if exclude_ids:
        filtered = []
        exclude_set = set(exclude_ids)

        for m in movies:
            mid = m.get("id")
            if not mid:
                continue

            try:
                cast_ids = get_movie_cast_ids(TMDB_API_KEY, mid)
            except Exception as e:
                print(f"[WARN] credits lookup failed for {mid}: {e}")
                filtered.append(m)
                continue

            if cast_ids.isdisjoint(exclude_set):
                filtered.append(m)

        movies = filtered

    movies = rank_movies(movies)

    return templates.TemplateResponse(
        "results.html",
        {"request": request, "movies": movies, "results_note": results_note},
    )