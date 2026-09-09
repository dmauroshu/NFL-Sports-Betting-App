"""
Milestone 2: pulls pregame odds from an OddsProvider, matches each vendor event to an
internal `game_id` (vendor APIs use their own event IDs and full team names, not ours),
and inserts append-only rows into `odds_snapshots`.

Matching strategy: exact match on (home team full name, away team full name) against
`teams.name`, then pick the internal game whose kickoff is closest to the vendor's
`commence_time`, within a tolerance window (handles minor kickoff-time discrepancies
between sources without silently matching the wrong week's game). An event that
doesn't match anything is still stored, with `game_id=None` and a warning logged —
per the blueprint's instruction to make data-quality problems visible, not hidden.

Usage:
    python -m src.ingest.odds_ingest --use-fixture        # no API key needed, for testing
    python -m src.ingest.odds_ingest                       # real pull, needs THE_ODDS_API_KEY
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging

import pandas as pd

from db.models import Game, OddsSnapshot, Team
from db.session import get_session, init_db
from src.ingest.odds.fixture_provider import FixtureOddsProvider
from src.ingest.odds.provider_base import OddsProvider, RawGameOdds
from src.ingest.odds.the_odds_api_provider import TheOddsApiProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MATCH_TOLERANCE = dt.timedelta(hours=36)  # generous enough for TZ/rounding mismatches,
# tight enough that a whole week of separation can never match the wrong game


def _parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)


def _match_game(raw: RawGameOdds, games_df: pd.DataFrame, name_to_id: dict[str, str]) -> str | None:
    home_id = name_to_id.get(raw.home_team)
    away_id = name_to_id.get(raw.away_team)
    if home_id is None or away_id is None:
        log.warning(
            "Could not map team names to internal IDs: home='%s' away='%s' (event %s)",
            raw.home_team,
            raw.away_team,
            raw.external_event_id,
        )
        return None

    candidates = games_df[
        (games_df["home_team_id"] == home_id) & (games_df["away_team_id"] == away_id)
    ]
    if candidates.empty:
        log.warning(
            "No internal game found for %s @ %s (event %s)",
            raw.away_team,
            raw.home_team,
            raw.external_event_id,
        )
        return None

    vendor_time = _parse_iso(raw.commence_time)
    candidates = candidates.copy()
    candidates["time_diff"] = (candidates["kickoff_utc"] - vendor_time).abs()
    best = candidates.sort_values("time_diff").iloc[0]

    if best["time_diff"] > MATCH_TOLERANCE:
        log.warning(
            "Closest internal game for event %s is %s away (beyond %s tolerance) — treating as unmatched",
            raw.external_event_id,
            best["time_diff"],
            MATCH_TOLERANCE,
        )
        return None

    return best["game_id"]


def _snapshot_rows(raw: RawGameOdds, game_id: str | None, pulled_at: dt.datetime) -> list[dict]:
    rows = []
    commence = _parse_iso(raw.commence_time)
    for bm in raw.bookmakers:
        for mkt in bm.markets:
            for outcome in mkt.outcomes:
                rows.append(
                    {
                        "game_id": game_id,
                        "external_event_id": raw.external_event_id,
                        "sportsbook_key": bm.key,
                        "sportsbook_title": bm.title,
                        "market_type": mkt.market_type,
                        "selection_name": outcome.name,
                        "point": outcome.point,
                        "price_american": outcome.price_american,
                        "commence_time_utc": commence,
                        "bookmaker_last_update_utc": _parse_iso(mkt.last_update),
                        "pulled_at_utc": pulled_at,
                    }
                )
    return rows


def run(provider: OddsProvider) -> None:
    init_db()
    session = get_session()
    try:
        games_df = pd.read_sql(session.query(Game).statement, session.bind)
        teams = session.query(Team).all()
        name_to_id = {t.name: t.team_id for t in teams}
    finally:
        session.close()

    games_df["kickoff_utc"] = pd.to_datetime(games_df["kickoff_utc"])

    raw_games = provider.fetch_pregame_odds()
    pulled_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    all_rows: list[dict] = []
    matched, unmatched = 0, 0
    for raw in raw_games:
        game_id = _match_game(raw, games_df, name_to_id)
        matched += game_id is not None
        unmatched += game_id is None
        all_rows.extend(_snapshot_rows(raw, game_id, pulled_at))

    log.info(
        "Fetched %d events (%d matched to internal games, %d unmatched), %d odds rows total",
        len(raw_games),
        matched,
        unmatched,
        len(all_rows),
    )

    if not all_rows:
        log.info("No odds rows to insert.")
        return

    session = get_session()
    try:
        session.bulk_insert_mappings(OddsSnapshot, all_rows)
        session.commit()
    finally:
        session.close()
    log.info("Inserted %d odds_snapshots rows (pulled_at=%s)", len(all_rows), pulled_at.isoformat())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--use-fixture",
        action="store_true",
        help="Use synthetic fixture data instead of hitting the live API (no API key needed).",
    )
    args = parser.parse_args()

    provider: OddsProvider = FixtureOddsProvider() if args.use_fixture else TheOddsApiProvider()
    run(provider)


if __name__ == "__main__":
    main()
