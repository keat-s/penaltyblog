"""Map (market, outcome, line) onto model probabilities from a scoreline grid.

Every market resolves to a (p_win, p_push) pair so downstream EV and Kelly
logic is uniform: EV = p_win * odds + p_push - 1 (push refunds the stake).
"""

from __future__ import annotations

from typing import Optional, Tuple

from penaltyblog.models import FootballProbabilityGrid

# Variance tier per market type, used for recommendation diversity buckets.
MARKET_TIERS = {
    "ah": "low",
    "dnb": "low",
    "dc": "low",
    "ou": "medium",
    "1x2": "medium",
    "btts": "medium",
    "exact": "high",
}


def model_probs(
    grid: FootballProbabilityGrid,
    market: str,
    outcome: str,
    line: Optional[float] = None,
) -> Tuple[float, float]:
    """Return (p_win, p_push) for a bet on `outcome` in `market`."""
    market = market.lower()
    outcome = str(outcome).lower()

    if market == "1x2":
        p = {"home": grid.home_win, "draw": grid.draw, "away": grid.away_win}[outcome]
        return p, 0.0

    if market == "ou":
        if line is None:
            raise ValueError("ou market requires a line")
        under, push, over = grid.totals(float(line))
        return (over, push) if outcome == "over" else (under, push)

    if market == "ah":
        if line is None:
            raise ValueError("ah market requires a line")
        probs = grid.asian_handicap_probs(outcome, float(line))
        return probs["win"], probs["push"]

    if market == "btts":
        p = grid.btts_yes if outcome == "yes" else grid.btts_no
        return p, 0.0

    if market == "dnb":
        # Raw (unconditional) probs: win outright, push on the draw.
        if outcome == "home":
            return grid.home_win, grid.draw
        return grid.away_win, grid.draw

    if market == "dc":
        p = {
            "1x": grid.double_chance_1x,
            "x2": grid.double_chance_x2,
            "12": grid.double_chance_12,
        }[outcome]
        return p, 0.0

    if market == "exact":
        h, a = (int(x) for x in outcome.split("-"))
        return grid.exact_score(h, a), 0.0

    raise ValueError(f"unknown market '{market}'")
