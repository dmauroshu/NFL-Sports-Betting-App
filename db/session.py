"""
Engine/session creation. Reads DATABASE_URL from the environment (.env), defaulting
to a local SQLite file so Milestone 1 needs no external service. Switching to Neon
Postgres later is a one-line .env change — nothing in the ingestion, feature, or
model code depends on which database is behind DATABASE_URL.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base

load_dotenv()

DEFAULT_SQLITE_PATH = Path("data/processed/nfl_betting.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")

# SQLite needs its parent directory to exist and a special connect arg for
# multi-threaded access; Postgres needs neither.
if DATABASE_URL.startswith("sqlite"):
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create all Milestone 1 tables if they don't already exist. Never drops data."""
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
