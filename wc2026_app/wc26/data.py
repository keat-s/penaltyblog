"""Load international results and WC2026 fixtures.

Data source: martj42/international_results — all international matches since
1872, including future WC2026 fixtures (NA scores) and a per-match `neutral`
flag that maps directly onto penaltyblog's `neutral_venue` model input.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)
DEFAULT_CACHE = Path.home() / ".cache" / "wc26" / "results.csv"

HOSTS = ("United States", "Mexico", "Canada")

# Competitive matches carry more signal than friendlies. Hosts are the
# exception: they skip qualification, so friendlies are all the recent data
# they have — down-weighting those starves the model of host signal.
COMPETITIVE_PATTERN = (
    "FIFA World Cup|qualification|Copa|Euro|Nations League|"
    "Cup of Nations|Gold Cup|Asian Cup"
)


@dataclass
class TrainingData:
    goals_home: np.ndarray
    goals_away: np.ndarray
    teams_home: np.ndarray
    teams_away: np.ndarray
    weights: np.ndarray
    neutral_venue: np.ndarray


def load_results(cache: Path | str = DEFAULT_CACHE, refresh: bool = False) -> pd.DataFrame:
    """Download (or read cached) international results CSV."""
    cache = Path(cache).expanduser()
    if refresh or not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(RESULTS_URL, cache)
    return pd.read_csv(cache, parse_dates=["date"])


def training_data(
    df: pd.DataFrame,
    asof: str | pd.Timestamp,
    years: float = 6.0,
    xi: float = 0.0019,
    friendly_weight: float = 0.6,
    host_friendly_weight: float = 1.0,
) -> TrainingData:
    """Build model inputs from played matches before `asof`.

    - Exponential time decay: weight = exp(-xi * days_ago).
    - Friendlies down-weighted, except friendlies involving a host nation
      (hosts skip qualification, friendlies are their only recent matches).
    """
    asof = pd.Timestamp(asof)
    played = df.dropna(subset=["home_score", "away_score"])
    cutoff = asof - pd.Timedelta(days=int(years * 365.25))
    train = played[(played["date"] >= cutoff) & (played["date"] < asof)].copy()
    if train.empty:
        raise ValueError(f"no played matches between {cutoff.date()} and {asof.date()}")

    days_ago = (asof - train["date"]).dt.days.to_numpy()
    weights = np.exp(-xi * days_ago)

    competitive = train["tournament"].str.contains(
        COMPETITIVE_PATTERN, case=False, regex=True
    ).to_numpy()
    involves_host = (
        train["home_team"].isin(HOSTS) | train["away_team"].isin(HOSTS)
    ).to_numpy()
    comp_weight = np.where(
        competitive, 1.0, np.where(involves_host, host_friendly_weight, friendly_weight)
    )

    return TrainingData(
        goals_home=train["home_score"].to_numpy(dtype=int),
        goals_away=train["away_score"].to_numpy(dtype=int),
        teams_home=train["home_team"].to_numpy(),
        teams_away=train["away_team"].to_numpy(),
        weights=weights * comp_weight,
        neutral_venue=train["neutral"].astype(int).to_numpy(),
    )


def fixtures(
    df: pd.DataFrame,
    date_from: str | pd.Timestamp | None = None,
    days: int = 7,
    tournament: str = "FIFA World Cup",
) -> pd.DataFrame:
    """Upcoming (unplayed) tournament fixtures within `days` of `date_from`."""
    fx = df[df["tournament"] == tournament]
    fx = fx[fx["home_score"].isna()]
    if date_from is not None:
        start = pd.Timestamp(date_from)
        fx = fx[fx["date"].between(start, start + pd.Timedelta(days=days))]
    return fx[["date", "home_team", "away_team", "neutral", "city", "country"]].reset_index(
        drop=True
    )
