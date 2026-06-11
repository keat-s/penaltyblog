"""CSV-backed provider — manual odds entry, no API key needed."""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .base import LiveState, OddsQuote


class CsvOddsProvider:
    """Reads the same odds CSV format the CLI has always accepted.

    Optional live-state CSV columns: home,away,minute,score_home,score_away,
    red_home,red_away.
    """

    name = "csv"

    def __init__(self, odds_path: str, live_path: Optional[str] = None):
        self._odds = pd.read_csv(odds_path)
        self._live = pd.read_csv(live_path) if live_path else None

    def live_state(self, home: str, away: str) -> Optional[LiveState]:
        if self._live is None:
            return None
        rows = self._live[(self._live["home"] == home) & (self._live["away"] == away)]
        if rows.empty:
            return None
        r = rows.iloc[0]
        return LiveState(
            home=home,
            away=away,
            minute=float(r["minute"]),
            score_home=int(r["score_home"]),
            score_away=int(r["score_away"]),
            red_home=int(r.get("red_home", 0) or 0),
            red_away=int(r.get("red_away", 0) or 0),
        )

    def odds(self, home: str, away: str) -> List[OddsQuote]:
        rows = self._odds[(self._odds["home"] == home) & (self._odds["away"] == away)]
        quotes = []
        for _, r in rows.iterrows():
            line = r.get("line")
            quotes.append(
                OddsQuote(
                    home=home,
                    away=away,
                    market=str(r["market"]).lower(),
                    outcome=str(r["outcome"]).lower(),
                    odds=float(r["odds"]),
                    line=None if pd.isna(line) else float(line),
                    bookmaker=str(r.get("bookmaker", "") or ""),
                )
            )
        return quotes
