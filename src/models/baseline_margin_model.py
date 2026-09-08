"""
Milestone 1 baseline model: predicts home-minus-away scoring margin from the
leakage-safe features in `team_game_features`, walk-forward validated (train on
strictly earlier seasons, test on the next season — never a random split).

This model is intentionally simple (Ridge regression on a handful of EPA/success-rate
features). The point of Milestone 1 is proving the leakage-safe pipeline and the
walk-forward evaluation harness work correctly — not squeezing out maximum accuracy.
XGBoost/simulation-based approaches come once this harness is trusted (blueprint §7).

Baseline comparison: a "home field only" model that always predicts a fixed home-margin
constant learned from the training data (i.e., knows nothing about either team). Beating
this is a very low bar and mainly proves the pipeline works; beating the closing line's
no-vig probability (once odds data exists) is the bar that actually matters.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error, mean_squared_error

from db.models import Game, TeamGameFeature
from db.session import get_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FEATURE_COLS = [
    "off_epa_play",
    "def_epa_play_allowed",
    "off_success_rate",
    "def_success_rate_allowed",
    "third_down_rate_shrunk",
]
MIN_GAMES_OF_HISTORY = 2  # drop games where either team has fewer prior games than this


def _load_matchup_table() -> pd.DataFrame:
    session = get_session()
    try:
        games = pd.read_sql(session.query(Game).statement, session.bind)
        feats = pd.read_sql(session.query(TeamGameFeature).statement, session.bind)
    finally:
        session.close()

    games = games[games["status"] == "final"].copy()
    games["margin"] = games["home_score"] - games["away_score"]

    home_feats = feats[feats["is_home"] == True].add_prefix("home_")  # noqa: E712
    away_feats = feats[feats["is_home"] == False].add_prefix("away_")  # noqa: E712

    df = games.merge(home_feats, left_on="game_id", right_on="home_game_id")
    df = df.merge(away_feats, left_on="game_id", right_on="away_game_id")

    keep = (df["home_games_of_history"] >= MIN_GAMES_OF_HISTORY) & (
        df["away_games_of_history"] >= MIN_GAMES_OF_HISTORY
    )
    dropped = (~keep).sum()
    log.info(
        "Dropped %d/%d games with insufficient history (< %d games) for at least one team",
        dropped,
        len(df),
        MIN_GAMES_OF_HISTORY,
    )
    return df[keep].copy()


def _build_design_matrix(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for col in FEATURE_COLS:
        X[f"diff_{col}"] = df[f"home_{col}"] - df[f"away_{col}"]
    return X


def _margin_to_home_win_prob(predicted_margin: np.ndarray, residual_std: float) -> np.ndarray:
    """
    Converts a predicted point margin into P(home wins) assuming the margin's residual
    distribution is approximately Normal — a standard, defensible simplification for
    NFL score margins (not exact, since scores are discrete and pushes exist at certain
    margins, but adequate for a Milestone 1 baseline; revisit with a t-distribution or
    empirical residual distribution before this drives real recommendations).
    """
    from scipy.stats import norm

    return 1 - norm.cdf(0, loc=predicted_margin, scale=residual_std)


def walk_forward_eval(df: pd.DataFrame) -> None:
    seasons = sorted(df["season"].unique().tolist())
    if len(seasons) < 2:
        log.warning(
            "Only %d season(s) available (%s) — walk-forward needs at least 2. "
            "Re-run ingestion with a wider --start-season/--end-season range for a "
            "real evaluation. Proceeding with a single train/test split anyway "
            "so the harness itself is validated.",
            len(seasons),
            seasons,
        )

    results = []
    for i in range(1, len(seasons)):
        train_seasons = seasons[:i]
        test_season = seasons[i]

        train_df = df[df["season"].isin(train_seasons)]
        test_df = df[df["season"] == test_season]
        if len(train_df) < 20 or len(test_df) < 5:
            continue

        X_train, y_train = _build_design_matrix(train_df), train_df["margin"]
        X_test, y_test = _build_design_matrix(test_df), test_df["margin"]

        model = Ridge(alpha=1.0)
        model.fit(X_train, y_train)
        pred_margin = model.predict(X_test)

        train_pred = model.predict(X_train)
        residual_std = float(np.std(y_train - train_pred))

        # Naive baseline: predict the constant mean home margin observed in training.
        naive_pred = np.full_like(pred_margin, y_train.mean())

        home_win_actual = (y_test > 0).astype(int)
        home_win_prob = _margin_to_home_win_prob(pred_margin, residual_std)

        results.append(
            {
                "test_season": test_season,
                "n_train_games": len(train_df),
                "n_test_games": len(test_df),
                "model_mae": mean_absolute_error(y_test, pred_margin),
                "naive_mae": mean_absolute_error(y_test, naive_pred),
                "model_rmse": mean_squared_error(y_test, pred_margin) ** 0.5,
                "naive_rmse": mean_squared_error(y_test, naive_pred) ** 0.5,
                "log_loss": log_loss(home_win_actual, home_win_prob, labels=[0, 1]),
                "brier_score": brier_score_loss(home_win_actual, home_win_prob),
            }
        )

    if not results:
        log.error("No walk-forward folds could be evaluated — need more seasons of data.")
        return

    results_df = pd.DataFrame(results)
    pd.set_option("display.width", 120)
    log.info("Walk-forward results:\n%s", results_df.to_string(index=False))

    improvement = (results_df["naive_mae"] - results_df["model_mae"]).mean()
    log.info(
        "Model beats the naive constant-margin baseline by %.3f points of MAE on average "
        "(positive = model is better). This is a low bar — the real test is closing-line "
        "comparison once odds data exists.",
        improvement,
    )


def main() -> None:
    df = _load_matchup_table()
    walk_forward_eval(df)


if __name__ == "__main__":
    main()
