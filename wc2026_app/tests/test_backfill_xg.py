import pandas as pd

from wc26.backfill import merge_results
from wc26.providers.mapping import normalize_team
from wc26.xg import estimate_side_xg, estimate_xg


def test_normalize_team():
    assert normalize_team("Türkiye") == "Turkey"
    assert normalize_team("Côte d'Ivoire") == "Ivory Coast"
    assert normalize_team("Korea Republic") == "South Korea"
    assert normalize_team("Curacao") == "Curaçao"
    assert normalize_team("Brazil") == "Brazil"  # pass-through


def _df():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-13", "2026-06-13"]),
            "home_team": ["Haiti", "Australia"],
            "away_team": ["Scotland", "Turkey"],
            "home_score": [float("nan"), float("nan")],
            "away_score": [float("nan"), float("nan")],
        }
    )


def test_merge_fills_nan_scores():
    df = _df()
    rows = [
        # provider dates one day off (UTC vs local) — must still match
        {"date": "2026-06-14", "home_team": "Haiti", "away_team": "Scotland",
         "home_score": 0, "away_score": 1},
        {"date": "2026-06-14", "home_team": "Australia", "away_team": "Turkey",
         "home_score": 2, "away_score": 0},
    ]
    summary = merge_results(df, rows)
    assert summary["filled"] == 2
    assert not summary["unmatched"]
    assert df.loc[0, ["home_score", "away_score"]].tolist() == [0, 1]
    assert df.loc[1, ["home_score", "away_score"]].tolist() == [2, 0]


def test_merge_reorients_when_sides_flipped():
    df = _df()
    # provider lists Scotland as home; dataset lists Haiti as home
    rows = [{"date": "2026-06-13", "home_team": "Scotland", "away_team": "Haiti",
             "home_score": 1, "away_score": 0}]
    merge_results(df, rows)
    # Haiti (dataset home) must get 0, Scotland (away) 1
    assert df.loc[0, ["home_score", "away_score"]].tolist() == [0, 1]


def test_merge_respects_overwrite_flag():
    df = _df()
    df.loc[0, ["home_score", "away_score"]] = [9, 9]  # already populated
    rows = [{"date": "2026-06-13", "home_team": "Haiti", "away_team": "Scotland",
             "home_score": 0, "away_score": 1}]
    s = merge_results(df, rows, overwrite=False)
    assert s["filled"] == 0 and s["corrected"] == 0
    assert df.loc[0, ["home_score", "away_score"]].tolist() == [9, 9]  # untouched
    s = merge_results(df, rows, overwrite=True)
    assert s["corrected"] == 1
    assert df.loc[0, ["home_score", "away_score"]].tolist() == [0, 1]


def test_merge_reports_unmatched():
    df = _df()
    rows = [{"date": "2026-06-13", "home_team": "Spain", "away_team": "Japan",
             "home_score": 1, "away_score": 1}]
    s = merge_results(df, rows)
    assert len(s["unmatched"]) == 1


def test_xg_proxy_monotonic_and_nonneg():
    # more big chances -> more xG; empty stats -> 0
    assert estimate_side_xg({}) == 0.0
    low = estimate_side_xg({"shots_insidebox": 2, "shots_outsidebox": 3})
    high = estimate_side_xg(
        {"big_chances_created": 4, "shots_insidebox": 10, "shots_outsidebox": 3}
    )
    assert high > low > 0

    # big chances counted once (not double with inside-box)
    xh, xa = estimate_xg(
        {"big_chances_created": 1, "shots_insidebox": 1, "shots_outsidebox": 0},
        {"shots_insidebox": 1, "shots_outsidebox": 0},
    )
    assert xh == 0.35  # 1 big chance, no extra inside-box shots
    assert xa == 0.10  # 1 plain inside-box shot
