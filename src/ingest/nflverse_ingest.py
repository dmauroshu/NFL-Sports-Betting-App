"""
Milestone 1 ingestion: pulls schedules + team info from nflverse and loads them into
`teams` and `games`. Play-by-play is pulled here too and cached to parquet under
data/raw/ (it's large and slow to re-download) but is NOT loaded into the DB directly —
src/features/build_features.py reads the cached parquet and aggregates it into
`team_game_features`, which IS what lives in the DB. Keeping raw PBP out of the
relational DB is deliberate: it's ~370 columns of play-level data, cheap to re-derive
from parquet, and expensive to keep re-normalizing into SQL tables.

Usage:
    python -m src.ingest.nflverse_ingest --start-season 2015 --end-season 2024
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path

import nflreadpy as nfl
import polars as pl

from db.models import Game, Team
from db.session import get_session, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")


def _team_conference_division() -> pl.DataFrame:
    """
    nflreadpy's team-info loader gives current conference/division. Historical
    realignments (e.g., a team switching divisions) aren't modeled here in Milestone 1 —
    flagged as a known simplification, not silently ignored.
    """
    teams = nfl.load_teams()
    return teams.select(
        [
            pl.col("team_abbr").alias("team_id"),
            pl.col("team_name").alias("name"),
            pl.col("team_conf").alias("conference"),
            pl.col("team_division").alias("division"),
        ]
    ).unique(subset=["team_id"])


def load_teams(session) -> None:
    teams_df = _team_conference_division()
    existing_ids = {t.team_id for t in session.query(Team.team_id).all()}
    n_new = 0
    for row in teams_df.iter_rows(named=True):
        if row["team_id"] in existing_ids:
            continue
        session.add(
            Team(
                team_id=row["team_id"],
                name=row["name"],
                conference=row["conference"],
                division=row["division"],
            )
        )
        n_new += 1
    session.commit()
    log.info("Teams: %d new, %d already present", n_new, len(existing_ids))


def load_games(session, start_season: int, end_season: int) -> None:
    seasons = list(range(start_season, end_season + 1))
    sched = nfl.load_schedules(seasons=seasons)

    existing_ids = {g.game_id for g in session.query(Game.game_id).all()}
    n_new = 0
    for row in sched.iter_rows(named=True):
        if row["game_id"] in existing_ids:
            continue

        kickoff_utc = None
        if row.get("gameday") and row.get("gametime"):
            try:
                kickoff_utc = dt.datetime.fromisoformat(f"{row['gameday']}T{row['gametime']}")
            except ValueError:
                log.warning("Could not parse kickoff for game_id=%s", row["game_id"])

        is_final = row.get("home_score") is not None and row.get("away_score") is not None

        session.add(
            Game(
                game_id=row["game_id"],
                season=row["season"],
                week=row["week"],
                game_type=row.get("game_type"),
                home_team_id=row.get("home_team"),
                away_team_id=row.get("away_team"),
                kickoff_utc=kickoff_utc,
                home_score=row.get("home_score"),
                away_score=row.get("away_score"),
                status="final" if is_final else "scheduled",
            )
        )
        n_new += 1
    session.commit()
    log.info("Games: %d new, %d already present", n_new, len(existing_ids))


def cache_pbp_parquet(start_season: int, end_season: int) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for season in range(start_season, end_season + 1):
        out_path = RAW_DIR / f"pbp_{season}.parquet"
        if out_path.exists():
            log.info("PBP %d already cached at %s, skipping download", season, out_path)
            continue
        log.info("Downloading play-by-play for %d ...", season)
        pbp = nfl.load_pbp(seasons=[season])
        pbp.write_parquet(out_path)
        log.info("Cached %d rows to %s", pbp.shape[0], out_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=2015)
    parser.add_argument("--end-season", type=int, default=dt.date.today().year)
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        load_teams(session)
        load_games(session, args.start_season, args.end_season)
    finally:
        session.close()

    cache_pbp_parquet(args.start_season, args.end_season)
    log.info("Ingestion complete for seasons %d-%d", args.start_season, args.end_season)


if __name__ == "__main__":
    main()
