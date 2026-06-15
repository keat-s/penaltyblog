"""Shot-based expected-goals proxy.

Sportmonks publishes a real xG figure (the `xgfixture` include), but it is gated
behind a plan tier we don't have. As a fallback we approximate xG from the shot
breakdown that *is* available in match statistics, weighting each shot bucket by
a rough historical conversion rate.

The coefficients are deliberately simple and transparent — this is a proxy, not
a trained model. Tune `COEFFS` against finished matches (compare `xg` columns to
actual goals) if you want a tighter fit. Big chances are treated as a subset of
inside-box shots, so we count them once at the high rate and the *remaining*
inside-box shots at the lower rate to avoid double-counting.
"""

from __future__ import annotations

from typing import Dict, Tuple

# Rough per-shot conversion weights (xG contributed by one shot of each kind).
COEFFS = {
    "big_chance": 0.35,       # clear-cut chances convert ~a third of the time
    "inside_box": 0.10,       # other shots from inside the box
    "outside_box": 0.03,      # long-range efforts
}


def _f(d: Dict, key: str) -> float:
    try:
        return float(d.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def estimate_side_xg(stats: Dict) -> float:
    """xG proxy for one side from its shot counts.

    Expected keys (any missing default to 0): big_chances_created,
    shots_insidebox, shots_outsidebox.
    """
    big = _f(stats, "big_chances_created")
    inside = _f(stats, "shots_insidebox")
    outside = _f(stats, "shots_outsidebox")
    other_inside = max(inside - big, 0.0)  # big chances are inside-box already
    xg = (
        COEFFS["big_chance"] * big
        + COEFFS["inside_box"] * other_inside
        + COEFFS["outside_box"] * outside
    )
    return round(xg, 3)


def estimate_xg(home_stats: Dict, away_stats: Dict) -> Tuple[float, float]:
    """xG proxy for both sides; returns (xg_home, xg_away)."""
    return estimate_side_xg(home_stats), estimate_side_xg(away_stats)
