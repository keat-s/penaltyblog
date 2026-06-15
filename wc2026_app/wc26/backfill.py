"""Backfill played scores into the cached results CSV from a live provider.

The martj42 dataset already carries every WC2026 fixture as a row with empty
scores; its upstream refresh lags by a day or two. Sportmonks publishes finals
within minutes, so we fill those NaN scores in place — matching on date and the
unordered pair of teams, then assigning each team's goals to the dataset's
home/away orientation (which may differ from the provider's).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd

from .data import DEFAULT_CACHE, load_results


# Provider timestamps are UTC; the dataset uses the local match date, so a late
# kickoff can land on the previous/next calendar day. Match within this slack.
_DATE_SLACK = pd.Timedelta(days=1)


def _pair(a: str, b: str) -> frozenset:
    return frozenset((a, b))


def merge_results(df: pd.DataFrame, rows: List[dict], overwrite: bool = False) -> dict:
    """Fill scores in `df` from provider `rows` (from SportmonksProvider.results).

    Matches by team pair with a +/-1 day tolerance on the date (provider UTC vs
    dataset local). By default only fills rows whose scores are currently NaN;
    `overwrite=True` also corrects already-populated scores. Mutates `df` in
    place. Returns a summary dict.
    """
    # team-pair -> list of (date, row_index) candidates
    index: dict = {}
    for i, r in df.iterrows():
        index.setdefault(_pair(r["home_team"], r["away_team"]), []).append((r["date"], i))

    filled, corrected, unmatched = 0, 0, []
    for row in rows:
        want = pd.Timestamp(row["date"])
        candidates = index.get(_pair(row["home_team"], row["away_team"]), [])
        near = [(abs(d - want), i) for d, i in candidates if abs(d - want) <= _DATE_SLACK]
        if not near:
            unmatched.append(f"{row['date']} {row['home_team']} v {row['away_team']}")
            continue
        i = min(near)[1]  # closest date wins
        # orient provider goals onto the dataset's home/away columns
        if df.at[i, "home_team"] == row["home_team"]:
            hs, as_ = row["home_score"], row["away_score"]
        else:  # dataset lists the teams the other way round
            hs, as_ = row["away_score"], row["home_score"]

        had = pd.notna(df.at[i, "home_score"])
        if had and not overwrite:
            continue
        if had and (df.at[i, "home_score"] != hs or df.at[i, "away_score"] != as_):
            corrected += 1
        elif not had:
            filled += 1
        df.at[i, "home_score"] = hs
        df.at[i, "away_score"] = as_

    return {
        "provided": len(rows),
        "filled": filled,
        "corrected": corrected,
        "unmatched": unmatched,
    }


def backfill_cache(
    rows: List[dict],
    cache: Path | str = DEFAULT_CACHE,
    overwrite: bool = False,
) -> dict:
    """Load the cached results CSV, merge `rows`, write it back. Returns summary."""
    cache = Path(cache).expanduser()
    df = load_results(cache=cache, refresh=False)
    summary = merge_results(df, rows, overwrite=overwrite)
    df.to_csv(cache, index=False)
    summary["cache"] = str(cache)
    return summary


def backfill_from_sportmonks(
    date_from: str,
    date_to: str,
    api_key: Optional[str] = None,
    cache: Path | str = DEFAULT_CACHE,
    overwrite: bool = False,
) -> dict:
    """Fetch finished matches from Sportmonks and merge them into the cache."""
    from .providers.sportmonks import SportmonksProvider

    provider = SportmonksProvider(api_key=api_key)
    rows = provider.results(date_from, date_to)
    return backfill_cache(rows, cache=cache, overwrite=overwrite)
