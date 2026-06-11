import pytest

from wc26.edge import Candidate, build_candidates, devig
from wc26.markets import model_probs


def test_1x2_probs_sum_to_one(grid):
    total = sum(model_probs(grid, "1x2", o)[0] for o in ("home", "draw", "away"))
    assert total == pytest.approx(1.0, abs=1e-6)


def test_ou_half_line_has_no_push(grid):
    over_w, over_p = model_probs(grid, "ou", "over", 2.5)
    under_w, under_p = model_probs(grid, "ou", "under", 2.5)
    assert over_p == under_p == 0.0
    assert over_w + under_w == pytest.approx(1.0, abs=1e-6)


def test_dnb_pushes_on_draw(grid):
    p_win, p_push = model_probs(grid, "dnb", "home", None)
    assert p_win == pytest.approx(grid.home_win)
    assert p_push == pytest.approx(grid.draw)


def test_ev_with_push():
    c = Candidate("m", "dnb", "home", odds=2.0, p_win=0.45, p_push=0.25)
    # EV = 0.45*2.0 + 0.25 - 1 = 0.15; conditional win prob = 0.45/0.75 = 0.6
    assert c.ev == pytest.approx(0.15)
    assert c.p_eff == pytest.approx(0.6)


def test_devig_sums_to_one():
    probs = devig([2.1, 3.4, 3.8])
    assert sum(probs) == pytest.approx(1.0, abs=1e-6)
    assert all(0 < p < 1 for p in probs)


def test_line_shopping_takes_best_price(grid):
    rows = [
        {"market": "1x2", "outcome": "home", "odds": 2.05, "bookmaker": "pinnacle"},
        {"market": "1x2", "outcome": "home", "odds": 2.20, "bookmaker": "bet365"},
        {"market": "1x2", "outcome": "draw", "odds": 3.40, "bookmaker": "pinnacle"},
        {"market": "1x2", "outcome": "away", "odds": 3.80, "bookmaker": "pinnacle"},
    ]
    cands = build_candidates(grid, "A v B", rows)
    home = next(c for c in cands if c.outcome == "home")
    assert home.odds == 2.20  # best price across books
    # fair prob anchored to pinnacle's complete set, not the mixed best prices
    fair = devig([2.05, 3.40, 3.80])
    assert home.fair_prob == pytest.approx(fair[0])


def test_longshot_guardrail():
    from wc26.recommend import select_diverse

    longshot = Candidate("m", "1x2", "away", odds=15.0, p_win=0.08)  # ev +0.2
    assert longshot.ev > 0.02
    assert select_diverse([longshot]) == []
    assert select_diverse([longshot], min_prob=0.0) == [longshot]


def test_build_candidates_devigs_complete_markets(grid):
    rows = [
        {"market": "1x2", "outcome": "home", "odds": 2.1},
        {"market": "1x2", "outcome": "draw", "odds": 3.4},
        {"market": "1x2", "outcome": "away", "odds": 3.8},
        {"market": "ou", "outcome": "over", "line": 2.5, "odds": 2.0},
    ]
    cands = build_candidates(grid, "A v B", rows)
    by_market = {(c.market, c.outcome): c for c in cands}
    assert by_market[("1x2", "home")].fair_prob is not None
    # ou market incomplete (no under) -> no fair prob
    assert by_market[("ou", "over")].fair_prob is None
