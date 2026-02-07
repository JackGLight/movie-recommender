from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.movies.tmdb import get_movie_details, get_movie_credits

from app.config import TMDB_API_KEY, DTDD_API_KEY
from app.db import engine, SessionLocal
from app.models import Base, WatchedMovie

from app.movies.dtdd import is_animal_safe_v1
from app.movies.genres import fetch_genres
from app.movies.ranking import rank_movies
from app.movies.tmdb import (
    discover_movies,
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
    return templates.TemplateResponse("search.html", {"request": request, "genres": genres})

@app.get("/watched")
def watched(request: Request):
    db = SessionLocal()
    try:
        rows = db.query(WatchedMovie).filter(WatchedMovie.user_id == 1).all()
    finally:
        db.close()

    return templates.TemplateResponse("watched.html", {"request": request, "rows": rows})

@app.get("/movie/{tmdb_id}")
def movie_detail(request: Request, tmdb_id: int):
    # Fetch full movie details
    movie = get_movie_details(TMDB_API_KEY, tmdb_id)

    # Credits (cast)
    credits = {}
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
        imdb = get_imdb_id(TMDB_API_KEY, tmdb_id)  # you already have this helper
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
    watched = db.query(WatchedMovie).filter_by(user_id=1, tmdb_id=tmdb_id).first()
    db.close()
    movie["is_watched"] = watched is not None

    # Limit cast list size for display
    cast = cast[:12]

    return templates.TemplateResponse(
        "movie.html",
        {"request": request, "movie": movie, "cast": cast},
    )


@app.post("/watched")
def mark_watched(
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
    return RedirectResponse(url="/watched", status_code=303)

@app.post("/watched/remove")
def remove_watched(tmdb_id: int = Form(...)):
    db = SessionLocal()
    try:
        db.query(WatchedMovie).filter(
            WatchedMovie.user_id == 1,
            WatchedMovie.tmdb_id == tmdb_id
        ).delete()
        db.commit()
    finally:
        db.close()

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
    # checkbox sends "on" when checked, None when not
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

    data = discover_movies(
        TMDB_API_KEY,
        year_from=year_from,
        year_to=year_to,
        min_vote=min_vote,
        genres_csv=genres_csv,
        with_cast_csv=with_cast_csv,
        page=1,
    )

    movies = data.get("results", [])
    # --- Filter out watched movies (MVP: single user_id=1) ---
    db = SessionLocal()
    try:
        watched_ids = {
            w.tmdb_id
            for w in db.query(WatchedMovie).filter(WatchedMovie.user_id == 1).all()
        }
    finally:
        db.close()

    movies = [m for m in movies if m.get("id") not in watched_ids]

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
            continue  # filter out unsafe

        checked.append(m)

    # mark unchecked ones as unknown so template is predictable
    for m in movies[MAX_DTDD_CHECK:]:
        m.setdefault("dtdd_dog_safe", "unknown")

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

    # --- Rank results ---
    movies = rank_movies(movies)

    return templates.TemplateResponse("results.html", {"request": request, "movies": movies})