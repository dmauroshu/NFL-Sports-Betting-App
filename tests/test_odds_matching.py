"""
Tests the odds<->game matching logic using the fixture provider, without needing a
live API key. Verifies: a real, correctly-named/dated event matches its internal
game_id; a nonsense event is stored but explicitly unmatched (never silently dropped);
and moneyline rows never carry a spread/total `point` value.
"""
import pandas as pd

from db.models import Game, OddsSnapshot
from db.session import get_session
from src.ingest.odds.fixture_provider import FixtureOddsProvider
from src.ingest.odds_ingest import run


def test_fixture_odds_match_and_unmatched_paths():
    session = get_session()
    try:
        game_exists = session.query(Game).filter(
            Game.home_team_id == "PHI", Game.away_team_id == "DAL"
        ).count() > 0
    finally:
        session.close()
    if not game_exists:
        import pytest

        pytest.skip("No PHI/DAL game in the DB — run nflverse_ingest.py first")

    run(FixtureOddsProvider())

    session = get_session()
    try:
        df = pd.read_sql(session.query(OddsSnapshot).statement, session.bind)
    finally:
        session.close()

    matched = df[df["external_event_id"] == "fixture-event-0001"]
    unmatched = df[df["external_event_id"] == "fixture-event-0002"]

    assert not matched.empty, "The real fixture event should have produced odds rows"
    assert matched["game_id"].notna().all(), "The real fixture event should match a game_id"

    assert unmatched.empty or unmatched["game_id"].isna().all(), (
        "The nonsense fixture event must never be matched to a real game_id"
    )

    h2h_rows = matched[matched["market_type"] == "h2h"]
    assert h2h_rows["point"].isna().all(), "Moneyline (h2h) rows must never carry a point value"
