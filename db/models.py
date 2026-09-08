"""
SQLAlchemy ORM models for Milestone 1.

These mirror db/schema.sql's [MILESTONE 1] tables exactly. Using the ORM (instead of
raw SQL) means the same code creates identical tables on local SQLite (dev) and
Neon Postgres (production) with zero changes — see db/session.py for the engine
selection logic driven by DATABASE_URL.

Only tables needed for Milestone 1 (schema + ingestion + baseline model) are defined
here. Do not add odds/injury/weather/recommendation tables until the milestone that
actually populates them — see schema.sql's [LATER] section for why.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. 'PHI'
    name: Mapped[str] = mapped_column(String)
    conference: Mapped[str | None] = mapped_column(String, nullable=True)
    division: Mapped[str | None] = mapped_column(String, nullable=True)


class Stadium(Base):
    __tablename__ = "stadiums"

    stadium_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.team_id"), nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    surface: Mapped[str | None] = mapped_column(String, nullable=True)
    roof_type: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_ft: Mapped[float | None] = mapped_column(Float, nullable=True)


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)  # gsis_id
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.team_id"), nullable=True)


class Game(Base):
    __tablename__ = "games"

    game_id: Mapped[str] = mapped_column(String, primary_key=True)
    season: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    game_type: Mapped[str | None] = mapped_column(String, nullable=True)
    home_team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.team_id"), nullable=True)
    away_team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.team_id"), nullable=True)
    kickoff_utc: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="scheduled")


class TeamGameFeature(Base):
    """
    One row per (game, team). Every numeric feature here MUST be computable using only
    plays from games whose kickoff was strictly before this game's kickoff — see
    src/features/build_features.py's `as_of` filtering for how that's enforced.
    """

    __tablename__ = "team_game_features"

    feature_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.game_id"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.team_id"))
    is_home: Mapped[bool] = mapped_column(Boolean)

    off_epa_play: Mapped[float | None] = mapped_column(Float, nullable=True)
    def_epa_play_allowed: Mapped[float | None] = mapped_column(Float, nullable=True)
    off_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    def_success_rate_allowed: Mapped[float | None] = mapped_column(Float, nullable=True)
    third_down_rate_shrunk: Mapped[float | None] = mapped_column(Float, nullable=True)

    games_of_history: Mapped[int] = mapped_column(Integer, default=0)
    as_of_utc: Mapped[dt.datetime] = mapped_column(DateTime)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    model_id: Mapped[str] = mapped_column(String, primary_key=True)
    market_type: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    trained_through_season: Mapped[int] = mapped_column(Integer)
    trained_through_week: Mapped[int] = mapped_column(Integer)
    git_commit: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str] = mapped_column(String)
    created_at_utc: Mapped[dt.datetime] = mapped_column(DateTime)


class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_versions.model_id"))
    game_id: Mapped[str] = mapped_column(ForeignKey("games.game_id"))
    predicted_margin: Mapped[float] = mapped_column(Float)  # home - away
    predicted_home_win_prob: Mapped[float] = mapped_column(Float)
    generated_at_utc: Mapped[dt.datetime] = mapped_column(DateTime)
