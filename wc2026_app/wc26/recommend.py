"""Turn +EV candidates into a diverse, Kelly-sized recommendation slate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from penaltyblog.betting.kelly import kelly_criterion

from .edge import Candidate


@dataclass
class Recommendation:
    candidate: Candidate
    stake_fraction: float
    stake: float

    def describe(self) -> str:
        c = self.candidate
        line = f" {c.line:+g}" if c.line is not None else ""
        fair = f" fair={c.fair_prob:.3f}" if c.fair_prob is not None else ""
        return (
            f"{c.match} | {c.market}{line} {c.outcome} @ {c.odds:.2f} "
            f"| model p={c.p_win:.3f}{fair} ev={c.ev:+.3f} tier={c.tier} "
            f"| stake {self.stake:.2f} ({self.stake_fraction:.2%})"
        )


def select_diverse(
    candidates: List[Candidate],
    min_ev: float = 0.02,
    min_prob: float = 0.10,
    require_market_edge: bool = False,
    max_per_match: int = 2,
    max_per_tier: Optional[dict] = None,
) -> List[Candidate]:
    """Filter to +EV candidates, enforcing diversity across matches/tiers.

    - Best candidate per (match, market, line): no betting both sides.
    - `max_per_match` caps correlated exposure to one game.
    - `max_per_tier` caps how many high-variance bets make the slate.
    - `min_prob` is a longshot guardrail: bookmakers price longshots *more*
      accurately than favourites and load margin onto them, so model "value"
      below ~10% win probability is the most likely false signal class.
    """
    max_per_tier = max_per_tier or {"low": 6, "medium": 6, "high": 2}

    pool = [c for c in candidates if c.ev >= min_ev and c.p_eff >= min_prob]
    if require_market_edge:
        # Strict: candidates without a de-vigged market probability (incomplete
        # odds set) are excluded, not waved through.
        pool = [c for c in pool if c.edge_vs_market is not None and c.edge_vs_market > 0]

    pool.sort(key=lambda c: c.ev, reverse=True)

    seen_market, per_match, per_tier = set(), {}, {}
    selected = []
    for c in pool:
        key = (c.match, c.market, c.line)
        if key in seen_market:
            continue
        if per_match.get(c.match, 0) >= max_per_match:
            continue
        if per_tier.get(c.tier, 0) >= max_per_tier.get(c.tier, 99):
            continue
        seen_market.add(key)
        per_match[c.match] = per_match.get(c.match, 0) + 1
        per_tier[c.tier] = per_tier.get(c.tier, 0) + 1
        selected.append(c)
    return selected


def size_stakes(
    selected: List[Candidate],
    bankroll: float = 1000.0,
    kelly_fraction: float = 0.25,
    max_total_stake: float = 0.15,
) -> List[Recommendation]:
    """Size stakes with independent fractional Kelly, capped as a slate.

    Bets across different matches are independent, not mutually exclusive
    outcomes of one market (penaltyblog's `multiple_kelly_criterion` models
    the latter), so each bet gets its own Kelly stake from its
    push-conditional win probability. Fractional Kelly (default quarter)
    shrinks stakes for model uncertainty — full Kelly on a noisy model
    overbets and risks deep drawdowns over a ~104-match tournament. If the
    summed stakes exceed `max_total_stake`, the slate is scaled down
    proportionally.
    """
    if not selected:
        return []
    fractions = [
        float(kelly_criterion(c.odds, c.p_eff, fraction=kelly_fraction).stake)
        for c in selected
    ]
    total = sum(fractions)
    if total > max_total_stake:
        fractions = [f * max_total_stake / total for f in fractions]
    recs = [
        Recommendation(candidate=c, stake_fraction=f, stake=f * bankroll)
        for c, f in zip(selected, fractions)
        if f > 1e-6
    ]
    recs.sort(key=lambda r: r.stake, reverse=True)
    return recs


def recommend(
    candidates: List[Candidate],
    bankroll: float = 1000.0,
    kelly_fraction: float = 0.25,
    min_ev: float = 0.02,
    **select_kwargs,
) -> List[Recommendation]:
    selected = select_diverse(candidates, min_ev=min_ev, **select_kwargs)
    return size_stakes(selected, bankroll=bankroll, kelly_fraction=kelly_fraction)
