"""Sportmonks Football API v3 adapter — secondary provider.

Endpoints/fields verified against docs.sportmonks.com (see
.omc/research/vendor-api-specs.md). WC2026 requires a paid plan or the 14-day
trial. Rate limits are per-entity per-hour; 429 responses carry retry_after.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .base import LiveState, OddsQuote
from .http import get_json
from .mapping import map_market, parse_outcome

BASE_URL = "https://api.sportmonks.com/v3/football"
ENV_KEY = "WC26_SPORTMONKS_KEY"

RED_CARD_TYPE_IDS = {20, 21}  # REDCARD, YELLOWREDCARD


class SportmonksProvider:
    name = "sportmonks"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 10.0):
        self.api_key = api_key or os.environ.get(ENV_KEY, "")
        if not self.api_key:
            raise ValueError(f"API key required: pass api_key or set {ENV_KEY}")
        self.timeout = timeout
        self.last_rtt: Optional[float] = None

    def _get(self, path: str, **params) -> list:
        params["api_token"] = self.api_key
        payload, rtt = get_json(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
        self.last_rtt = rtt
        if "error" in payload:
            raise RuntimeError(f"sportmonks {path} error: {payload['error']}")
        data = payload.get("data", [])
        return data if isinstance(data, list) else [data]

    @staticmethod
    def _sides(fixture: dict) -> Optional[dict]:
        """{'home': participant, 'away': participant} from include=participants."""
        sides = {}
        for p in fixture.get("participants", []) or []:
            loc = (p.get("meta") or {}).get("location")
            if loc in ("home", "away"):
                sides[loc] = p
        return sides if len(sides) == 2 else None

    def _find_live(self, home: str, away: str) -> Optional[dict]:
        rows = self._get(
            "/livescores/inplay", include="participants;scores;periods;events"
        )
        for fx in rows:
            sides = self._sides(fx)
            if not sides:
                continue
            if (
                home.casefold() in sides["home"]["name"].casefold()
                and away.casefold() in sides["away"]["name"].casefold()
            ):
                return fx
        return None

    def find_fixture_id(self, home: str, away: str, date: Optional[str] = None) -> Optional[int]:
        fx = self._find_live(home, away)
        if fx:
            return fx["id"]
        if date:
            for row in self._get(f"/fixtures/date/{date}", include="participants"):
                sides = self._sides(row)
                if (
                    sides
                    and home.casefold() in sides["home"]["name"].casefold()
                    and away.casefold() in sides["away"]["name"].casefold()
                ):
                    return row["id"]
        return None

    def live_state(self, home: str, away: str) -> Optional[LiveState]:
        fx = self._find_live(home, away)
        if fx is None:
            return None
        sides = self._sides(fx)

        # `minutes` is period-local (e.g. 17 = 17' into the 2nd half);
        # `counts_from` anchors it to the match clock (45 for the 2nd half).
        # Verify against a trial-key payload — docs don't show a worked example.
        minute = 0.0
        for period in fx.get("periods", []) or []:
            if period.get("ticking"):
                minute = float(period.get("counts_from") or 0) + float(
                    period.get("minutes") or 0
                )

        score = {"home": 0, "away": 0}
        for s in fx.get("scores", []) or []:
            if s.get("description") == "CURRENT":
                inner = s.get("score", {})
                part = str(inner.get("participant", "")).lower()
                if part in score:
                    score[part] = int(inner.get("goals") or 0)

        reds = {"home": 0, "away": 0}
        id_to_side = {sides["home"]["id"]: "home", sides["away"]["id"]: "away"}
        for ev in fx.get("events", []) or []:
            if ev.get("type_id") in RED_CARD_TYPE_IDS and not ev.get("rescinded"):
                side = id_to_side.get(ev.get("participant_id"))
                if side:
                    reds[side] += 1

        return LiveState(
            home=sides["home"]["name"],
            away=sides["away"]["name"],
            minute=minute,
            score_home=score["home"],
            score_away=score["away"],
            red_home=reds["home"],
            red_away=reds["away"],
        )

    def odds(
        self, home: str, away: str, date: Optional[str] = None, inplay: bool = False
    ) -> List[OddsQuote]:
        fixture_id = self.find_fixture_id(home, away, date=date)
        if fixture_id is None:
            return []
        path = (
            f"/odds/inplay/fixtures/{fixture_id}"
            if inplay
            else f"/odds/pre-match/fixtures/{fixture_id}"
        )
        quotes = []
        for odd in self._get(path, include="market;bookmaker"):
            if odd.get("stopped") or odd.get("suspended"):
                continue
            market_name = odd.get("market_description") or (odd.get("market") or {}).get(
                "name", ""
            )
            market = map_market(market_name)
            if not market:
                continue
            parsed = parse_outcome(
                market, odd.get("label", ""), handicap=odd.get("handicap"), total=odd.get("total")
            )
            if not parsed:
                continue
            outcome, line = parsed
            raw_odds = odd.get("dp3") or odd.get("value")
            if raw_odds is None:
                continue  # one malformed row must not kill the whole match's odds
            bookmaker = (odd.get("bookmaker") or {}).get("name", str(odd.get("bookmaker_id", "")))
            quotes.append(
                OddsQuote(
                    home=home,
                    away=away,
                    market=market,
                    outcome=outcome,
                    line=line,
                    odds=float(raw_odds),
                    bookmaker=bookmaker,
                )
            )
        return quotes
