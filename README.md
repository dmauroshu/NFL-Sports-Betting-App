# NFL Betting Analytics — Milestone 1

Milestone 1 scope (per the project blueprint): database schema, nflverse ingestion,
a leakage-safe feature pipeline, and a baseline walk-forward margin model.
**No odds data yet** — that's the next milestone.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL if using Postgres/Neon; defaults to local SQLite
```

## Run

```bash
# 1. Pull nflverse data and load the database (defaults to seasons 2015-2024)
python -m src.ingest.nflverse_ingest --start-season 2015 --end-season 2024

# 2. Build the leakage-safe feature table
python -m src.features.build_features

# 3. Train + walk-forward validate the baseline margin model
python -m src.models.baseline_margin_model
```

## Why SQLite by default

The blueprint recommends Neon Postgres for the real deployment, but Milestone 1 doesn't
need a network database to prove the pipeline out. `DATABASE_URL` in `.env` controls this —
point it at your Neon connection string whenever you're ready; every script here uses
SQLAlchemy so no code changes are needed to switch.

## Leakage safety

Every function in `src/features/build_features.py` that computes a team's "form" going into
a game only uses plays from games that were **already final** before that game's kickoff
(`as_of` filtering on `gameday`). This is the control described in the blueprint's §8 — do
not bypass it when adding features later (e.g., don't compute a season's full-season average
and use it to predict week 3 of that same season).

## Results from this build (2015-2024, real nflverse data)

Ran end-to-end against actual data before handing this off — not a hypothetical:

- 2,743 games ingested, 10 seasons of play-by-play cached (~480K plays)
- 5,486 leakage-safe feature rows built (2 per game); 430 early-season games dropped
  for insufficient history (documented, expected)
- Walk-forward evaluated across 9 test seasons (2016-2024): the Ridge margin model
  **beat the naive constant-margin baseline in every single test season**, by an
  average of 0.666 points of MAE
- Brier scores landed around 0.22 (0.25 = coin flip, lower is better) and log loss
  around 0.63-0.66 (ln(2) ≈ 0.693 = uninformed baseline) — modest but real,
  out-of-sample skill from five basic features
- `tests/test_leakage_safety.py` passes: first-game-of-season history is verified
  zero, `games_of_history` is verified monotonic, shrinkage output is verified bounded

This is a low bar on purpose (see the model script's docstring) — the real test is
closing-line comparison once odds data exists. But it proves the walk-forward harness
and the leakage-safe pipeline are both working correctly on real data, which is what
Milestone 1 needed to prove before anything else gets built on top of it.

## What's intentionally NOT here yet

- Odds ingestion (Milestone 2)
- Injuries/weather features (Phase 5 per the roadmap)
- Player props (Phase 6)
- The Streamlit dashboard (Phase 3, needs odds first to be meaningful)
