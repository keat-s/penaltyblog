"""Edge engine: de-vig bookmaker odds, compare against model probabilities.

Research note: naive multiplicative (equal-margin) de-vigging is systematically
wrong because bookmakers load margin onto longshots (favourite-longshot bias);
it generates false value signals on long odds. Default here is the bias-aware
"power" method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from penaltyblog.implied import calculate_implied

from .markets import MARKET_TIERS, model_probs

DEFAULT_DEVIG_METHOD = "power"


@dataclass
class Candidate:
    """A potential bet with model and (optionally) market probabilities."""

    match: str
    market: str
    outcome: str
    odds: float
    p_win: float
    p_push: float = 0.0
    line: Optional[float] = None
    fair_prob: Optional[float] = None  # de-vigged market prob for this outcome
    tier: str = field(default="")

    def __post_init__(self) -> None:
        if not self.tier:
            self.tier = MARKET_TIERS.get(self.market.lower(), "high")

    @property
    def ev(self) -> float:
        """Expected value per unit stake (push refunds stake)."""
        return self.p_win * self.odds + self.p_push - 1.0

    @property
    def p_eff(self) -> float:
        """Win probability conditional on the bet not pushing."""
        if self.p_push >= 1.0:
            return 0.0
        return self.p_win / (1.0 - self.p_push)

    @property
    def edge_vs_market(self) -> Optional[float]:
        """Model minus de-vigged market probability (None if no full market odds)."""
        if self.fair_prob is None:
            return None
        return self.p_eff - self.fair_prob


def devig(odds: Sequence[float], method: str = DEFAULT_DEVIG_METHOD) -> List[float]:
    """Remove bookmaker margin from a complete outcome set of decimal odds."""
    result = calculate_implied(list(odds), method=method)
    return list(result.probabilities)


# Outcomes needed for a market to be de-viggable (mutually exclusive +
# exhaustive). Double chance is excluded: its outcomes overlap (1x and x2
# share the draw), so margin-removal math produces meaningless "fair"
# probabilities — derive DC fair values from de-vigged 1X2 instead if needed.
COMPLETE_MARKETS = {"1x2": 3, "ou": 2, "ah": 2, "btts": 2, "dnb": 2}

SHARP_BOOKS = ("pinnacle",)


def build_candidates(
    grid,
    match: str,
    odds_rows: List[Dict],
    devig_method: str = DEFAULT_DEVIG_METHOD,
) -> List[Candidate]:
    """Build candidates for one match from odds rows.

    Each row: {market, outcome, odds, line (optional), bookmaker (optional)}.

    Line shopping: with multiple bookmakers quoting the same outcome, the
    candidate takes the best (maximum) price — best-vs-average odds is worth
    +42-296% profit in backtests, a first-order effect.

    Fair probabilities: de-vig a complete outcome set from a single book,
    preferring a sharp book (Pinnacle) whose de-margined closing odds are
    near-efficient; otherwise the complete set with the lowest margin.
    """
    rows = []
    for row in odds_rows:
        line = row.get("line")
        line = (
            None
            if line in ("", None) or (isinstance(line, float) and line != line)
            else float(line)
        )
        rows.append(
            {
                "market": str(row["market"]).lower(),
                "outcome": str(row["outcome"]).lower(),
                "line": line,
                "odds": float(row["odds"]),
                "book": str(row.get("bookmaker", "") or "").lower(),
            }
        )

    # Best price per (market, line, outcome).
    best: Dict = {}
    for r in rows:
        key = (r["market"], r["line"], r["outcome"])
        if key not in best or r["odds"] > best[key]["odds"]:
            best[key] = r

    candidates = []
    for (market, line, outcome), r in best.items():
        p_win, p_push = model_probs(grid, market, outcome, line)
        candidates.append(
            Candidate(
                match=match,
                market=market,
                outcome=outcome,
                line=line,
                odds=r["odds"],
                p_win=p_win,
                p_push=p_push,
            )
        )

    # Fair probs from a single book's complete outcome set per (market, line).
    # Lines are per-side, so the two halves of an Asian handicap market sit on
    # opposite signs (home -1 pairs with away +1): group AH by the
    # home-referenced line so they de-vig together.
    def group_line(market, outcome, line):
        if market == "ah" and outcome == "away" and line is not None:
            return -line
        return line

    by_market: Dict = {}
    for r in rows:
        key = (r["market"], group_line(r["market"], r["outcome"], r["line"]))
        book_odds = by_market.setdefault(key, {}).setdefault(r["book"], {})
        book_odds[r["outcome"]] = max(r["odds"], book_odds.get(r["outcome"], 0.0))

    for (market, line), books in by_market.items():
        need = COMPLETE_MARKETS.get(market)
        if not need:
            continue
        complete_sets = {b: o for b, o in books.items() if len(o) == need}
        if not complete_sets:
            continue
        sharp = next((b for b in SHARP_BOOKS if b in complete_sets), None)
        book = sharp or min(
            complete_sets, key=lambda b: sum(1 / o for o in complete_sets[b].values())
        )
        outcomes = list(complete_sets[book])
        fair = devig([complete_sets[book][o] for o in outcomes], method=devig_method)
        fair_by_outcome = dict(zip(outcomes, fair))
        for c in candidates:
            if (
                c.market == market
                and group_line(c.market, c.outcome, c.line) == line
                and c.outcome in fair_by_outcome
            ):
                c.fair_prob = fair_by_outcome[c.outcome]

    return candidates
