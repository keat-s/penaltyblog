"""UI-agnostic data layer for the WC2026 Streamlit dashboard.

Three entry points, all returning plain JSON-able dicts:
  - fixture_rows   : model predictions for a fixtures DataFrame
  - prematch_slate : pooled +EV recommendations across upcoming fixtures
  - live_snapshot  : in-play state + live recommendations for one match
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .edge import build_candidates
from .live import live_grid
from .recommend import Recommendation, recommend


def _rec_to_dict(r: Recommendation) -> Dict[str, Any]:
    """Flatten a Recommendation into the JSON-able dict the dashboard consumes."""
    return {
        "match": r.candidate.match,
        "market": r.candidate.market,
        "line": r.candidate.line,
        "outcome": r.candidate.outcome,
        "odds": r.candidate.odds,
        "model_p": r.candidate.p_win,
        "fair_p": r.candidate.fair_prob,
        "ev": r.candidate.ev,
        "tier": r.candidate.tier,
        "stake": r.stake,
        "stake_fraction": r.stake_fraction,
    }


# ---------------------------------------------------------------------------
# 1. fixture_rows
# ---------------------------------------------------------------------------


def fixture_rows(model, fixtures_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Predict every row of *fixtures_df* and return a list of result dicts.

    *fixtures_df* must have columns date, home_team, away_team and neutral
    (as produced by `wc26.data.fixtures`).

    Each dict has keys: date, home, away, neutral, p_home, p_draw, p_away,
    p_over25, p_btts.  Probabilities are floats in (0, 1).
    """
    rows = []
    for _, row in fixtures_df.iterrows():
        home = str(row["home_team"])
        away = str(row["away_team"])
        neutral = bool(row["neutral"])

        grid = model.predict(home, away, neutral_venue=neutral)
        _, _, over25 = grid.totals(2.5)

        rows.append(
            {
                "date": str(pd.Timestamp(row["date"]).date()),
                "home": home,
                "away": away,
                "neutral": neutral,
                "p_home": float(grid.home_win),
                "p_draw": float(grid.draw),
                "p_away": float(grid.away_win),
                "p_over25": float(over25),
                "p_btts": float(grid.btts_yes),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# 2. prematch_slate
# ---------------------------------------------------------------------------


def prematch_slate(
    model,
    fixtures_df: pd.DataFrame,
    odds_rows_by_match: Dict[str, List[Dict]],
    *,
    bankroll: float,
    kelly_fraction: float,
    min_ev: float,
    require_market_edge: bool = True,
) -> Dict[str, Any]:
    """Build a pooled recommendation slate across all upcoming fixtures.

    *odds_rows_by_match* maps "Home v Away" labels to lists of odds-row dicts
    ({market, outcome, odds, line?, bookmaker?}).

    Returns {"recommendations": [...], "total_stake": float,
             "n_candidates": int, "warnings": list[str]}.
    """
    # Build a fast lookup: label -> neutral flag
    label_to_neutral: Dict[str, bool] = {}
    for _, row in fixtures_df.iterrows():
        label = f"{row['home_team']} v {row['away_team']}"
        label_to_neutral[label] = bool(row["neutral"])

    warnings: List[str] = []
    all_candidates = []

    for match_label, odds_rows in odds_rows_by_match.items():
        if match_label in label_to_neutral:
            neutral = label_to_neutral[match_label]
        else:
            neutral = True
            warnings.append(
                f"match '{match_label}' not found in fixtures_df; assuming neutral venue"
            )

        # Parse "Home v Away" to get team names for model.predict
        parts = match_label.split(" v ", 1)
        if len(parts) == 2:
            home, away = parts
        else:
            # Fallback: can't split, skip
            warnings.append(f"could not parse team names from label '{match_label}'; skipped")
            continue

        grid = model.predict(home, away, neutral_venue=neutral)
        candidates = build_candidates(grid, match_label, odds_rows)
        all_candidates.extend(candidates)

    recs = recommend(
        all_candidates,
        bankroll=bankroll,
        kelly_fraction=kelly_fraction,
        min_ev=min_ev,
        require_market_edge=require_market_edge,
    )

    return {
        "recommendations": [_rec_to_dict(r) for r in recs],
        "total_stake": sum(r.stake for r in recs),
        "n_candidates": len(all_candidates),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 3. live_snapshot
# ---------------------------------------------------------------------------


def live_snapshot(
    model,
    provider,
    home: str,
    away: str,
    *,
    neutral: bool,
    bankroll: float,
    kelly_fraction: float,
    min_ev: float,
) -> Dict[str, Any]:
    """Return a live in-play snapshot with updated probabilities and recommendations.

    Returns {"status": "not_live"} when the provider has no live state for
    the match.  Otherwise returns full pricing and a recommendations list.
    """
    state = provider.live_state(home, away)
    if state is None:
        return {"status": "not_live"}

    pre = model.predict(home, away, neutral_venue=neutral)
    live = live_grid(
        pre.home_goal_expectation,
        pre.away_goal_expectation,
        minute=state.minute,
        score_home=state.score_home,
        score_away=state.score_away,
        red_home=state.red_home,
        red_away=state.red_away,
    )

    _, _, over25 = live.totals(2.5)

    warnings: List[str] = []
    match_label = f"{home} v {away}"
    quotes = provider.odds(home, away)
    if not quotes:
        warnings.append("provider returned no odds; recommendations unavailable")
    odds_rows = [q.as_row() for q in quotes]
    candidates = build_candidates(live, match_label, odds_rows)

    recs = recommend(
        candidates,
        bankroll=bankroll,
        kelly_fraction=kelly_fraction,
        min_ev=min_ev,
    )

    return {
        "status": state.status,
        "minute": float(state.minute),
        "score": [state.score_home, state.score_away],
        "reds": [state.red_home, state.red_away],
        "p_home": float(live.home_win),
        "p_draw": float(live.draw),
        "p_away": float(live.away_win),
        "p_over25": float(over25),
        "recommendations": [_rec_to_dict(r) for r in recs],
        "warnings": warnings,
        "fetched_at": state.fetched_at,
    }
