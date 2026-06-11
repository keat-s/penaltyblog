"""Tests for wc26.slate — UI-agnostic data layer."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from penaltyblog.models import FootballProbabilityGrid

from wc26.providers.base import LiveState, OddsQuote
from wc26.slate import fixture_rows, live_snapshot, prematch_slate


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _make_grid(lambda_home: float = 1.6, lambda_away: float = 1.0) -> FootballProbabilityGrid:
    """Synthetic independent-Poisson grid, same construction as conftest."""
    goals = np.arange(16)
    matrix = np.outer(poisson.pmf(goals, lambda_home), poisson.pmf(goals, lambda_away))
    return FootballProbabilityGrid(
        goal_matrix=matrix,
        home_goal_expectation=lambda_home,
        away_goal_expectation=lambda_away,
        normalize=True,
    )


class _StubModel:
    """Model stub: returns a synthetic grid regardless of team names."""

    def predict(self, home: str, away: str, *, neutral_venue: bool = True):
        # Use slightly different lambdas so home/away have distinct probs
        return _make_grid(1.6, 1.0)


class _FakeProvider:
    """Provider stub returning canned live state and odds quotes."""

    def __init__(self, *, live: bool = True):
        self._live = live
        self.fetched_at = time.time()

    def live_state(self, home: str, away: str):
        if not self._live:
            return None
        return LiveState(
            home=home,
            away=away,
            minute=62.0,
            score_home=1,
            score_away=0,
            red_home=0,
            red_away=1,
            status="live",
            fetched_at=self.fetched_at,
        )

    def odds(self, home: str, away: str):
        # Complete 1x2 set with enough EV to generate at least one rec
        # Model probs ≈ home 0.51, draw 0.25, away 0.24 — inflate home odds
        return [
            OddsQuote(home=home, away=away, market="1x2", outcome="home", odds=2.20, bookmaker="pinnacle"),
            OddsQuote(home=home, away=away, market="1x2", outcome="draw", odds=3.40, bookmaker="pinnacle"),
            OddsQuote(home=home, away=away, market="1x2", outcome="away", odds=4.00, bookmaker="pinnacle"),
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def model():
    return _StubModel()


@pytest.fixture
def fixtures_df():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-15", "2026-06-16"]),
            "home_team": ["Brazil", "Germany"],
            "away_team": ["Argentina", "France"],
            "neutral": [True, False],
            "city": ["New York", "Dallas"],
            "country": ["United States", "United States"],
        }
    )


@pytest.fixture
def odds_rows_by_match():
    """Odds for both fixtures with obviously +EV prices to guarantee recs."""
    def _rows(home, away):
        return [
            {"market": "1x2", "outcome": "home", "odds": 2.20, "bookmaker": "pinnacle"},
            {"market": "1x2", "outcome": "draw", "odds": 3.40, "bookmaker": "pinnacle"},
            {"market": "1x2", "outcome": "away", "odds": 4.00, "bookmaker": "pinnacle"},
        ]

    return {
        "Brazil v Argentina": _rows("Brazil", "Argentina"),
        "Germany v France": _rows("Germany", "France"),
    }


# ---------------------------------------------------------------------------
# fixture_rows tests
# ---------------------------------------------------------------------------


class TestFixtureRows:
    def test_returns_one_dict_per_row(self, model, fixtures_df):
        rows = fixture_rows(model, fixtures_df)
        assert len(rows) == 2

    def test_required_keys_present(self, model, fixtures_df):
        expected = {"date", "home", "away", "neutral", "p_home", "p_draw", "p_away", "p_over25", "p_btts"}
        for row in fixture_rows(model, fixtures_df):
            assert set(row.keys()) == expected

    def test_date_is_iso_string(self, model, fixtures_df):
        rows = fixture_rows(model, fixtures_df)
        assert rows[0]["date"] == "2026-06-15"
        assert rows[1]["date"] == "2026-06-16"

    def test_team_names_preserved(self, model, fixtures_df):
        rows = fixture_rows(model, fixtures_df)
        assert rows[0]["home"] == "Brazil"
        assert rows[0]["away"] == "Argentina"
        assert rows[1]["home"] == "Germany"

    def test_neutral_flag_preserved(self, model, fixtures_df):
        rows = fixture_rows(model, fixtures_df)
        assert rows[0]["neutral"] is True
        assert rows[1]["neutral"] is False

    def test_probabilities_in_unit_interval(self, model, fixtures_df):
        for row in fixture_rows(model, fixtures_df):
            for key in ("p_home", "p_draw", "p_away", "p_over25", "p_btts"):
                assert 0.0 < row[key] < 1.0, f"{key}={row[key]} out of (0,1)"

    def test_1x2_sums_to_one(self, model, fixtures_df):
        for row in fixture_rows(model, fixtures_df):
            total = row["p_home"] + row["p_draw"] + row["p_away"]
            assert total == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# prematch_slate tests
# ---------------------------------------------------------------------------


class TestPrematchSlate:
    def _run(self, model, fixtures_df, odds_rows_by_match, **kw):
        params = dict(bankroll=1000.0, kelly_fraction=0.25, min_ev=0.02, require_market_edge=False)
        params.update(kw)
        return prematch_slate(model, fixtures_df, odds_rows_by_match, **params)

    def test_returns_expected_top_level_keys(self, model, fixtures_df, odds_rows_by_match):
        result = self._run(model, fixtures_df, odds_rows_by_match)
        assert set(result.keys()) == {"recommendations", "total_stake", "n_candidates", "warnings"}

    def test_warnings_empty_when_all_matches_found(self, model, fixtures_df, odds_rows_by_match):
        result = self._run(model, fixtures_df, odds_rows_by_match)
        assert result["warnings"] == []

    def test_rec_dict_keys(self, model, fixtures_df, odds_rows_by_match):
        expected_keys = {
            "match", "market", "line", "outcome", "odds",
            "model_p", "fair_p", "ev", "tier", "stake", "stake_fraction",
        }
        result = self._run(model, fixtures_df, odds_rows_by_match)
        for rec in result["recommendations"]:
            assert set(rec.keys()) == expected_keys

    def test_positive_total_stake_for_ev_positive_odds(self, model, fixtures_df, odds_rows_by_match):
        # Model home_win ≈ 0.51; home @ 2.20 → EV ≈ 0.51*2.20 - 1 ≈ +0.12
        result = self._run(model, fixtures_df, odds_rows_by_match)
        assert result["total_stake"] > 0.0

    def test_n_candidates_counts_all_odds_rows(self, model, fixtures_df, odds_rows_by_match):
        # 2 matches × 3 outcome rows each = 6 candidates
        result = self._run(model, fixtures_df, odds_rows_by_match)
        assert result["n_candidates"] == 6

    def test_warning_when_match_label_missing_from_fixtures(self, model, fixtures_df):
        orphan_odds = {
            "Brazil v Argentina": [
                {"market": "1x2", "outcome": "home", "odds": 2.20, "bookmaker": "b"},
                {"market": "1x2", "outcome": "draw", "odds": 3.40, "bookmaker": "b"},
                {"market": "1x2", "outcome": "away", "odds": 4.00, "bookmaker": "b"},
            ],
            "Unknown v Team": [
                {"market": "1x2", "outcome": "home", "odds": 2.00, "bookmaker": "b"},
            ],
        }
        result = prematch_slate(
            model, fixtures_df, orphan_odds,
            bankroll=1000.0, kelly_fraction=0.25, min_ev=0.02,
            require_market_edge=False,
        )
        assert any("Unknown v Team" in w for w in result["warnings"])

    def test_total_stake_matches_sum_of_rec_stakes(self, model, fixtures_df, odds_rows_by_match):
        result = self._run(model, fixtures_df, odds_rows_by_match)
        expected = sum(r["stake"] for r in result["recommendations"])
        assert result["total_stake"] == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# live_snapshot tests
# ---------------------------------------------------------------------------


class TestLiveSnapshot:
    def _run(self, model, provider, home="Brazil", away="Argentina", **kw):
        params = dict(neutral=True, bankroll=1000.0, kelly_fraction=0.25, min_ev=0.02)
        params.update(kw)
        return live_snapshot(model, provider, home, away, **params)

    def test_not_live_path(self, model):
        provider = _FakeProvider(live=False)
        result = self._run(model, provider)
        assert result == {"status": "not_live"}

    def test_live_path_top_level_keys(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        expected_keys = {
            "status", "minute", "score", "reds",
            "p_home", "p_draw", "p_away", "p_over25",
            "recommendations", "fetched_at",
        }
        assert set(result.keys()) == expected_keys

    def test_live_path_status_and_minute(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        assert result["status"] == "live"
        assert result["minute"] == pytest.approx(62.0)

    def test_live_path_score_from_fake_state(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        assert result["score"] == [1, 0]

    def test_live_path_reds_from_fake_state(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        assert result["reds"] == [0, 1]

    def test_live_path_probabilities_in_unit_interval(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        for key in ("p_home", "p_draw", "p_away", "p_over25"):
            assert 0.0 < result[key] < 1.0, f"{key}={result[key]} out of (0,1)"

    def test_live_path_1x2_sums_to_one(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        total = result["p_home"] + result["p_draw"] + result["p_away"]
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_live_path_recs_is_list(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        assert isinstance(result["recommendations"], list)

    def test_live_path_rec_dict_keys(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        expected_keys = {
            "match", "market", "line", "outcome", "odds",
            "model_p", "fair_p", "ev", "tier", "stake", "stake_fraction",
        }
        for rec in result["recommendations"]:
            assert set(rec.keys()) == expected_keys

    def test_live_path_fetched_at_from_state(self, model):
        provider = _FakeProvider(live=True)
        result = self._run(model, provider)
        assert result["fetched_at"] == pytest.approx(provider.fetched_at, abs=1.0)
