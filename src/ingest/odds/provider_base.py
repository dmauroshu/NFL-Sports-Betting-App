"""
Provider interface for pregame odds. Per the blueprint's §5 (design provider
interfaces so data vendors can be replaced later): odds_ingest.py depends only on
this interface, never on a specific vendor's request/response shape. Swapping The
Odds API for a different provider later means writing one new class here, not
touching the ingestion or matching logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawOutcome:
    name: str            # team name, or 'Over'/'Under'
    price_american: int
    point: float | None  # spread/total line; None for moneyline


@dataclass
class RawMarket:
    market_type: str     # 'h2h' | 'spreads' | 'totals'
    last_update: str     # ISO8601 string, as provided by the vendor
    outcomes: list[RawOutcome]


@dataclass
class RawBookmaker:
    key: str
    title: str
    markets: list[RawMarket]


@dataclass
class RawGameOdds:
    external_event_id: str
    commence_time: str   # ISO8601 string
    home_team: str        # full team name, e.g. "Kansas City Chiefs"
    away_team: str
    bookmakers: list[RawBookmaker]


class OddsProvider(ABC):
    @abstractmethod
    def fetch_pregame_odds(self, markets: list[str], regions: list[str]) -> list[RawGameOdds]:
        """Return current pregame odds for all upcoming games the vendor has listed."""
        raise NotImplementedError
