"""
Enforces the core invariant of the feature pipeline: a team's features in its FIRST
game of a season must reflect zero history (no plays have happened yet to leak from),
and `games_of_history` must increase monotonically as more games are played by the
same team within a season. If either of these breaks, a future code change has
introduced a leak.

Run with: pytest tests/test_leakage_safety.py
Requires the DB to already be populated (run ingestion + build_features first).
"""
import pandas as pd
import pytest

from db.models import Game, TeamGameFeature
from db.session import get_session


@pytest.fixture(scope="module")
def merged_features():
    session = get_session()
    try:
        feats = pd.read_sql(session.query(TeamGameFeature).statement, session.bind)
        games = pd.read_sql(session.query(Game).statement, session.bind)
    finally:
        session.close()
    if feats.empty:
        pytest.skip("team_game_features is empty — run the ingestion + feature pipeline first")
    return feats.merge(games[["game_id", "season", "week"]], on="game_id")


def test_first_game_of_season_has_zero_history(merged_features):
    df = merged_features
    first_games = df.loc[df.groupby(["team_id", "season"])["week"].idxmin()]
    assert (first_games["games_of_history"] == 0).all(), (
        "A team's first game of a season must have games_of_history == 0 — nonzero "
        "means a game leaked into the accumulator before this game's feature row "
        "was computed."
    )
    assert first_games["off_epa_play"].isna().all(), (
        "off_epa_play should be null before any history exists — a non-null value "
        "here means the feature was computed from data that shouldn't be available yet."
    )


def test_games_of_history_is_monotonic_within_season(merged_features):
    df = merged_features.sort_values(["team_id", "season", "week"])
    for (_team, _season), grp in df.groupby(["team_id", "season"]):
        diffs = grp["games_of_history"].diff().dropna()
        assert (diffs >= 0).all(), "games_of_history must never decrease within a season"


def test_third_down_rate_is_bounded(merged_features):
    df = merged_features
    assert df["third_down_rate_shrunk"].between(0, 1).all(), (
        "Shrunk third-down rate must stay in [0, 1] regardless of shrinkage weight"
    )
