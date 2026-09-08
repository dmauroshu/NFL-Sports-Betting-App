"""
Milestone 1 feature pipeline: builds `team_game_features` from cached play-by-play
parquet files (see src/ingest/nflverse_ingest.py).

LEAKAGE SAFETY — read this before adding any feature:
For every game G, a team's features are computed ONLY from plays belonging to that
team's games which occur strictly earlier in the season than G (by week, then by
kickoff time within a week). The running per-team accumulators are updated with a
game's plays only AFTER that game's pregame feature row has already been written.
This mirrors the blueprint's §8 `as_of_timestamp` pattern using chronological order
instead of wall-clock time, since nflverse data doesn't carry a "when did we learn
this" timestamp separate from the game itself. If you add a feature that draws on
data outside this file's PBP source (e.g., injuries, snap counts), you MUST apply
the same "only strictly-earlier games" rule or you will silently leak the future
into the training set.

Third-down rate uses empirical-Bayes shrinkage toward the season-to-date league
average (computed the same leakage-safe way) rather than each team's raw small-sample
rate, per the blueprint's instruction to regress unstable per-team rates toward a prior.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pandas as pd
import polars as pl

from db.models import Game, TeamGameFeature
from db.session import get_session, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
THIRD_DOWN_SHRINKAGE_PSEUDO_ATTEMPTS = 10  # weight given to the league-average prior


_PBP_COLUMNS = [
    "game_id",
    "season",
    "week",
    "posteam",
    "defteam",
    "epa",
    "success",
    "down",
    "play_type",
]


def _load_pbp(seasons: list[int]) -> pl.DataFrame:
    """
    Reads only the columns this pipeline actually uses. The raw PBP parquet has ~370
    columns per season; loading all of them for 10 seasons at once is what caused an
    OOM kill in this environment's 4GB container. Selecting columns at read time
    (rather than after concatenation) keeps memory to a small fraction of that.
    """
    frames = []
    for season in seasons:
        path = RAW_DIR / f"pbp_{season}.parquet"
        if not path.exists():
            log.warning("No cached PBP for %d at %s — run nflverse_ingest.py first", season, path)
            continue
        frames.append(pl.read_parquet(path, columns=_PBP_COLUMNS))
    if not frames:
        raise FileNotFoundError("No cached play-by-play parquet files found in data/raw/")
    return pl.concat(frames, how="vertical_relaxed")


def _per_team_per_game_stats(pbp: pl.DataFrame) -> pd.DataFrame:
    """
    Collapse play-level data to one row per (game_id, team) with that team's OFFENSIVE
    output (epa/play, success rate, 3rd-down conversions) and, separately, what they
    ALLOWED on defense. Filters to standard scrimmage plays only (excludes penalties,
    kneels, spikes, and plays with a null EPA).
    """
    plays = pbp.filter(
        pl.col("play_type").is_in(["pass", "run"])
        & pl.col("epa").is_not_null()
        & pl.col("success").is_not_null()
    )

    offense = (
        plays.group_by(["game_id", "season", "week", "posteam"])
        .agg(
            [
                pl.len().alias("off_plays"),
                pl.col("epa").sum().alias("off_epa_sum"),
                pl.col("success").sum().alias("off_success_sum"),
                (pl.col("down") == 3).sum().alias("third_down_attempts"),
                ((pl.col("down") == 3) & (pl.col("success") == 1)).sum().alias("third_down_conversions"),
            ]
        )
        .rename({"posteam": "team_id"})
    )

    defense = (
        plays.group_by(["game_id", "defteam"])
        .agg(
            [
                pl.len().alias("def_plays_faced"),
                pl.col("epa").sum().alias("def_epa_allowed_sum"),
                pl.col("success").sum().alias("def_success_allowed_sum"),
            ]
        )
        .rename({"defteam": "team_id"})
    )

    merged = offense.join(defense, on=["game_id", "team_id"], how="left")
    return merged.to_pandas()


def _build_features_for_season(season_games: pd.DataFrame, team_game_stats: pd.DataFrame) -> list[dict]:
    """
    Walks a single season's games in chronological order, maintaining running
    per-team accumulators. Returns a list of feature dicts (two per game: home + away),
    each computed from ONLY the accumulator state as it existed before that game.
    """
    stats_by_game_team = team_game_stats.set_index(["game_id", "team_id"])

    # Running accumulators, reset at the start of each season (within-season only —
    # a documented Milestone 1 simplification; carrying a shrunk prior across
    # seasons is a natural follow-up, not implemented here).
    team_acc: dict[str, dict[str, float]] = {}
    league_acc = {"plays": 0, "third_down_attempts": 0, "third_down_conversions": 0}

    def get_acc(team_id: str) -> dict[str, float]:
        return team_acc.setdefault(
            team_id,
            {
                "games": 0,
                "off_plays": 0,
                "off_epa_sum": 0.0,
                "off_success_sum": 0.0,
                "def_plays_faced": 0,
                "def_epa_allowed_sum": 0.0,
                "def_success_allowed_sum": 0.0,
                "third_down_attempts": 0,
                "third_down_conversions": 0,
            },
        )

    rows: list[dict] = []
    ordered = season_games.sort_values(["week", "kickoff_utc"], na_position="last")

    for game in ordered.itertuples():
        league_rate = (
            league_acc["third_down_conversions"] / league_acc["third_down_attempts"]
            if league_acc["third_down_attempts"] > 0
            else 0.40  # only used before ANY third down has been observed this season
        )

        for team_id, is_home in [(game.home_team_id, True), (game.away_team_id, False)]:
            if team_id is None:
                continue
            acc = get_acc(team_id)

            off_epa_play = acc["off_epa_sum"] / acc["off_plays"] if acc["off_plays"] > 0 else None
            off_success_rate = acc["off_success_sum"] / acc["off_plays"] if acc["off_plays"] > 0 else None
            def_epa_play_allowed = (
                acc["def_epa_allowed_sum"] / acc["def_plays_faced"] if acc["def_plays_faced"] > 0 else None
            )
            def_success_rate_allowed = (
                acc["def_success_allowed_sum"] / acc["def_plays_faced"] if acc["def_plays_faced"] > 0 else None
            )
            third_down_rate_shrunk = (
                acc["third_down_conversions"] + THIRD_DOWN_SHRINKAGE_PSEUDO_ATTEMPTS * league_rate
            ) / (acc["third_down_attempts"] + THIRD_DOWN_SHRINKAGE_PSEUDO_ATTEMPTS)

            rows.append(
                {
                    "game_id": game.game_id,
                    "team_id": team_id,
                    "is_home": is_home,
                    "off_epa_play": off_epa_play,
                    "def_epa_play_allowed": def_epa_play_allowed,
                    "off_success_rate": off_success_rate,
                    "def_success_rate_allowed": def_success_rate_allowed,
                    "third_down_rate_shrunk": third_down_rate_shrunk,
                    "games_of_history": acc["games"],
                    "as_of_utc": game.kickoff_utc,
                }
            )

        # Only NOW fold this game's actual plays into the accumulators, so the rows
        # just written above never saw this game's own outcome.
        for team_id in [game.home_team_id, game.away_team_id]:
            if team_id is None or (game.game_id, team_id) not in stats_by_game_team.index:
                continue
            s = stats_by_game_team.loc[(game.game_id, team_id)]
            acc = get_acc(team_id)
            acc["games"] += 1
            acc["off_plays"] += s.get("off_plays", 0) or 0
            acc["off_epa_sum"] += s.get("off_epa_sum", 0) or 0
            acc["off_success_sum"] += s.get("off_success_sum", 0) or 0
            acc["def_plays_faced"] += s.get("def_plays_faced", 0) or 0
            acc["def_epa_allowed_sum"] += s.get("def_epa_allowed_sum", 0) or 0
            acc["def_success_allowed_sum"] += s.get("def_success_allowed_sum", 0) or 0
            acc["third_down_attempts"] += s.get("third_down_attempts", 0) or 0
            acc["third_down_conversions"] += s.get("third_down_conversions", 0) or 0

            league_acc["third_down_attempts"] += s.get("third_down_attempts", 0) or 0
            league_acc["third_down_conversions"] += s.get("third_down_conversions", 0) or 0

    return rows


def main() -> None:
    init_db()
    session = get_session()
    try:
        games_df = pd.read_sql(session.query(Game).statement, session.bind)
    finally:
        session.close()

    seasons = sorted(games_df["season"].unique().tolist())
    pbp = _load_pbp(seasons)
    team_game_stats = _per_team_per_game_stats(pbp)

    all_rows: list[dict] = []
    for season in seasons:
        season_games = games_df[games_df["season"] == season]
        all_rows.extend(_build_features_for_season(season_games, team_game_stats))

    log.info("Built %d feature rows across %d seasons", len(all_rows), len(seasons))

    session = get_session()
    try:
        # Idempotent: clear and rebuild rather than append-and-dedupe, since this is
        # a deterministic transform of games+pbp, not an append-only observation log.
        session.query(TeamGameFeature).delete()
        session.bulk_insert_mappings(TeamGameFeature, all_rows)
        session.commit()
    finally:
        session.close()

    log.info("team_game_features table rebuilt.")


if __name__ == "__main__":
    main()
