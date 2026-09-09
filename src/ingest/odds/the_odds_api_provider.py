"""
Concrete OddsProvider backed by The Odds API (https://the-odds-api.com), a
documented, free-tier-available REST API — chosen per the blueprint's preference for
documented APIs over scraping.

Endpoint and response shape here match the API's own published documentation for
the NFL odds endpoint (verified against their docs, not guessed):

    GET https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds
        ?regions=us&markets=h2h,spreads,totals&oddsFormat=american&apiKey=...

CREDIT BUDGETING (read before changing `regions` or `markets`):
The Odds API's free tier is ~500 credits/month, and cost per call = markets x regions.
A single call with regions=["us"] and markets=["h2h","spreads","totals"] costs 3
credits. At one pull per day that's ~90 credits/month — well within budget, and
consistent with this project's pregame-only scope (no need to poll more than a
few times a day since we don't track in-game movement). Do not casually add more
regions or markets without recomputing this — it's the single tightest constraint
in the whole system per the blueprint's §11.
"""
from __future__ import annotations

import os

import requests

from .provider_base import OddsProvider, RawBookmaker, RawGameOdds, RawMarket, RawOutcome

BASE_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"


class TheOddsApiProvider(OddsProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("THE_ODDS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "THE_ODDS_API_KEY is not set. Get a free key at https://the-odds-api.com/ "
                "and add it to your .env file."
            )

    def fetch_pregame_odds(
        self, markets: list[str] | None = None, regions: list[str] | None = None
    ) -> list[RawGameOdds]:
        markets = markets or ["h2h", "spreads", "totals"]
        regions = regions or ["us"]

        params = {
            "apiKey": self.api_key,
            "regions": ",".join(regions),
            "markets": ",".join(markets),
            "oddsFormat": "american",
        }
        response = requests.get(BASE_URL, params=params, timeout=30)
        response.raise_for_status()

        remaining = response.headers.get("x-requests-remaining")
        used = response.headers.get("x-requests-used")
        if remaining is not None:
            import logging

            logging.getLogger(__name__).info(
                "The Odds API quota: %s used, %s remaining this period", used, remaining
            )

        return [self._parse_game(g) for g in response.json()]

    @staticmethod
    def _parse_game(raw: dict) -> RawGameOdds:
        bookmakers = []
        for bm in raw.get("bookmakers", []):
            markets = []
            for mkt in bm.get("markets", []):
                outcomes = [
                    RawOutcome(
                        name=o["name"],
                        price_american=o["price"],
                        point=o.get("point"),
                    )
                    for o in mkt.get("outcomes", [])
                ]
                markets.append(
                    RawMarket(market_type=mkt["key"], last_update=mkt["last_update"], outcomes=outcomes)
                )
            bookmakers.append(RawBookmaker(key=bm["key"], title=bm["title"], markets=markets))

        return RawGameOdds(
            external_event_id=raw["id"],
            commence_time=raw["commence_time"],
            home_team=raw["home_team"],
            away_team=raw["away_team"],
            bookmakers=bookmakers,
        )
