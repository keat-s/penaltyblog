"""Pure math for prop markets: anytime scorer, corners, shots on target.

Anytime scorer is Poisson thinning of the TEAM goal model: if the team
scores at rate lambda and a player takes a fixed `share` of those goals,
P(player scores >= 1) = 1 - exp(-lambda * share). Shares come from player
goal counts (Laplace-smoothed) and are the weakest input — international
scoring data is thin, and role/lineup changes are not modelled.

The count model (corners / shots on target, one generic implementation)
fits per-team FOR and AGAINST means shrunk toward the global mean with
weight n / (n + k) (empirical-Bayes style); quality depends entirely on
how many finished-fixture statistics have been collected, so sample
counts are exposed for thin-data warnings.

Honest framing: prop markets carry higher bookmaker margins and lower
limits than main markets, and our research base contains zero verified
evidence of exploitable inefficiency in them. Treat all outputs as fair
prices under stated assumptions, not as proven edges.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import poisson

from penaltyblog.models import FootballProbabilityGrid


def goal_shares(
    player_goals: dict[str, float], smoothing: float = 1.0
) -> dict[str, float]:
    """Laplace-smoothed normalized goal shares: (g_i + s) / (sum_g + s * n).

    Smoothing pulls shares toward uniform, so zero-goal players keep a
    nonzero share and thin samples are not taken at face value.
    """
    if not player_goals:
        return {}
    n = len(player_goals)
    total = sum(player_goals.values()) + smoothing * n
    return {p: (g + smoothing) / total for p, g in player_goals.items()}


def scorer_prob(team_lambda: float, share: float) -> float:
    """P(player scores >= 1) under Poisson thinning: 1 - exp(-lambda * share)."""
    return 1.0 - math.exp(-team_lambda * share)


def scorer_table(
    team_lambda: float,
    player_goals: dict[str, float],
    smoothing: float = 1.0,
) -> list[dict]:
    """Per-player anytime-scorer prices, sorted by p_score descending.

    Each row: {player, goals, share, p_score, fair_odds}.
    """
    shares = goal_shares(player_goals, smoothing=smoothing)
    rows = []
    for player, share in shares.items():
        p = scorer_prob(team_lambda, share)
        rows.append(
            {
                "player": player,
                "goals": player_goals[player],
                "share": share,
                "p_score": p,
                "fair_odds": 1.0 / p if p > 0 else math.inf,
            }
        )
    rows.sort(key=lambda r: r["p_score"], reverse=True)
    return rows


@dataclass
class TeamRates:
    """Shrunk per-team FOR/AGAINST means for one count stat (corners, SoT...).

    `counts` holds the number of FOR-side records per team — the sample
    size behind the estimate, so callers can flag thin data.
    """

    for_: dict[str, float] = field(default_factory=dict)
    against_: dict[str, float] = field(default_factory=dict)
    global_mean: float = 0.0
    counts: dict[str, int] = field(default_factory=dict)


def fit_team_rates(records: list[dict], k: float = 5.0) -> TeamRates:
    """Fit shrunk per-team rates from finished-match records.

    Each record is {team, opponent, value}: `value` is what `team`
    produced in that match. A record is a FOR-observation for `team` and
    an AGAINST-observation for `opponent`. Per-team means are shrunk
    toward the global mean with weight n / (n + k): small samples shrink
    harder than large ones.
    """
    if not records:
        return TeamRates()

    values = [float(r["value"]) for r in records]
    global_mean = float(np.mean(values))

    for_obs: dict[str, list[float]] = {}
    against_obs: dict[str, list[float]] = {}
    for r in records:
        for_obs.setdefault(r["team"], []).append(float(r["value"]))
        against_obs.setdefault(r["opponent"], []).append(float(r["value"]))

    def shrink(obs: list[float]) -> float:
        n = len(obs)
        w = n / (n + k)
        return w * float(np.mean(obs)) + (1.0 - w) * global_mean

    return TeamRates(
        for_={t: shrink(obs) for t, obs in for_obs.items()},
        against_={t: shrink(obs) for t, obs in against_obs.items()},
        global_mean=global_mean,
        counts={t: len(obs) for t, obs in for_obs.items()},
    )


def predict_lambdas(rates: TeamRates, home: str, away: str) -> tuple[float, float]:
    """Multiplicative expected counts for a match.

    lambda_home = for[home] * against[away] / global_mean (mirrored for
    away). Unknown teams fall back to the global mean; check
    `rates.counts` for thin-data flags.
    """
    g = rates.global_mean
    if g <= 0:
        return 0.0, 0.0
    lam_home = rates.for_.get(home, g) * rates.against_.get(away, g) / g
    lam_away = rates.for_.get(away, g) * rates.against_.get(home, g) / g
    return lam_home, lam_away


def count_grid(
    lambda_home: float, lambda_away: float, max_count: int = 30
) -> FootballProbabilityGrid:
    """Independent Poisson outer-product grid over a count stat.

    Reuses FootballProbabilityGrid so `totals(line)` gives push-aware
    over/under for integer lines and per-team distributions come free.
    """
    counts = np.arange(max_count + 1)
    matrix = np.outer(
        poisson.pmf(counts, lambda_home), poisson.pmf(counts, lambda_away)
    )
    return FootballProbabilityGrid(
        goal_matrix=matrix,
        home_goal_expectation=lambda_home,
        away_goal_expectation=lambda_away,
        normalize=True,
    )


def over_under(grid: FootballProbabilityGrid, line: float) -> dict:
    """Push-aware over/under prices for a totals line.

    Fair odds exclude the push (price of the win, with push refunded).
    """
    under, push, over = grid.totals(line)
    return {
        "over": over,
        "under": under,
        "push": push,
        "fair_over": 1.0 / over if over > 0 else math.inf,
        "fair_under": 1.0 / under if under > 0 else math.inf,
    }


def ev(prob: float, odds: float, push: float = 0.0) -> float:
    """Expected value per unit staked: prob * odds + push - 1.

    `push` is the probability of a stake refund (e.g. integer-line totals).
    """
    return prob * odds + push - 1.0
