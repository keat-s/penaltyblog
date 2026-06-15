"""Unit tests for SportmonksProvider disk-cache layer.

All tests are network-free: _get is monkeypatched.  The tmp_path fixture
provides a fresh per-test cache dir so tests never interfere.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from wc26.providers.sportmonks import SportmonksProvider, _PLAYER_CACHE_TTL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider(tmp_path: Path) -> SportmonksProvider:
    return SportmonksProvider(api_key="test", cache_dir=tmp_path)


# Minimal squad payload matching the real /teams/{id}?include=players.player shape.
_SQUAD_RESPONSE = [
    {
        "id": 1,
        "players": [
            {"player": {"id": 101, "name": "Player One"}},
            {"player": {"id": 102, "name": "Player Two"}},
        ],
    }
]

# Per-player stats payload matching /players/{id}?include=statistics.details.type.
def _player_stats_response(player_id: int, goals: int = 3) -> list:
    return [
        {
            "id": player_id,
            "statistics": [
                {
                    "details": [
                        {"type": {"name": "Goals"}, "value": {"total": goals}},
                        {"type": {"name": "Minutes Played"}, "value": {"total": 450}},
                        {"type": {"name": "Appearances"}, "value": {"total": 5}},
                    ]
                }
            ],
        }
    ]


# ---------------------------------------------------------------------------
# find_team_id cache
# ---------------------------------------------------------------------------

class TestFindTeamIdCache:
    def test_miss_calls_get(self, tmp_path):
        p = _provider(tmp_path)
        call_count = 0

        def counting_get(path, **kw):
            nonlocal call_count
            call_count += 1
            return [{"id": 42, "name": "Spain"}]

        p._get = counting_get
        result = p.find_team_id("Spain")
        assert result == 42
        assert call_count == 1

    def test_hit_does_not_call_get(self, tmp_path):
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=[{"id": 42, "name": "Spain"}])
        p.find_team_id("Spain")                       # miss → fetches
        p._get = MagicMock(return_value=[{"id": 999}])  # would return wrong id
        result = p.find_team_id("Spain")              # hit → no fetch
        assert result == 42
        p._get.assert_not_called()

    def test_not_found_caches_none(self, tmp_path):
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=[])
        assert p.find_team_id("NoSuchTeam") is None
        # Second call must also return None without calling _get again.
        p._get = MagicMock(return_value=[{"id": 1, "name": "NoSuchTeam"}])
        assert p.find_team_id("NoSuchTeam") is None
        p._get.assert_not_called()


# ---------------------------------------------------------------------------
# team_player_goals top-level cache
# ---------------------------------------------------------------------------

class TestTeamPlayerGoalsCache:
    def _setup_get(self, p: SportmonksProvider) -> MagicMock:
        """Wire up _get to return squad + per-player stats."""
        def fake_get(path, **kw):
            if path.startswith("/teams/search/"):
                return [{"id": 1, "name": "Spain"}]
            if path.startswith("/teams/"):
                return _SQUAD_RESPONSE
            if path.startswith("/players/101"):
                return _player_stats_response(101, goals=5)
            if path.startswith("/players/102"):
                return _player_stats_response(102, goals=2)
            return []

        p._get = MagicMock(side_effect=fake_get)
        return p._get

    def test_returns_correct_shape(self, tmp_path):
        p = _provider(tmp_path)
        self._setup_get(p)
        result = p.team_player_goals("Spain")
        assert len(result) == 2
        by_name = {r["player"]: r for r in result}
        assert by_name["Player One"]["goals"] == 5
        assert by_name["Player Two"]["goals"] == 2
        assert set(by_name["Player One"].keys()) == {"player", "goals", "minutes", "appearances"}

    def test_cache_hit_skips_all_network_calls(self, tmp_path):
        p = _provider(tmp_path)
        self._setup_get(p)
        p.team_player_goals("Spain")          # miss → network

        p._get = MagicMock()                  # any call would be wrong
        result = p.team_player_goals("Spain") # hit → no network
        p._get.assert_not_called()

        # Result must be identical
        assert len(result) == 2
        assert {r["player"] for r in result} == {"Player One", "Player Two"}

    def _backdate_all_caches(self, tmp_path: Path) -> None:
        """Expire every cache file written under tmp_path."""
        for f in tmp_path.rglob("*.json"):
            try:
                raw = json.loads(f.read_text())
                raw["_written_at"] = time.time() - _PLAYER_CACHE_TTL - 10
                f.write_text(json.dumps(raw))
            except Exception:
                pass

    def test_ttl_expiry_triggers_refetch(self, tmp_path):
        p = _provider(tmp_path)
        self._setup_get(p)
        p.team_player_goals("Spain")          # populate all sub-caches

        # Expire ALL cache files (team_goals + player sub-caches).
        self._backdate_all_caches(tmp_path)

        # New data with different goal counts.
        def updated_get(path, **kw):
            if path.startswith("/teams/search/"):
                return [{"id": 1, "name": "Spain"}]
            if path.startswith("/teams/"):
                return _SQUAD_RESPONSE
            if path.startswith("/players/101"):
                return _player_stats_response(101, goals=99)
            if path.startswith("/players/102"):
                return _player_stats_response(102, goals=88)
            return []

        p._get = MagicMock(side_effect=updated_get)
        result = p.team_player_goals("Spain")
        by_name = {r["player"]: r for r in result}
        assert by_name["Player One"]["goals"] == 99

    def test_bypass_cache_flag_forces_refetch(self, tmp_path):
        p = _provider(tmp_path)
        self._setup_get(p)
        p.team_player_goals("Spain")          # populate all sub-caches

        # Expire sub-caches so _get is called during _fetch_team_player_goals.
        self._backdate_all_caches(tmp_path)

        mock2 = MagicMock(side_effect=lambda path, **kw: (
            [{"id": 1, "name": "Spain"}] if path.startswith("/teams/search/") else
            _SQUAD_RESPONSE if path.startswith("/teams/") else
            _player_stats_response(101, goals=77) if path.startswith("/players/101") else
            _player_stats_response(102, goals=66) if path.startswith("/players/102") else []
        ))
        p._get = mock2
        result = p.team_player_goals("Spain", bypass_cache=True)
        assert mock2.call_count > 0  # network was hit
        by_name = {r["player"]: r for r in result}
        assert by_name["Player One"]["goals"] == 77

    def test_bypass_cache_env_forces_refetch(self, tmp_path, monkeypatch):
        p = _provider(tmp_path)
        self._setup_get(p)
        p.team_player_goals("Spain")

        # Expire sub-caches so _get is exercised.
        self._backdate_all_caches(tmp_path)

        monkeypatch.setenv("WC26_BYPASS_CACHE", "1")
        mock2 = MagicMock(side_effect=lambda path, **kw: (
            [{"id": 1, "name": "Spain"}] if path.startswith("/teams/search/") else
            _SQUAD_RESPONSE if path.startswith("/teams/") else
            _player_stats_response(101, goals=55) if path.startswith("/players/101") else
            _player_stats_response(102, goals=44) if path.startswith("/players/102") else []
        ))
        p._get = mock2
        result = p.team_player_goals("Spain")
        assert mock2.call_count > 0
        by_name = {r["player"]: r for r in result}
        assert by_name["Player One"]["goals"] == 55


# ---------------------------------------------------------------------------
# _cache_read / _cache_write mechanics
# ---------------------------------------------------------------------------

class TestCacheMechanics:
    def test_missing_file_returns_none(self, tmp_path):
        p = _provider(tmp_path)
        assert p._cache_read(tmp_path / "nonexistent.json", 3600) is None

    def test_round_trip(self, tmp_path):
        p = _provider(tmp_path)
        cache_file = tmp_path / "test.json"
        data = [{"player": "X", "goals": 1}]
        p._cache_write(cache_file, data)
        assert p._cache_read(cache_file, 3600) == data

    def test_immutable_never_expires(self, tmp_path):
        p = _provider(tmp_path)
        cache_file = tmp_path / "test.json"
        data = [{"player": "Y", "goals": 9}]
        p._cache_write(cache_file, data)
        # Backdate to epoch.
        raw = json.loads(cache_file.read_text())
        raw["_written_at"] = 0
        cache_file.write_text(json.dumps(raw))
        assert p._cache_read(cache_file, ttl_seconds=None) == data

    def test_expired_entry_returns_none(self, tmp_path):
        p = _provider(tmp_path)
        cache_file = tmp_path / "test.json"
        p._cache_write(cache_file, [{"player": "Z"}])
        raw = json.loads(cache_file.read_text())
        raw["_written_at"] = time.time() - 10
        cache_file.write_text(json.dumps(raw))
        assert p._cache_read(cache_file, ttl_seconds=1) is None

    def test_corrupt_file_returns_none(self, tmp_path):
        p = _provider(tmp_path)
        cache_file = tmp_path / "corrupt.json"
        cache_file.write_text("not valid json{{{")
        assert p._cache_read(cache_file, 3600) is None
