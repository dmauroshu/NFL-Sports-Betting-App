-- Reference schema from the project blueprint (§6).
-- This file is documentation of the FULL target schema, Postgres-flavored.
-- The tables actually created by Milestone 1 live in db/models.py (SQLAlchemy,
-- so they work identically on SQLite for local dev and Postgres/Neon in production).
-- Tables marked [MILESTONE 1] exist now. Tables marked [LATER] are not yet implemented
-- — don't create them ahead of the phase that needs them; an empty table you forget
-- about is worse than no table.

-- [MILESTONE 1] ---------------------------------------------------------
CREATE TABLE teams (
    team_id VARCHAR PRIMARY KEY,       -- nflverse team abbreviation, e.g. 'PHI'
    name VARCHAR NOT NULL,
    conference VARCHAR,
    division VARCHAR
);

CREATE TABLE stadiums (
    stadium_id VARCHAR PRIMARY KEY,
    team_id VARCHAR REFERENCES teams(team_id),
    name VARCHAR,
    surface VARCHAR,
    roof_type VARCHAR,
    latitude FLOAT,
    longitude FLOAT,
    altitude_ft FLOAT
);

CREATE TABLE players (
    player_id VARCHAR PRIMARY KEY,     -- gsis_id
    name VARCHAR,
    position VARCHAR,
    team_id VARCHAR REFERENCES teams(team_id)
);

CREATE TABLE games (
    game_id VARCHAR PRIMARY KEY,       -- nflverse game_id
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    game_type VARCHAR,
    home_team_id VARCHAR REFERENCES teams(team_id),
    away_team_id VARCHAR REFERENCES teams(team_id),
    kickoff_utc TIMESTAMP,
    home_score INTEGER,
    away_score INTEGER,
    status VARCHAR                     -- 'scheduled' | 'final'
);

CREATE TABLE team_game_features (
    feature_id INTEGER PRIMARY KEY,
    game_id VARCHAR REFERENCES games(game_id),
    team_id VARCHAR REFERENCES teams(team_id),
    is_home BOOLEAN,
    -- rolling, as-of-kickoff, shrinkage-adjusted features (see build_features.py)
    off_epa_play FLOAT,
    def_epa_play_allowed FLOAT,
    off_success_rate FLOAT,
    def_success_rate_allowed FLOAT,
    third_down_rate_shrunk FLOAT,
    games_of_history INTEGER,          -- how many prior games this was computed from
    as_of_utc TIMESTAMP                -- when this feature row was computed (leakage audit trail)
);

CREATE TABLE model_versions (
    model_id VARCHAR PRIMARY KEY,
    market_type VARCHAR,               -- 'spread' | 'moneyline' | 'total' (same model drives all three)
    name VARCHAR,
    trained_through_season INTEGER,
    trained_through_week INTEGER,
    git_commit VARCHAR,
    file_path VARCHAR,
    created_at_utc TIMESTAMP
);

CREATE TABLE predictions (
    prediction_id INTEGER PRIMARY KEY,
    model_id VARCHAR REFERENCES model_versions(model_id),
    game_id VARCHAR REFERENCES games(game_id),
    predicted_margin FLOAT,             -- home minus away, positive = home favored
    predicted_home_win_prob FLOAT,
    generated_at_utc TIMESTAMP
);

-- [LATER — Milestone 2+] --------------------------------------------------
-- odds_snapshots(...)        -- pregame odds, append-only, added once odds ingestion starts
-- injury_reports(...)        -- Phase 5
-- weather_observations(...)  -- Phase 5
-- recommendations(...)       -- Phase 4 (needs odds_snapshots + predictions)
-- bets(...)                  -- Phase 4/5
-- bankroll_ledger(...)       -- Phase 5
