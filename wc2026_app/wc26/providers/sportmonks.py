"""Sportmonks Football API v3 adapter — secondary provider.

Endpoints/fields verified against docs.sportmonks.com (see
.omc/research/vendor-api-specs.md). WC2026 requires a paid plan or the 14-day
trial. Rate limits are per-entity per-hour; 429 responses carry retry_after.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional

from .base import LiveState, OddsQuote
from .http import get_json
from .mapping import map_market, normalize_team, parse_outcome

BASE_URL = "https://api.sportmonks.com/v3/football"
ENV_KEY = "WC26_SPORTMONKS_KEY"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "wc26" / "sportmonks_players"

# 7-day TTL: squad rosters and season stats change slowly.
_PLAYER_CACHE_TTL = 7 * 24 * 3600

# Bump when the cached record shape changes so old files auto-invalidate.
# v2: added `born` to team_player_goals records.
_CACHE_SCHEMA = 2

RED_CARD_TYPE_IDS = {20, 21}  # REDCARD, YELLOWREDCARD


class SportmonksProvider:
    name = "sportmonks"

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

    def _cache_read(self, cache_file: Path, ttl_seconds: Optional[float]) -> Optional[list]:
        """Return cached list if the file exists and is still valid, else None."""
        if not cache_file.exists():
            return None
        try:
            cached = json.loads(cache_file.read_text())
            if cached.get("_schema") != _CACHE_SCHEMA:
                return None  # shape changed → ignore old file, re-fetch
            written_at = cached.get("_written_at", 0)
            if ttl_seconds is None or (time.time() - written_at) < ttl_seconds:
                return cached["data"]
        except (json.JSONDecodeError, KeyError):
            pass  # corrupt cache → re-fetch
        return None

    def _cache_write(self, cache_file: Path, data: list) -> None:
        """Write *data* to *cache_file* with a timestamp + schema version."""
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"_schema": _CACHE_SCHEMA, "_written_at": time.time(), "data": data})
        )

    def _get(self, path: str, **params) -> list:
        params["api_token"] = self.api_key
        payload, rtt = get_json(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
        self.last_rtt = rtt
        if "error" in payload:
            raise RuntimeError(f"sportmonks {path} error: {payload['error']}")
        msg = payload.get("message")
        if msg and "data" not in payload:
            raise RuntimeError(f"sportmonks {path}: {msg}")
        data = payload.get("data", [])
        return data if isinstance(data, list) else [data]

    def _get_paged(self, path: str, max_pages: int = 20, **params) -> list:
        """Follow Sportmonks pagination, accumulating `data` across pages."""
        params["api_token"] = self.api_key
        rows: list = []
        page = 1
        while page <= max_pages:
            params["page"] = page
            payload, rtt = get_json(
                f"{BASE_URL}{path}", params=params, timeout=self.timeout
            )
            self.last_rtt = rtt
            msg = payload.get("message")
            if msg and "data" not in payload:
                raise RuntimeError(f"sportmonks {path}: {msg}")
            rows.extend(payload.get("data", []) or [])
            pg = payload.get("pagination") or {}
            if not pg.get("has_more"):
                break
            page += 1
        return rows

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

    # --- results backfill -------------------------------------------------

    @staticmethod
    def _final_score(fixture: dict) -> Optional[dict]:
        """{'home': goals, 'away': goals} from the CURRENT score, or None."""
        score = {}
        for s in fixture.get("scores", []) or []:
            if s.get("description") == "CURRENT":
                inner = s.get("score", {})
                part = str(inner.get("participant", "")).lower()
                if part in ("home", "away"):
                    score[part] = int(inner.get("goals") or 0)
        return score if len(score) == 2 else None

    def results(self, date_from: str, date_to: str) -> List[dict]:
        """Finished matches in [date_from, date_to] as result rows.

        Each row: {date, home_team, away_team, home_score, away_score,
        fixture_id}. Only fixtures that are actually finished (a CURRENT score
        is present) are returned; team names are normalized to the dataset
        spelling. Scheduled/in-play fixtures are skipped.
        """
        rows = self._get_paged(
            f"/fixtures/between/{date_from}/{date_to}",
            include="participants;scores",
            per_page=50,
        )
        out = []
        for fx in rows:
            sides = self._sides(fx)
            score = self._final_score(fx)
            if not sides or not score:
                continue
            # require a finished match: result_info is set only post-match
            if not fx.get("result_info"):
                continue
            out.append(
                {
                    "date": str(fx.get("starting_at", ""))[:10],
                    "home_team": normalize_team(sides["home"]["name"]),
                    "away_team": normalize_team(sides["away"]["name"]),
                    "home_score": score["home"],
                    "away_score": score["away"],
                    "fixture_id": fx["id"],
                }
            )
        return out

    # --- shot statistics (for the xG proxy) -------------------------------

    # Sportmonks statistic type names we use to approximate xG.
    _SHOT_TYPES = {
        "Big Chances Created": "big_chances_created",
        "Shots Insidebox": "shots_insidebox",
        "Shots Outsidebox": "shots_outsidebox",
        "Shots On Target": "shots_on_target",
        "Shots Total": "shots_total",
    }

    # --- player goal stats (for anytime-scorer props) --------------------

    def find_team_id(self, name: str) -> Optional[int]:
        """Resolve a national-team name to its Sportmonks team id.

        Result is cached indefinitely (team ids are stable).
        """
        cache_file = self._cache_dir / "teams" / f"{name.lower().replace(' ', '_')}.json"
        cached = self._cache_read(cache_file, ttl_seconds=None)
        if cached is not None:
            return cached[0] if cached else None

        rows = self._get(f"/teams/search/{name}")
        team_id: Optional[int] = None
        for t in rows:
            if t.get("name", "").casefold() == name.casefold():
                team_id = t["id"]
                break
        if team_id is None and rows:
            team_id = rows[0]["id"]

        self._cache_write(cache_file, [team_id] if team_id is not None else [])
        return team_id

    def _squad_members(self, team_id: int) -> list:
        """Return the squad member list for *team_id*, cached with 7-day TTL."""
        cache_file = self._cache_dir / "squads" / f"{team_id}.json"
        cached = self._cache_read(cache_file, _PLAYER_CACHE_TTL)
        if cached is not None:
            return cached

        squad = self._get(f"/teams/{team_id}", include="players.player")
        members = (squad[0].get("players") if squad else None) or []
        self._cache_write(cache_file, members)
        return members

    def _player_stats(self, pid: int) -> list:
        """Return per-season statistics for *pid*, cached with 7-day TTL."""
        cache_file = self._cache_dir / "players" / f"{pid}.json"
        cached = self._cache_read(cache_file, _PLAYER_CACHE_TTL)
        if cached is not None:
            return cached

        rows = self._get(f"/players/{pid}", include="statistics.details.type")
        stats = (rows[0].get("statistics") if rows else []) or []
        self._cache_write(cache_file, stats)
        return stats

    def team_player_goals(
        self, team: str, max_players: int = 30, bypass_cache: bool = False
    ) -> List[dict]:
        """Per-player goal tallies for a national team's current squad.

        Aggregates each player's `Goals`/`Minutes Played`/`Appearances` across
        the seasons Sportmonks exposes (club + international), which is enough
        signal for goal *shares* — the props model only uses relative goals.
        Returns [{player, goals, minutes, appearances}] like the API-Football
        adapter, so it drops straight into `props.scorer_table`.

        Results are disk-cached (7-day TTL) under ~/.cache/wc26/sportmonks_players/.
        Pass bypass_cache=True or set WC26_BYPASS_CACHE=1 to force a fresh fetch.
        """
        if bypass_cache or os.environ.get("WC26_BYPASS_CACHE"):
            return self._fetch_team_player_goals(team, max_players)

        cache_file = self._cache_dir / "team_goals" / f"{team.lower().replace(' ', '_')}.json"
        cached = self._cache_read(cache_file, _PLAYER_CACHE_TTL)
        if cached is not None:
            return cached

        result = self._fetch_team_player_goals(team, max_players)
        self._cache_write(cache_file, result)
        return result

    def _fetch_team_player_goals(self, team: str, max_players: int) -> List[dict]:
        """Internal: fetch player goal tallies without consulting the top-level cache."""
        team_id = self.find_team_id(team)
        if team_id is None:
            return []
        members = self._squad_members(team_id)

        out = []
        for m in members[:max_players]:
            player = m.get("player") or {}
            pid, pname = player.get("id"), player.get("name")
            if not pid or not pname:
                continue
            dob = player.get("date_of_birth")  # "YYYY-MM-DD"
            born = int(dob[:4]) if dob else None
            stats = self._player_stats(pid)
            goals = minutes = apps = 0
            for season in stats:
                for d in season.get("details", []) or []:
                    tname = (d.get("type") or {}).get("name")
                    val = d.get("value") or {}
                    total = val.get("total") or 0
                    if tname == "Goals":
                        goals += int(total)
                    elif tname == "Minutes Played":
                        minutes += int(total)
                    elif tname == "Appearances":
                        apps += int(total)
            out.append(
                {
                    "player": pname,
                    "goals": goals,
                    "minutes": minutes,
                    "appearances": apps,
                    "born": born,
                }
            )
        return out

    def match_shot_stats(self, fixture_id: int) -> Optional[dict]:
        """Per-side shot counts for one fixture: {'home': {...}, 'away': {...}}.

        Returns None if statistics or participant sides are unavailable.
        """
        rows = self._get(
            f"/fixtures/{fixture_id}", include="statistics.type;participants"
        )
        if not rows:
            return None
        fx = rows[0]
        sides = self._sides(fx)
        if not sides:
            return None
        id_to_side = {sides["home"]["id"]: "home", sides["away"]["id"]: "away"}
        out = {"home": {}, "away": {}}
        for s in fx.get("statistics", []) or []:
            tname = (s.get("type") or {}).get("name")
            key = self._SHOT_TYPES.get(tname)
            if not key:
                continue
            side = id_to_side.get(s.get("participant_id"))
            if side:
                out[side][key] = (s.get("data") or {}).get("value")
        return out if (out["home"] or out["away"]) else None
