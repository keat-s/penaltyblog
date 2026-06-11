"""Provider-agnostic types for live match state and odds.

Vendor adapters normalize their payloads into these types so the edge engine
never sees vendor-specific JSON. Odds quotes map 1:1 onto the odds-row dicts
consumed by `edge.build_candidates`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class LiveState:
    """Normalized in-play match state."""

    home: str
    away: str
    minute: float
    score_home: int
    score_away: int
    red_home: int = 0
    red_away: int = 0
    status: str = "live"  # live | ht | ft | ns (not started)
    fetched_at: float = field(default_factory=time.time)


@dataclass
class OddsQuote:
    """One price on one outcome; convertible to an edge-engine odds row."""

    home: str
    away: str
    market: str  # 1x2 | ou | ah | btts | dnb | dc
    outcome: str
    odds: float
    line: Optional[float] = None
    bookmaker: str = ""

    def as_row(self) -> dict:
        return {
            "home": self.home,
            "away": self.away,
            "market": self.market,
            "outcome": self.outcome,
            "line": self.line,
            "odds": self.odds,
            "bookmaker": self.bookmaker,
        }


class OddsProvider(Protocol):
    """Minimal interface every provider implements."""

    name: str

    def live_state(self, home: str, away: str) -> Optional[LiveState]:
        """Current state for a match, or None if not found/live."""
        ...

    def odds(self, home: str, away: str) -> List[OddsQuote]:
        """Available quotes for a match (pre-match or in-play)."""
        ...
