"""Tests for cross-source player matching (the FBref<->Sportmonks join)."""

from wc26.playermatch import find_match, merge_goals


def _p(name, born, goals=0):
    return {"player": name, "goals": goals, "minutes": 0, "appearances": 0, "born": born}


# FBref-style common names the join must reconcile to legal names by birth year.
FBREF = [
    _p("Pedri", 2002, 1),
    _p("Rodri", 1996, 2),
    _p("Nico Williams", 2002, 3),
    _p("Álvaro Morata", 1992, 5),  # roster drift: not in the primary squad
]


def test_nickname_matches_via_birth_year():
    # Legal name shares NO token with "Pedri" — only birth year + partial fuzzy joins them.
    m = find_match("Pedro González López", 2002, FBREF)
    assert m is not None and m["player"] == "Pedri"


def test_surname_token_match():
    m = find_match("Nicholas Williams Arthuer", 2002, FBREF)
    assert m is not None and m["player"] == "Nico Williams"


def test_same_birth_year_collision_rejected():
    # Yeremi Pino (2002) must NOT match Pedri (2002): no shared token, weak fuzzy.
    m = find_match("Yeremi Jesús Pino Santos", 2002, FBREF)
    assert m is None or m["player"] != "Pedri"


def test_missing_birth_year_no_match():
    assert find_match("Pedro González López", None, FBREF) is None


def test_merge_adds_goals_and_keeps_full_roster():
    squad = [
        _p("Pedro González López", 2002, 2),   # +1 from Pedri
        _p("Rodrigo Hernández Cascante", 1996, 0),  # +2 from Rodri
        _p("Joan García Pons", 2001, 0),        # no FBref record
    ]
    merged = merge_goals(squad, FBREF)
    by = {p["player"]: p for p in merged}
    assert len(merged) == 3  # every primary player kept
    assert by["Pedro González López"]["goals"] == 3
    assert by["Rodrigo Hernández Cascante"]["goals"] == 2
    assert by["Joan García Pons"]["goals"] == 0
    # roster-drift FBref player (Morata) is dropped, not appended
    assert "Álvaro Morata" not in by


def test_secondary_record_not_double_counted():
    # two primary players that could both fuzzy-match one FBref record:
    # only the first should consume it.
    squad = [_p("Rodrigo Hernández Cascante", 1996, 0), _p("Rodrigo Other", 1996, 0)]
    merged = merge_goals(squad, [_p("Rodri", 1996, 2)])
    assert sum(p["goals"] for p in merged) == 2  # Rodri's 2 goals counted once
