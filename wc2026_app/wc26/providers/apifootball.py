"""API-Football (api-sports.io) v3 adapter — primary live provider.

Endpoints/fields verified against the official v3 docs (see
.omc/research/vendor-api-specs.md). Free tier: 100 requests/day, header
`x-apisports-key`. Live odds refresh ~5s server-side; fixtures/events ~15s.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import LiveState, OddsQuote
from .http import get_json
from .mapping import map_market, parse_outcome

BASE_URL = "https://v3.football.api-sports.io"
ENV_KEY = "WC26_APIFOOTBALL_KEY"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "wc26" / "apifootball"

# Map API-Football type strings to our field names.
_STAT_MAP = {
    "Corner Kicks": "corners",
    "Shots on Goal": "shots_on_goal",
    "Total Shots": "shots_total",
    "Fouls": "fouls",
}


class ApiFootballProvider:
    name = "api_football"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        cache_dir: Optional[Path] = None,
    ):
        self.api_key = api_key or os.environ.get(ENV_KEY, "")
        if not self.api_key:
            raise ValueError(f"API key required: pass api_key or set {ENV_KEY}")
        self.timeout = timeout
        self.last_rtt: Optional[float] = None
        self._cache_dir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR

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

    def _cache_key(self, path: str, params: dict) -> Path:
        """Return cache file path for a given path + params combination."""
        canon = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        digest = hashlib.sha256(canon.encode()).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _get_cached(self, path: str, ttl_seconds: Optional[float], **params) -> list:
        """Return cached JSON response, fetching from API only on a miss or expiry.

        ttl_seconds=None means immutable: once written the entry is never
        re-fetched (suitable for finished-fixture statistics).
        """
        cache_file = self._cache_key(path, params)
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                written_at = cached.get("_written_at", 0)
                if ttl_seconds is None or (time.time() - written_at) < ttl_seconds:
                    return cached["response"]
            except (json.JSONDecodeError, KeyError):
                pass  # corrupt cache → re-fetch

        data = self._get(path, **params)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"_written_at": time.time(), "response": data})
        )
        return data

    # ------------------------------------------------------------------
    # Props data endpoints
    # ------------------------------------------------------------------

    def team_id(self, name: str) -> Optional[int]:
        """Return API-Football team id for *name*, or None if not found.

        Tries an exact-name lookup first; falls back to search= if the
        exact lookup returns no results.
        """
        rows = self._get_cached("/teams", None, name=name)
        if rows:
            return int(rows[0]["team"]["id"])
        rows = self._get_cached("/teams", None, search=name)
        if rows:
            return int(rows[0]["team"]["id"])
        return None

    def player_goal_stats(self, team_name: str, season: int) -> List[dict]:
        """Return per-player aggregated goal stats across all competitions.

        Follows paging (paging.current / paging.total) automatically.
        Each entry: {player, goals, minutes, appearances}.
        24-hour TTL (season data updates as matches complete).
        """
        tid = self.team_id(team_name)
        if tid is None:
            return []

        ttl = 24 * 3600
        aggregated: Dict[str, dict] = {}

        def _fetch_page(page: int) -> tuple[list, int]:
            """Fetch one page; returns (response_list, total_pages)."""
            payload, rtt = get_json(
                f"{BASE_URL}/players",
                params={"team": tid, "season": season, "page": page},
                headers={"x-apisports-key": self.api_key},
                timeout=self.timeout,
            )
            self.last_rtt = rtt
            errors = payload.get("errors")
            if errors and (errors if isinstance(errors, list) else list(errors.values())):
                raise RuntimeError(f"api-football /players error: {errors}")
            total_pages = payload.get("paging", {}).get("total", 1)
            return payload.get("response", []), total_pages

        # Use disk cache per page
        def _cached_page(page: int) -> tuple[list, int]:
            cache_file = self._cache_key(
                "/players", {"team": str(tid), "season": str(season), "page": str(page)}
            )
            if cache_file.exists():
                try:
                    cached = json.loads(cache_file.read_text())
                    written_at = cached.get("_written_at", 0)
                    if (time.time() - written_at) < ttl:
                        return cached["response"], cached.get("total_pages", 1)
                except (json.JSONDecodeError, KeyError):
                    pass

            rows, total_pages = _fetch_page(page)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(
                    {"_written_at": time.time(), "response": rows, "total_pages": total_pages}
                )
            )
            return rows, total_pages

        page = 1
        while True:
            rows, total_pages = _cached_page(page)
            for entry in rows:
                pname = entry["player"]["name"]
                if pname not in aggregated:
                    aggregated[pname] = {"player": pname, "goals": 0, "minutes": 0, "appearances": 0}
                for stat in entry.get("statistics", []):
                    aggregated[pname]["goals"] += int(stat.get("goals", {}).get("total") or 0)
                    aggregated[pname]["minutes"] += int(stat.get("games", {}).get("minutes") or 0)
                    aggregated[pname]["appearances"] += int(stat.get("games", {}).get("appearences") or 0)
            if page >= total_pages:
                break
            page += 1

        return list(aggregated.values())

    def fixture_statistics(self, fixture_id: int) -> Dict[str, dict]:
        """Return per-team statistics for a finished fixture.

        Returns {team_name: {corners, shots_on_goal, shots_total, fouls}}.
        Null API values become 0.  Immutable cache (fixture results don't change).
        """
        rows = self._get_cached("/fixtures/statistics", None, fixture=fixture_id)
        result: Dict[str, dict] = {}
        for entry in rows:
            team_name = entry["team"]["name"]
            stats: Dict[str, int] = {field: 0 for field in _STAT_MAP.values()}
            for stat in entry.get("statistics", []):
                field = _STAT_MAP.get(stat["type"])
                if field is not None:
                    stats[field] = int(stat["value"] or 0)
            result[team_name] = stats
        return result

    def team_stat_records(
        self, team_name: str, last_n: int = 20, stat: str = "corners"
    ) -> List[dict]:
        """Return {team, opponent, value} records for both sides of each fixture.

        Fetches the last *last_n* finished fixtures for *team_name*, then
        calls fixture_statistics (cached) for each.  Both the for-side and
        against-side observations are returned so fit_team_rates can compute
        both for_ and against_ rates.
        """
        tid = self.team_id(team_name)
        if tid is None:
            return []

        fixtures = self._get_cached("/fixtures", None, team=tid, last=last_n, status="FT")
        records: List[dict] = []
        for fx in fixtures:
            fixture_id = fx["fixture"]["id"]
            home_name = fx["teams"]["home"]["name"]
            away_name = fx["teams"]["away"]["name"]
            try:
                stats = self.fixture_statistics(fixture_id)
            except Exception:
                continue
            # Emit one record per team side so fit_team_rates gets both
            # the for-side (team scored X) and the against-side (opponent
            # conceded X) observations from the same match.
            for team, opponent in [(home_name, away_name), (away_name, home_name)]:
                team_stats = stats.get(team, {})
                value = team_stats.get(stat, 0)
                records.append({"team": team, "opponent": opponent, "value": value})
        return records

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
