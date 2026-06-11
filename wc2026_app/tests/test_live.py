import numpy as np
import pytest

from wc26.live import live_grid, remaining_lambdas


def test_grid_normalized():
    g = live_grid(1.6, 1.0, minute=60, score_home=1, score_away=0)
    assert g.grid.sum() == pytest.approx(1.0, abs=1e-6)


def test_late_lead_locks_result():
    g = live_grid(1.6, 1.0, minute=89, score_home=2, score_away=0)
    assert g.home_win > 0.95


def test_impossible_scores_have_zero_probability():
    g = live_grid(1.6, 1.0, minute=60, score_home=2, score_away=1)
    # final score can't be below current score
    assert g.exact_score(1, 0) == 0.0
    assert g.exact_score(2, 0) == 0.0
    assert g.exact_score(2, 1) > 0


def test_red_card_shifts_probabilities():
    base = live_grid(1.5, 1.5, minute=45, score_home=0, score_away=0)
    red = live_grid(1.5, 1.5, minute=45, score_home=0, score_away=0, red_home=1)
    assert red.home_win < base.home_win
    assert red.away_win > base.away_win


def test_remaining_lambdas_decay_with_time():
    lh_45, _ = remaining_lambdas(1.6, 1.0, minute=45)
    lh_80, _ = remaining_lambdas(1.6, 1.0, minute=80)
    assert lh_80 < lh_45 < 1.6


def test_full_time_grid_is_current_score():
    g = live_grid(1.6, 1.0, minute=90, score_home=1, score_away=1)
    assert g.exact_score(1, 1) == pytest.approx(1.0, abs=1e-9)
    assert g.draw == pytest.approx(1.0, abs=1e-9)


def test_expectations_consistent():
    g = live_grid(2.0, 1.0, minute=45, score_home=1, score_away=0)
    goals = np.arange(g.grid.shape[0])
    eh = (g.home_goal_distribution() * goals).sum()
    assert eh == pytest.approx(g.home_goal_expectation, rel=0.05)
