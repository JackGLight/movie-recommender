import os
from dotenv import load_dotenv

load_dotenv()

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
if not TMDB_API_KEY:
    raise RuntimeError("TMDB_API_KEY is missing. Add it to your .env file.")

DTDD_API_KEY = os.getenv("DTDD_API_KEY", "")