import pytest

from wc26.providers.apifootball import ApiFootballProvider
from wc26.providers.mapping import map_market, parse_outcome
from wc26.providers.sportmonks import SportmonksProvider


def test_map_market():
    assert map_market("Match Winner") == "1x2"
    assert map_market("Fulltime Result") == "1x2"
    assert map_market("Over/Under Line") == "ou"
    assert map_market("Asian Handicap") == "ah"
    assert map_market("Both Teams Score") == "btts"
    assert map_market("Match Corners") is None
    assert map_market("Which team will score the 2nd goal?") is None


def test_parse_outcome_styles():
    assert parse_outcome("1x2", "Home") == ("home", None)
    assert parse_outcome("ou", "Over 2.5") == ("over", 2.5)  # line embedded in label
    assert parse_outcome("ou", "Over", handicap="2") == ("over", 2.0)  # separate field
    assert parse_outcome("ou", "Over") is None  # no line at all -> unusable
    assert parse_outcome("ah", "Home", handicap="-1") == ("home", -1.0)
    assert parse_outcome("ah", "Exactly", handicap="8") is None
    assert parse_outcome("btts", "Yes") == ("yes", None)


# --- API-Football: payloads lifted from official v3 doc response samples ---

AF_LIVE_FIXTURE = {
    "fixture": {"id": 721238, "status": {"short": "2H", "elapsed": 62}},
    "teams": {"home": {"id": 1563, "name": "Qatar"}, "away": {"id": 1565, "name": "Switzerland"}},
    "goals": {"home": 1, "away": 0},
    "events": [
        {"type": "Card", "detail": "Red card", "team": {"id": 1565}},
        {"type": "Card", "detail": "Yellow Card", "team": {"id": 1563}},
        {"type": "Goal", "detail": "Normal Goal", "team": {"id": 1563}},
    ],
}

AF_LIVE_ODDS = [
    {
        "fixture": {"id": 721238, "status": {"long": "Second Half", "elapsed": 62}},
        "status": {"stopped": False, "blocked": False, "finished": False},
        "odds": [
            {
                "id": 33,
                "name": "Asian Handicap",
                "values": [
                    {"value": "Home", "odd": "1.475", "handicap": "-1", "main": False},
                    {"value": "Home", "odd": "2.05", "handicap": "-1", "main": True},
                    {"value": "Away", "odd": "1.8", "handicap": "1", "main": True},
                ],
            },
            {
                "id": 36,
                "name": "Over/Under Line",
                "values": [
                    {"value": "Over", "odd": "1.625", "handicap": "2", "main": None},
                    {"value": "Under", "odd": "2.25", "handicap": "2", "main": None},
                ],
            },
            {
                "id": 20,
                "name": "Match Corners",
                "values": [{"value": "Over", "odd": "2.5", "handicap": "8", "main": None}],
            },
        ],
    }
]


def _af_provider(monkeypatch, responses):
    p = ApiFootballProvider(api_key="test")
    monkeypatch.setattr(p, "_get", lambda path, **kw: responses[path])
    return p


def test_apifootball_live_state(monkeypatch):
    p = _af_provider(monkeypatch, {"/fixtures": [AF_LIVE_FIXTURE]})
    state = p.live_state("Qatar", "Switzerland")
    assert state.minute == 62
    assert (state.score_home, state.score_away) == (1, 0)
    assert (state.red_home, state.red_away) == (0, 1)  # yellow ignored
    assert state.status == "live"


# Payload shape from the real live=all response, 2026-06-13: API-Football
# names the hosts "USA" while the results dataset says "United States".
AF_LIVE_USA_FIXTURE = {
    "fixture": {"id": 1489370, "status": {"short": "1H", "elapsed": 28}},
    "teams": {"home": {"id": 2384, "name": "USA"}, "away": {"id": 30, "name": "Paraguay"}},
    "goals": {"home": 1, "away": 0},
    "events": [],
}


def test_apifootball_team_alias(monkeypatch):
    p = _af_provider(monkeypatch, {"/fixtures": [AF_LIVE_USA_FIXTURE]})
    state = p.live_state("United States", "Paraguay")
    assert state is not None
    assert (state.score_home, state.score_away) == (1, 0)
    # unrelated teams must still miss
    assert p.live_state("Uruguay", "Paraguay") is None


AF_PREMATCH_ODDS = [
    {
        "bookmakers": [
            {
                "name": "Pinnacle",
                "bets": [
                    {
                        "name": "Asian Handicap",
                        "values": [
                            {"value": "Home -1", "odd": "1.74"},
                            {"value": "Away -1", "odd": "2.20"},  # home-referenced label
                        ],
                    }
                ],
            }
        ]
    }
]

AF_NS_FIXTURE = {
    "fixture": {"id": 1489369, "status": {"short": "NS", "elapsed": None}},
    "teams": {"home": {"id": 1, "name": "Mexico"}, "away": {"id": 2, "name": "South Africa"}},
    "goals": {"home": None, "away": None},
}


def test_apifootball_prematch_ah_lines_per_side(monkeypatch):
    from wc26.edge import build_candidates

    p = _af_provider(
        monkeypatch,
        {"/fixtures": [AF_NS_FIXTURE], "/odds": AF_PREMATCH_ODDS},
    )
    quotes = p.odds("Mexico", "South Africa")
    assert {(q.outcome, q.line) for q in quotes} == {("home", -1.0), ("away", 1.0)}

    # opposite-sign AH pair must still de-vig together
    import numpy as np
    from scipy.stats import poisson as pois

    from penaltyblog.models import FootballProbabilityGrid

    goals = np.arange(16)
    grid = FootballProbabilityGrid(
        np.outer(pois.pmf(goals, 1.8), pois.pmf(goals, 0.8)), 1.8, 0.8, normalize=True
    )
    cands = build_candidates(grid, "Mexico v South Africa", [q.as_row() for q in quotes])
    assert all(c.fair_prob is not None for c in cands)
    assert sum(c.fair_prob for c in cands) == pytest.approx(1.0, abs=0.01)


def test_apifootball_live_odds_main_rows_only(monkeypatch):
    p = _af_provider(
        monkeypatch, {"/fixtures": [AF_LIVE_FIXTURE], "/odds/live": AF_LIVE_ODDS}
    )
    quotes = p.odds("Qatar", "Switzerland")
    ah = [q for q in quotes if q.market == "ah"]
    assert len(ah) == 2  # main:true rows only, not the main:false duplicate
    assert {(q.outcome, q.line, q.odds) for q in ah} == {("home", -1.0, 2.05), ("away", 1.0, 1.8)}
    ou = [q for q in quotes if q.market == "ou"]
    assert {(q.outcome, q.line) for q in ou} == {("over", 2.0), ("under", 2.0)}
    assert not [q for q in quotes if q.market is None]


# --- Sportmonks: payloads per docs.sportmonks.com entity definitions ---

SM_INPLAY = [
    {
        "id": 18535517,
        "participants": [
            {"id": 53, "name": "Celtic", "meta": {"location": "home"}},
            {"id": 62, "name": "Rangers", "meta": {"location": "away"}},
        ],
        "periods": [
            {"ticking": False, "minutes": 45, "counts_from": 0, "description": "1st-half"},
            {"ticking": True, "minutes": 17, "counts_from": 45, "description": "2nd-half"},
        ],
        "scores": [
            {"description": "CURRENT", "score": {"goals": 2, "participant": "home"}},
            {"description": "CURRENT", "score": {"goals": 1, "participant": "away"}},
            {"description": "1ST_HALF", "score": {"goals": 1, "participant": "home"}},
        ],
        "events": [
            {"type_id": 20, "participant_id": 62, "rescinded": False},
            {"type_id": 19, "participant_id": 53, "rescinded": False},
            {"type_id": 21, "participant_id": 62, "rescinded": True},
        ],
    }
]

SM_ODDS = [
    {
        "market_id": 1,
        "market_description": "Fulltime Result",
        "label": "Home",
        "value": "1.48",
        "dp3": "1.480",
        "stopped": False,
        "bookmaker": {"name": "bet365"},
    },
    {
        "market_id": 80,
        "market_description": "Over/Under",
        "label": "Over",
        "value": "1.95",
        "dp3": "1.950",
        "total": "2.5",
        "stopped": False,
        "bookmaker": {"name": "Pinnacle"},
    },
    {
        "market_id": 1,
        "market_description": "Fulltime Result",
        "label": "Draw",
        "value": "3.80",
        "dp3": "3.800",
        "stopped": True,  # suspended -> dropped
        "bookmaker": {"name": "bet365"},
    },
]


def _sm_provider(monkeypatch, responses):
    p = SportmonksProvider(api_key="test")
    monkeypatch.setattr(p, "_get", lambda path, **kw: responses[path])
    return p


def test_sportmonks_live_state(monkeypatch):
    p = _sm_provider(monkeypatch, {"/livescores/inplay": SM_INPLAY})
    state = p.live_state("Celtic", "Rangers")
    assert state.minute == 62
    assert (state.score_home, state.score_away) == (2, 1)
    assert (state.red_home, state.red_away) == (0, 1)  # rescinded card ignored


def test_sportmonks_odds(monkeypatch):
    p = _sm_provider(
        monkeypatch,
        {
            "/livescores/inplay": SM_INPLAY,
            "/odds/pre-match/fixtures/18535517": SM_ODDS,
        },
    )
    quotes = p.odds("Celtic", "Rangers")
    assert {(q.market, q.outcome, q.line, q.odds) for q in quotes} == {
        ("1x2", "home", None, 1.48),
        ("ou", "over", 2.5, 1.95),
    }
    assert quotes[0].bookmaker == "bet365"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("WC26_APIFOOTBALL_KEY", raising=False)
    monkeypatch.delenv("WC26_SPORTMONKS_KEY", raising=False)
    with pytest.raises(ValueError):
        ApiFootballProvider()
    with pytest.raises(ValueError):
        SportmonksProvider()
