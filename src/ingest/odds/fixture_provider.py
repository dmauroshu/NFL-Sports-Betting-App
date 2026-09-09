"""
A fake OddsProvider returning synthetic-but-schema-accurate data, so the ingestion
and team-matching logic can be built and tested without a live THE_ODDS_API_KEY or
network access. The field names and nesting exactly match The Odds API's real
response shape (see the_odds_api_provider.py's docstring for the verified source) —
only the numbers and IDs are made up.

Usage: `python -m src.ingest.odds_ingest --use-fixture`
"""
from __future__ import annotations

from .provider_base import OddsProvider, RawBookmaker, RawGameOdds, RawMarket, RawOutcome


class FixtureOddsProvider(OddsProvider):
    def fetch_pregame_odds(self, markets=None, regions=None) -> list[RawGameOdds]:
        return [
            RawGameOdds(
                external_event_id="fixture-event-0001",
                commence_time="2024-12-29T18:00:00Z",  # matches a real ingested game (kickoff stored as local/naive; see note below)
                home_team="Philadelphia Eagles",
                away_team="Dallas Cowboys",
                bookmakers=[
                    RawBookmaker(
                        key="draftkings",
                        title="DraftKings",
                        markets=[
                            RawMarket(
                                market_type="h2h",
                                last_update="2025-09-07T12:00:00Z",
                                outcomes=[
                                    RawOutcome(name="Philadelphia Eagles", price_american=-165, point=None),
                                    RawOutcome(name="Dallas Cowboys", price_american=140, point=None),
                                ],
                            ),
                            RawMarket(
                                market_type="spreads",
                                last_update="2025-09-07T12:00:00Z",
                                outcomes=[
                                    RawOutcome(name="Philadelphia Eagles", price_american=-110, point=-3.5),
                                    RawOutcome(name="Dallas Cowboys", price_american=-110, point=3.5),
                                ],
                            ),
                            RawMarket(
                                market_type="totals",
                                last_update="2025-09-07T12:00:00Z",
                                outcomes=[
                                    RawOutcome(name="Over", price_american=-108, point=47.5),
                                    RawOutcome(name="Under", price_american=-112, point=47.5),
                                ],
                            ),
                        ],
                    ),
                    RawBookmaker(
                        key="fanduel",
                        title="FanDuel",
                        markets=[
                            RawMarket(
                                market_type="h2h",
                                last_update="2025-09-07T12:05:00Z",
                                outcomes=[
                                    RawOutcome(name="Philadelphia Eagles", price_american=-158, point=None),
                                    RawOutcome(name="Dallas Cowboys", price_american=135, point=None),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            RawGameOdds(
                external_event_id="fixture-event-0002",
                commence_time="2099-01-01T00:00:00Z",  # deliberately unmatchable — tests the "unmatched" path
                home_team="Nonexistent Team A",
                away_team="Nonexistent Team B",
                bookmakers=[],
            ),
        ]
