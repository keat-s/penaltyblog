"""Knockout-round extension: extra time and penalties.

Dixon-Coles outputs are 90-minute probabilities. For knockout ties the
question is "who advances", which needs an explicit extra-time and penalty
model on top of the 90' grid:

    P(advance) = P(win 90') + P(draw 90') * [P(win ET) + P(draw ET) * P(win pens)]

Modelling choices (explicit, unvalidated — research found no verified
evidence on ET/penalty pricing, so this layer makes its assumptions
configurable rather than claiming accuracy):
- ET is a 30-minute mini-match with independent Poisson goals at the
  pre-match scoring rates scaled by 30/90, times `et_factor` (default 1.0).
  Conditioning on "90' was a draw" is ignored (drawn games skew toward
  closely-matched or low-scoring states; if anything ET rates run lower).
- Penalties default to a coin flip (`pens_home=0.5`); plug in a shootout
  prior if you have one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson

ET_MINUTES = 30.0
REGULATION_MINUTES = 90.0


@dataclass
class AdvanceProbs:
    win_90: float
    draw_90: float
    lose_90: float
    win_et: float  # conditional on 90' draw
    draw_et: float
    lose_et: float
    pens_home: float
    advance_home: float
    advance_away: float

    def fair_odds(self) -> tuple[float, float]:
        return 1.0 / self.advance_home, 1.0 / self.advance_away


def et_outcome_probs(
    lambda_home: float,
    lambda_away: float,
    et_factor: float = 1.0,
    max_goals: int = 10,
) -> tuple[float, float, float]:
    """(home win, draw, away win) for a 30-minute extra-time period."""
    scale = (ET_MINUTES / REGULATION_MINUTES) * et_factor
    goals = np.arange(max_goals + 1)
    matrix = np.outer(
        poisson.pmf(goals, lambda_home * scale), poisson.pmf(goals, lambda_away * scale)
    )
    matrix /= matrix.sum()
    i, j = np.indices(matrix.shape)
    return (
        float(matrix[i > j].sum()),
        float(matrix[i == j].sum()),
        float(matrix[i < j].sum()),
    )


def advance_probabilities(
    grid_90,
    et_factor: float = 1.0,
    pens_home: float = 0.5,
    max_goals: int = 10,
) -> AdvanceProbs:
    """Probability each side advances from a knockout tie.

    `grid_90` is the 90-minute FootballProbabilityGrid; its goal expectations
    seed the extra-time mini-match.
    """
    win_et, draw_et, lose_et = et_outcome_probs(
        grid_90.home_goal_expectation,
        grid_90.away_goal_expectation,
        et_factor=et_factor,
        max_goals=max_goals,
    )
    adv_home = grid_90.home_win + grid_90.draw * (win_et + draw_et * pens_home)
    adv_away = grid_90.away_win + grid_90.draw * (lose_et + draw_et * (1.0 - pens_home))
    return AdvanceProbs(
        win_90=grid_90.home_win,
        draw_90=grid_90.draw,
        lose_90=grid_90.away_win,
        win_et=win_et,
        draw_et=draw_et,
        lose_et=lose_et,
        pens_home=pens_home,
        advance_home=adv_home,
        advance_away=adv_away,
    )
