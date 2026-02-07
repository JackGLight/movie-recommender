from sqlalchemy import Column, Integer, String
from app.db import Base

class WatchedMovie(Base):
    __tablename__ = "watched_movies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    tmdb_id = Column(Integer, index=True)
    title = Column(String)