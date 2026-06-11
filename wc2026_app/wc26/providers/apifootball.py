"""API-Football (api-sports.io) v3 adapter — primary live provider.

Endpoints/fields verified against the official v3 docs (see
.omc/research/vendor-api-specs.md). Free tier: 100 requests/day, header
`x-apisports-key`. Live odds refresh ~5s server-side; fixtures/events ~15s.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .base import LiveState, OddsQuote
from .http import get_json
from .mapping import map_market, parse_outcome

BASE_URL = "https://v3.football.api-sports.io"
ENV_KEY = "WC26_APIFOOTBALL_KEY"


class ApiFootballProvider:
    name = "api_football"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 10.0):
        self.api_key = api_key or os.environ.get(ENV_KEY, "")
        if not self.api_key:
            raise ValueError(f"API key required: pass api_key or set {ENV_KEY}")
        self.timeout = timeout
        self.last_rtt: Optional[float] = None

    def _get(self, path: str, **params) -> list:
        payload, rtt = get_json(
            f"{BASE_URL}{path}",
            params=params,
            headers={"x-apisports-key": self.api_key},
            timeout=self.timeout,
        )
        self.last_rtt = rtt
        errors = payload.get("errors")
        if errors and (errors if isinstance(errors, list) else list(errors.values())):
            raise RuntimeError(f"api-football {path} error: {errors}")
        return payload.get("response", [])

    @staticmethod
    def _team_match(fixture: dict, home: str, away: str) -> bool:
        fh = fixture["teams"]["home"]["name"].casefold()
        fa = fixture["teams"]["away"]["name"].casefold()
        return home.casefold() in fh and away.casefold() in fa

    def find_fixture(self, home: str, away: str, date: Optional[str] = None) -> Optional[dict]:
        """Find a fixture by team names: live matches first, then by date."""
        for fx in self._get("/fixtures", live="all"):
            if self._team_match(fx, home, away):
                return fx
        if date:
            for fx in self._get("/fixtures", date=date):
                if self._team_match(fx, home, away):
                    return fx
        return None

    @staticmethod
    def _red_cards(fixture: dict) -> tuple[int, int]:
        """Count red cards from inline events (present on live=all payloads)."""
        reds = {"home": 0, "away": 0}
        home_id = fixture["teams"]["home"]["id"]
        for ev in fixture.get("events", []) or []:
            detail = str(ev.get("detail", "")).lower()
            # Exact detail strings per vendor docs; substring matching risks
            # counting unrelated card events.
            if ev.get("type", "").lower() == "card" and detail in ("red card", "yellow red card"):
                side = "home" if ev.get("team", {}).get("id") == home_id else "away"
                reds[side] += 1
        return reds["home"], reds["away"]

    def live_state(self, home: str, away: str) -> Optional[LiveState]:
        fx = self.find_fixture(home, away)
        if fx is None:
            return None
        status = fx["fixture"]["status"]
        red_h, red_a = self._red_cards(fx)
        short = status.get("short", "")
        return LiveState(
            home=fx["teams"]["home"]["name"],
            away=fx["teams"]["away"]["name"],
            minute=float(status.get("elapsed") or 0),
            score_home=int(fx["goals"]["home"] or 0),
            score_away=int(fx["goals"]["away"] or 0),
            red_home=red_h,
            red_away=red_a,
            status={"NS": "ns", "TBD": "ns", "HT": "ht", "FT": "ft", "AET": "ft", "PEN": "ft"}.get(
                short, "live"
            ),
        )

    def odds(self, home: str, away: str, date: Optional[str] = None) -> List[OddsQuote]:
        fx = self.find_fixture(home, away, date=date)
        if fx is None:
            return []
        fixture_id = fx["fixture"]["id"]
        is_live = fx["fixture"]["status"].get("short") in ("1H", "HT", "2H", "ET", "BT", "P", "LIVE")
        h_name, a_name = fx["teams"]["home"]["name"], fx["teams"]["away"]["name"]
        return (
            self._live_odds(fixture_id, h_name, a_name)
            if is_live
            else self._prematch_odds(fixture_id, h_name, a_name)
        )

    def _prematch_odds(self, fixture_id: int, home: str, away: str) -> List[OddsQuote]:
        quotes = []
        for entry in self._get("/odds", fixture=fixture_id):
            for bookmaker in entry.get("bookmakers", []):
                for bet in bookmaker.get("bets", []):
                    market = map_market(bet.get("name", ""))
                    if not market:
                        continue
                    for v in bet.get("values", []):
                        parsed = parse_outcome(market, v.get("value", ""))
                        if not parsed:
                            continue
                        outcome, line = parsed
                        # Pre-match AH labels are home-referenced on BOTH rows:
                        # "Away -1.25" @ 1.84 is the away side of the home -1.25
                        # line, i.e. away +1.25 (verified against live payload:
                        # the Home/Away pair at the same printed handicap forms
                        # a ~2% two-sided market). Normalize to per-side lines.
                        if market == "ah" and outcome == "away" and line is not None:
                            line = -line
                        quotes.append(
                            OddsQuote(
                                home=home,
                                away=away,
                                market=market,
                                outcome=outcome,
                                line=line,
                                odds=float(v["odd"]),
                                bookmaker=bookmaker.get("name", ""),
                            )
                        )
        return quotes

    def _live_odds(self, fixture_id: int, home: str, away: str) -> List[OddsQuote]:
        quotes = []
        for entry in self._get("/odds/live", fixture=fixture_id):
            if entry.get("status", {}).get("stopped") or entry.get("status", {}).get("blocked"):
                continue
            for bet in entry.get("odds", []):
                market = map_market(bet.get("name", ""))
                if not market:
                    continue
                # Duplicate values per bet: the main:true row is the live line.
                # `is True` matters: main:false marks superseded duplicates and
                # must not be used as a fallback; main:null means no main concept.
                values = bet.get("values", [])
                mains = [v for v in values if v.get("main") is True]
                for v in mains or values:
                    if v.get("suspended"):
                        continue
                    parsed = parse_outcome(market, v.get("value", ""), handicap=v.get("handicap"))
                    if not parsed:
                        continue
                    outcome, line = parsed
                    quotes.append(
                        OddsQuote(
                            home=home,
                            away=away,
                            market=market,
                            outcome=outcome,
                            line=line,
                            odds=float(v["odd"]),
                            bookmaker="api-football-live",
                        )
                    )
        return quotes
