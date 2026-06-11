import math

import pytest

from wc26.props import (
    TeamRates,
    count_grid,
    ev,
    fit_team_rates,
    goal_shares,
    over_under,
    predict_lambdas,
    scorer_prob,
    scorer_table,
)


def test_goal_shares_sum_to_one():
    shares = goal_shares({"A": 10, "B": 3, "C": 0})
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-12)


def test_goal_shares_smoothing_pulls_toward_uniform():
    goals = {"A": 10, "B": 0}
    raw = goal_shares(goals, smoothing=0.0)
    light = goal_shares(goals, smoothing=1.0)
    heavy = goal_shares(goals, smoothing=1000.0)
    assert raw["A"] == pytest.approx(1.0)
    # More smoothing -> top share closer to uniform 1/2.
    assert raw["A"] > light["A"] > heavy["A"] > 0.5
    # s=1000, n=2: (10+1000)/(10+2000) = 0.50249
    assert heavy["A"] == pytest.approx(1010.0 / 2010.0, abs=1e-12)
    assert heavy["A"] == pytest.approx(0.5, abs=0.01)


def test_goal_shares_zero_goal_player_nonzero():
    shares = goal_shares({"Striker": 12, "Defender": 0}, smoothing=1.0)
    assert shares["Defender"] > 0
    assert shares["Defender"] == pytest.approx(1.0 / 14.0)


def test_goal_shares_empty():
    assert goal_shares({}) == {}


def test_scorer_prob_closed_form_at_full_share():
    assert scorer_prob(1.5, 1.0) == pytest.approx(1.0 - math.exp(-1.5), abs=1e-15)


def test_scorer_prob_monotonic_in_share_and_lambda():
    probs_share = [scorer_prob(1.5, s) for s in (0.1, 0.2, 0.4, 0.8)]
    assert probs_share == sorted(probs_share)
    probs_lam = [scorer_prob(lam, 0.3) for lam in (0.5, 1.0, 2.0, 4.0)]
    assert probs_lam == sorted(probs_lam)
    assert scorer_prob(1.5, 0.0) == 0.0


def test_scorer_table_sorted_with_fair_odds():
    rows = scorer_table(1.8, {"A": 8, "B": 2, "C": 0})
    assert [r["player"] for r in rows] == ["A", "B", "C"]
    for r in rows:
        assert r["fair_odds"] == pytest.approx(1.0 / r["p_score"])
        assert r["p_score"] == pytest.approx(scorer_prob(1.8, r["share"]))
    # Zero-goal player still priced (smoothed share > 0).
    assert rows[-1]["p_score"] > 0


def _records(team, opponent, values):
    return [{"team": team, "opponent": opponent, "value": v} for v in values]


def test_fit_team_rates_shrinks_small_samples_harder():
    # Big team: 20 obs at 8; small team: 2 obs at 8; filler keeps the
    # global mean at 4 via a third pairing.
    records = (
        _records("BIG", "X", [8.0] * 20)
        + _records("SMALL", "X", [8.0] * 2)
        + _records("FILL", "X", [0.0] * 22)
    )
    rates = fit_team_rates(records, k=5.0)
    assert rates.global_mean == pytest.approx(4.0)
    # n/(n+k): BIG keeps 20/25 of its excess, SMALL only 2/7.
    assert rates.for_["BIG"] == pytest.approx(4.0 + (20 / 25) * 4.0)
    assert rates.for_["SMALL"] == pytest.approx(4.0 + (2 / 7) * 4.0)
    assert abs(rates.for_["SMALL"] - 4.0) < abs(rates.for_["BIG"] - 4.0)
    assert rates.counts == {"BIG": 20, "SMALL": 2, "FILL": 22}


def test_fit_team_rates_against_side():
    # X concedes everything in the test above; against_ should exist for X.
    records = _records("A", "X", [6.0, 6.0]) + _records("B", "Y", [2.0, 2.0])
    rates = fit_team_rates(records, k=2.0)
    assert rates.global_mean == pytest.approx(4.0)
    # X faced two 6s: shrunk toward 4 with weight 2/4.
    assert rates.against_["X"] == pytest.approx(0.5 * 6.0 + 0.5 * 4.0)
    assert "X" not in rates.for_


def test_fit_team_rates_empty():
    rates = fit_team_rates([])
    assert isinstance(rates, TeamRates)
    assert rates.global_mean == 0.0
    assert rates.counts == {}


def test_predict_lambdas_unknown_team_fallback():
    records = _records("A", "B", [5.0, 5.0]) + _records("B", "A", [3.0, 3.0])
    rates = fit_team_rates(records, k=5.0)
    lh, la = predict_lambdas(rates, "UNKNOWN1", "UNKNOWN2")
    assert lh == pytest.approx(rates.global_mean)
    assert la == pytest.approx(rates.global_mean)
    # Thin-data flag: unknown teams have no counts entry.
    assert "UNKNOWN1" not in rates.counts


def test_predict_lambdas_multiplicative():
    rates = TeamRates(
        for_={"H": 6.0, "A": 4.0},
        against_={"H": 5.0, "A": 10.0},
        global_mean=5.0,
        counts={"H": 10, "A": 10},
    )
    lh, la = predict_lambdas(rates, "H", "A")
    assert lh == pytest.approx(6.0 * 10.0 / 5.0)
    assert la == pytest.approx(4.0 * 5.0 / 5.0)


def test_count_grid_totals_sum_to_one_with_push_on_integer_line():
    grid = count_grid(5.2, 4.1, max_count=30)
    under, push, over = grid.totals(9.0)
    assert under + push + over == pytest.approx(1.0, abs=1e-9)
    assert push > 0  # integer line on a count market can push
    # Half-line never pushes.
    u2, p2, o2 = grid.totals(9.5)
    assert p2 == 0.0
    assert u2 + o2 == pytest.approx(1.0, abs=1e-9)
    assert grid.home_goal_expectation == pytest.approx(5.2)


def test_over_under_dict():
    grid = count_grid(5.0, 4.0)
    ou = over_under(grid, 9.0)
    assert ou["over"] + ou["under"] + ou["push"] == pytest.approx(1.0, abs=1e-9)
    assert ou["fair_over"] == pytest.approx(1.0 / ou["over"])
    assert ou["fair_under"] == pytest.approx(1.0 / ou["under"])
    assert ou["push"] > 0


def test_ev_signs():
    assert ev(0.5, 2.0) == pytest.approx(0.0)  # fair price
    assert ev(0.5, 2.2) > 0  # value
    assert ev(0.5, 1.8) < 0  # juice
    # Push refund: win 40% at 2.0, push 20% -> EV exactly zero.
    assert ev(0.4, 2.0, push=0.2) == pytest.approx(0.0)
    # Same win prob/odds without the refund is negative.
    assert ev(0.4, 2.0) < 0
