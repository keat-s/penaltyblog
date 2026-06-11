"""In-play conditional pricing.

Re-prices a match mid-game without refitting: take the pre-match goal
expectations, scale by remaining time and live state (red cards), build the
remaining-goals Poisson grid, then shift it by the current score. The result
is a normal FootballProbabilityGrid, so every market reprices for free.

Parameter provenance (deep-research, .omc/research/wc2026-deep-research.md):
- Goal intensity rises roughly linearly through a match (Dixon-Robinson;
  drift ~ +0.55 over 90 minutes).
- Red cards are asymmetric: the sanctioned team's scoring rate falls ~17-42%,
  the opponent's rises ~60-69% (Titman; replicated on World Cup matches
  1998-2014). Yellow cards carry no signal worth modelling.
These defaults are literature-derived but not backtested in this app —
in-play output is the most speculative module; no verified evidence shows
realized in-play ROI net of margin.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import poisson

from penaltyblog.models import FootballProbabilityGrid

# lambda(t) proportional to 1 + GOAL_INTENSITY_DRIFT * t / T
GOAL_INTENSITY_DRIFT = 0.55

# Red-card multipliers on scoring intensity (sanctioned team / opponent).
RED_CARD_OWN = 0.70
RED_CARD_OPP = 1.65


def remaining_fraction(
    minute: float,
    match_minutes: float = 90.0,
    drift: float = GOAL_INTENSITY_DRIFT,
) -> float:
    """Fraction of total expected goals still to come after `minute`.

    Integrates the linearly rising intensity lambda(t) ~ 1 + drift*t/T over
    the remaining time, normalized by the full-match integral.
    """
    T = match_minutes
    m = min(max(minute, 0.0), T)
    total = T * (1.0 + drift / 2.0)
    remaining = (T - m) + drift * (T * T - m * m) / (2.0 * T)
    return remaining / total


def remaining_lambdas(
    lambda_home: float,
    lambda_away: float,
    minute: float,
    red_home: int = 0,
    red_away: int = 0,
    match_minutes: float = 90.0,
    red_card_own: float = RED_CARD_OWN,
    red_card_opp: float = RED_CARD_OPP,
    drift: float = GOAL_INTENSITY_DRIFT,
) -> tuple[float, float]:
    """Expected remaining goals for each side given the live state."""
    frac = remaining_fraction(minute, match_minutes, drift)
    lh = lambda_home * frac * (red_card_own**red_home) * (red_card_opp**red_away)
    la = lambda_away * frac * (red_card_own**red_away) * (red_card_opp**red_home)
    return lh, la


def live_grid(
    lambda_home: float,
    lambda_away: float,
    minute: float,
    score_home: int,
    score_away: int,
    red_home: int = 0,
    red_away: int = 0,
    match_minutes: float = 90.0,
    max_goals: int = 15,
    **kwargs,
) -> FootballProbabilityGrid:
    """Conditional scoreline grid given current score, minute and red cards.

    `lambda_home`/`lambda_away` are the pre-match goal expectations (e.g.
    `grid.home_goal_expectation` from a fitted model's prediction).
    """
    lh, la = remaining_lambdas(
        lambda_home, lambda_away, minute, red_home, red_away, match_minutes, **kwargs
    )

    goals = np.arange(max_goals + 1)
    rem = np.outer(poisson.pmf(goals, lh), poisson.pmf(goals, la))

    full = np.zeros((score_home + max_goals + 1, score_away + max_goals + 1))
    full[score_home:, score_away:] = rem

    return FootballProbabilityGrid(
        goal_matrix=full,
        home_goal_expectation=score_home + lh,
        away_goal_expectation=score_away + la,
        normalize=True,
    )


def live_grid_from_model(
    model,
    home_team: str,
    away_team: str,
    neutral: bool = True,
    **state,
) -> FootballProbabilityGrid:
    """Convenience: pre-match prediction -> live conditional grid."""
    pre = model.predict(home_team, away_team, neutral_venue=bool(neutral))
    return live_grid(
        pre.home_goal_expectation,
        pre.away_goal_expectation,
        **state,
    )
