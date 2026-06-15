"""Regression tests for prediction-engine robustness fixes."""

import numpy as np
import pandas as pd

from wc26.data import TrainingData, merge_upstream, training_data
from wc26.model import fit_model, try_predict_fixture


def _tiny_model():
    """Fit a Poisson model on three synthetic teams (A, B, C)."""
    th = np.array(["A", "B", "A", "C", "B", "C"] * 4)
    ta = np.array(["B", "A", "C", "A", "C", "B"] * 4)
    gh = np.array([1, 2, 0, 1, 3, 1] * 4)
    ga = np.array([0, 1, 1, 2, 0, 1] * 4)
    td = TrainingData(gh, ga, th, ta, np.ones(len(th)), np.zeros(len(th), dtype=int))
    return fit_model(td, kind="poisson")


def _played(tournaments):
    """Played matches all on one date (so time-decay weight is uniform)."""
    n = len(tournaments)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01"] * n),
            "home_team": [f"H{i}" for i in range(n)],
            "away_team": [f"A{i}" for i in range(n)],
            "home_score": [1] * n,
            "away_score": [0] * n,
            "tournament": tournaments,
            "neutral": [True] * n,
        }
    )


def test_nan_tournament_weighted_as_friendly():
    # xi=0 removes time decay, so weight == competitive weight alone.
    df = _played(["FIFA World Cup", "Friendly", np.nan])
    td = training_data(df, asof="2026-06-15", years=1.0, xi=0.0)
    assert td.weights[0] == 1.0  # competitive
    assert td.weights[1] == 0.6  # friendly
    assert td.weights[2] == 0.6  # NaN tournament must not count as competitive


def test_try_predict_unknown_team_returns_none():
    model = _tiny_model()
    assert try_predict_fixture(model, "Wakanda", "A", neutral=True) is None


def test_try_predict_known_teams_returns_grid():
    model = _tiny_model()
    grid = try_predict_fixture(model, "A", "B", neutral=True)
    assert grid is not None
    assert grid.home_goal_expectation > 0


def _results(scores):
    """One-row-per-match results frame; `scores` is a list of (h, a) or None."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-14", "2026-06-20"][: len(scores)]),
            "home_team": ["Spain", "Brazil"][: len(scores)],
            "away_team": ["Japan", "Peru"][: len(scores)],
            "home_score": [s[0] if s else np.nan for s in scores],
            "away_score": [s[1] if s else np.nan for s in scores],
        }
    )


def test_merge_upstream_preserves_backfilled_score():
    old = _results([(3, 1), None])          # Spain 3-1 backfilled
    new = _results([None, None])            # upstream hasn't caught up yet
    merged = merge_upstream(old, new)
    row = merged[merged["home_team"] == "Spain"].iloc[0]
    assert row["home_score"] == 3 and row["away_score"] == 1


def test_merge_upstream_is_authoritative_when_it_has_a_score():
    old = _results([(3, 1), None])          # local (possibly wrong) backfill
    new = _results([(3, 2), None])          # upstream now has the real final
    merged = merge_upstream(old, new)
    row = merged[merged["home_team"] == "Spain"].iloc[0]
    assert row["home_score"] == 3 and row["away_score"] == 2  # upstream wins
