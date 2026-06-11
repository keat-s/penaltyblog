"""Tests for ApiFootballProvider props endpoints (P2).

All tests are payload-based (no real network calls).  Live fixture files
saved under tests/data/ were constructed from the documented API-Football
v3 response shape — the API daily limit was exhausted during development
so payloads were built from the spec; shapes are consistent with the
existing _get / live_state / odds tests already in test_providers.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wc26.providers.apifootball import ApiFootballProvider

DATA = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(filename: str) -> dict:
    return json.loads((DATA / filename).read_text())


def _provider(tmp_path: Path) -> ApiFootballProvider:
    return ApiFootballProvider(api_key="test", cache_dir=tmp_path)


# ---------------------------------------------------------------------------
# team_id
# ---------------------------------------------------------------------------

class TestTeamId:
    def test_exact_name_hit(self, tmp_path):
        payload = _load("teams_name_mexico.json")
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=payload["response"])
        assert p.team_id("Mexico") == 16

    def test_exact_miss_falls_back_to_search(self, tmp_path):
        p = _provider(tmp_path)
        # First call (exact name) returns empty; second call (search) returns a result.
        p._get = MagicMock(side_effect=[
            [],
            _load("teams_name_mexico.json")["response"],
        ])
        assert p.team_id("Mex") == 16

    def test_both_miss_returns_none(self, tmp_path):
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=[])
        assert p.team_id("NoSuchTeamXYZ") is None

    def test_immutable_cache_hit_does_not_call_get(self, tmp_path):
        """Second call for the same name must NOT hit the network."""
        payload = _load("teams_name_mexico.json")
        p = _provider(tmp_path)
        call_count = 0

        def counting_get(path, **params):
            nonlocal call_count
            call_count += 1
            return payload["response"]

        p._get = counting_get
        p.team_id("Mexico")   # miss → fetches
        p.team_id("Mexico")   # hit  → no fetch
        assert call_count == 1


# ---------------------------------------------------------------------------
# player_goal_stats — paging + aggregation
# ---------------------------------------------------------------------------

class TestPlayerGoalStats:
    def _setup_two_page(self, tmp_path) -> ApiFootballProvider:
        """Provider wired to return two pages of player data."""
        page1 = _load("players_team_season_page1.json")
        page2 = _load("players_team_season_page2.json")
        p = _provider(tmp_path)

        # team_id lookup
        teams_resp = _load("teams_name_mexico.json")["response"]

        import wc26.providers.apifootball as mod
        from unittest.mock import patch

        real_get_json_calls = []

        def fake_get_json(url, params=None, headers=None, timeout=10.0):
            real_get_json_calls.append((url, params))
            if "teams" in url:
                return {"errors": [], "response": teams_resp, "paging": {"current": 1, "total": 1}}, 0.1
            pg = (params or {}).get("page", 1)
            data = page1 if int(pg) == 1 else page2
            return data, 0.1

        p._fake_get_json = fake_get_json
        return p, fake_get_json, real_get_json_calls

    def test_aggregates_across_competitions(self, tmp_path):
        """Lozano appears in two stat blocks; goals must be summed."""
        page1 = _load("players_team_season_page1.json")
        teams_resp = _load("teams_name_mexico.json")["response"]

        p = _provider(tmp_path)

        def fake_get(path, **params):
            if path == "/teams":
                return teams_resp
            # return only page 1 (single page)
            data = page1.copy()
            data["paging"]["total"] = 1
            return data["response"]

        p._get = MagicMock(side_effect=fake_get)

        # Patch get_json used internally by player_goal_stats
        import wc26.providers.apifootball as mod
        from unittest.mock import patch

        def fake_get_json(url, params=None, headers=None, timeout=10.0):
            if "teams" in url:
                return {"errors": [], "response": teams_resp, "paging": {"current": 1, "total": 1}}, 0.05
            pg = int((params or {}).get("page", 1))
            data = page1.copy()
            data["paging"]["total"] = 1
            return data, 0.05

        with patch.object(mod, "get_json", fake_get_json):
            results = p.player_goal_stats("Mexico", 2025)

        by_name = {r["player"]: r for r in results}
        # Lozano: 3 + 1 = 4 goals across two stat blocks in page1
        assert by_name["H. Lozano"]["goals"] == 4
        assert by_name["H. Lozano"]["appearances"] == 7  # 5 + 2
        assert by_name["H. Lozano"]["minutes"] == 500    # 380 + 120
        # Jimenez: 2 goals
        assert by_name["R. Jimenez"]["goals"] == 2

    def test_paging_followed(self, tmp_path):
        """Two-page response must include players from both pages."""
        page1 = _load("players_team_season_page1.json")
        page2 = _load("players_team_season_page2.json")
        teams_resp = _load("teams_name_mexico.json")["response"]

        p = _provider(tmp_path)

        import wc26.providers.apifootball as mod
        from unittest.mock import patch

        def fake_get_json(url, params=None, headers=None, timeout=10.0):
            if "teams" in url:
                return {"errors": [], "response": teams_resp, "paging": {"current": 1, "total": 1}}, 0.05
            pg = int((params or {}).get("page", 1))
            return (page1 if pg == 1 else page2), 0.05

        with patch.object(mod, "get_json", fake_get_json):
            results = p.player_goal_stats("Mexico", 2025)

        names = {r["player"] for r in results}
        assert "H. Lozano" in names
        assert "R. Jimenez" in names
        assert "A. Guardado" in names   # only on page 2

    def test_cache_hit_does_not_refetch(self, tmp_path):
        """A second call for the same team/season must not call get_json again."""
        page1 = _load("players_team_season_page1.json")
        page1_single = page1.copy()
        page1_single["paging"] = {"current": 1, "total": 1}
        teams_resp = _load("teams_name_mexico.json")["response"]

        import wc26.providers.apifootball as mod
        from unittest.mock import patch

        call_count = 0

        def counting_get_json(url, params=None, headers=None, timeout=10.0):
            nonlocal call_count
            call_count += 1
            if "teams" in url:
                return {"errors": [], "response": teams_resp, "paging": {"current": 1, "total": 1}}, 0.05
            return page1_single, 0.05

        p = _provider(tmp_path)
        with patch.object(mod, "get_json", counting_get_json):
            p.player_goal_stats("Mexico", 2025)
            first_count = call_count
            p.player_goal_stats("Mexico", 2025)
            second_count = call_count

        # Second call should not increase the counter beyond teams+page calls.
        assert second_count == first_count


# ---------------------------------------------------------------------------
# fixture_statistics — type mapping and None → 0
# ---------------------------------------------------------------------------

class TestFixtureStatistics:
    def test_type_mapping_and_none_coercion(self, tmp_path):
        payload = _load("fixture_statistics_1035817.json")
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=payload["response"])

        stats = p.fixture_statistics(1035817)

        # Argentina has null Corner Kicks → should be 0
        assert stats["Argentina"]["corners"] == 0
        assert stats["Argentina"]["shots_on_goal"] == 3
        assert stats["Argentina"]["shots_total"] == 10
        assert stats["Argentina"]["fouls"] == 9

        # Mexico values are all non-null
        assert stats["Mexico"]["corners"] == 3
        assert stats["Mexico"]["shots_on_goal"] == 2
        assert stats["Mexico"]["shots_total"] == 6
        assert stats["Mexico"]["fouls"] == 13

    def test_full_fixture_1035816(self, tmp_path):
        payload = _load("fixture_statistics_1035816.json")
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=payload["response"])

        stats = p.fixture_statistics(1035816)
        assert set(stats["Mexico"].keys()) == {"corners", "shots_on_goal", "shots_total", "fouls"}
        assert stats["Mexico"]["corners"] == 7
        assert stats["Brazil"]["corners"] == 5

    def test_immutable_cache_hit_skips_get(self, tmp_path):
        payload = _load("fixture_statistics_1035816.json")
        p = _provider(tmp_path)
        call_count = 0

        def counting_get(path, **params):
            nonlocal call_count
            call_count += 1
            return payload["response"]

        p._get = counting_get
        p.fixture_statistics(1035816)   # miss
        p.fixture_statistics(1035816)   # hit
        assert call_count == 1


# ---------------------------------------------------------------------------
# _get_cached — cache mechanics
# ---------------------------------------------------------------------------

class TestGetCached:
    def test_miss_calls_get(self, tmp_path):
        p = _provider(tmp_path)
        call_count = 0

        def counting_get(path, **params):
            nonlocal call_count
            call_count += 1
            return [{"id": 1}]

        p._get = counting_get
        result = p._get_cached("/teams", None, name="Mexico")
        assert result == [{"id": 1}]
        assert call_count == 1

    def test_hit_does_not_call_get(self, tmp_path):
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=[{"id": 1}])
        p._get_cached("/teams", None, name="Mexico")   # populate cache
        p._get = MagicMock(return_value=[{"id": 999}])  # would return different data
        result = p._get_cached("/teams", None, name="Mexico")  # should use cache
        assert result == [{"id": 1}]
        p._get.assert_not_called()

    def test_ttl_expiry_triggers_refetch(self, tmp_path):
        p = _provider(tmp_path)
        old_data = [{"id": 1}]
        new_data = [{"id": 2}]

        p._get = MagicMock(return_value=old_data)
        p._get_cached("/players", ttl_seconds=1, team=16, season=2025)

        # Manually backdate the cache entry
        cache_file = p._cache_key("/players", {"team": "16", "season": "2025"})
        cached = json.loads(cache_file.read_text())
        cached["_written_at"] = time.time() - 10   # 10 s ago → expired for ttl=1
        cache_file.write_text(json.dumps(cached))

        p._get = MagicMock(return_value=new_data)
        result = p._get_cached("/players", ttl_seconds=1, team=16, season=2025)
        assert result == new_data
        p._get.assert_called_once()

    def test_immutable_ttl_never_expires(self, tmp_path):
        p = _provider(tmp_path)
        p._get = MagicMock(return_value=[{"id": 42}])
        p._get_cached("/fixtures/statistics", None, fixture=99999)

        # Backdate the cache entry far into the past
        cache_file = p._cache_key("/fixtures/statistics", {"fixture": "99999"})
        cached = json.loads(cache_file.read_text())
        cached["_written_at"] = 0   # epoch
        cache_file.write_text(json.dumps(cached))

        p._get = MagicMock(return_value=[{"id": 999}])
        result = p._get_cached("/fixtures/statistics", None, fixture=99999)
        assert result == [{"id": 42}]   # still the old value
        p._get.assert_not_called()


# ---------------------------------------------------------------------------
# team_stat_records — both sides emitted
# ---------------------------------------------------------------------------

class TestTeamStatRecords:
    def test_both_sides_emitted(self, tmp_path):
        """Each finished fixture must produce records for BOTH home and away."""
        fx_payload = _load("fixtures_team_last2.json")
        stats1 = _load("fixture_statistics_1035816.json")
        stats2 = _load("fixture_statistics_1035817.json")
        teams_resp = _load("teams_name_mexico.json")["response"]

        p = _provider(tmp_path)

        def fake_get(path, **params):
            if path == "/teams":
                return teams_resp
            if path == "/fixtures":
                return fx_payload["response"]
            fid = int(params.get("fixture", 0))
            if fid == 1035816:
                return stats1["response"]
            if fid == 1035817:
                return stats2["response"]
            return []

        p._get = MagicMock(side_effect=fake_get)
        records = p.team_stat_records("Mexico", last_n=2, stat="corners")

        # 2 fixtures × 2 sides = 4 records
        assert len(records) == 4
        teams_in_records = {r["team"] for r in records}
        opponents_in_records = {r["opponent"] for r in records}
        assert "Mexico" in teams_in_records
        assert "Brazil" in teams_in_records
        assert "Argentina" in teams_in_records

    def test_record_structure(self, tmp_path):
        """Every record must have team, opponent, value keys."""
        fx_payload = _load("fixtures_team_last2.json")
        stats1 = _load("fixture_statistics_1035816.json")
        stats2 = _load("fixture_statistics_1035817.json")
        teams_resp = _load("teams_name_mexico.json")["response"]

        p = _provider(tmp_path)

        def fake_get(path, **params):
            if path == "/teams":
                return teams_resp
            if path == "/fixtures":
                return fx_payload["response"]
            fid = int(params.get("fixture", 0))
            if fid == 1035816:
                return stats1["response"]
            return stats2["response"]

        p._get = MagicMock(side_effect=fake_get)
        records = p.team_stat_records("Mexico", last_n=2, stat="corners")

        for r in records:
            assert set(r.keys()) >= {"team", "opponent", "value"}
            assert isinstance(r["value"], (int, float))

    def test_stat_corners_values_correct(self, tmp_path):
        """Corner values must match fixture_statistics output."""
        fx_payload = _load("fixtures_team_last2.json")
        stats1 = _load("fixture_statistics_1035816.json")
        teams_resp = _load("teams_name_mexico.json")["response"]

        # Only use fixture 1035816 for this test (single fixture)
        single_fx = fx_payload.copy()
        single_fx["response"] = [fx_payload["response"][0]]

        p = _provider(tmp_path)

        def fake_get(path, **params):
            if path == "/teams":
                return teams_resp
            if path == "/fixtures":
                return single_fx["response"]
            return stats1["response"]

        p._get = MagicMock(side_effect=fake_get)
        records = p.team_stat_records("Mexico", last_n=1, stat="corners")

        by_team = {r["team"]: r["value"] for r in records}
        assert by_team["Mexico"] == 7
        assert by_team["Brazil"] == 5

    def test_fit_team_rates_compatible(self, tmp_path):
        """Records from team_stat_records must work with props.fit_team_rates."""
        from wc26.props import fit_team_rates

        fx_payload = _load("fixtures_team_last2.json")
        stats1 = _load("fixture_statistics_1035816.json")
        stats2 = _load("fixture_statistics_1035817.json")
        teams_resp = _load("teams_name_mexico.json")["response"]

        p = _provider(tmp_path)

        def fake_get(path, **params):
            if path == "/teams":
                return teams_resp
            if path == "/fixtures":
                return fx_payload["response"]
            fid = int(params.get("fixture", 0))
            if fid == 1035816:
                return stats1["response"]
            return stats2["response"]

        p._get = MagicMock(side_effect=fake_get)
        records = p.team_stat_records("Mexico", last_n=2, stat="corners")

        rates = fit_team_rates(records)
        assert "Mexico" in rates.for_
        assert rates.global_mean > 0
