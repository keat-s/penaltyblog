"""Cross-source player matching for goal aggregation.

Different providers spell the same player differently — FBref uses common names
("Pedri", "Rodri"), Sportmonks uses legal names ("Pedro González López",
"Rodrigo Hernández Cascante"). These share no name tokens, so pure fuzzy/surname
matching fails on exactly the players who matter most.

Spike result (Spain squad, 2026-06): name-only matching scored 64% and missed
every nickname; matching on BIRTH YEAR + a guarded fuzzy name scored 92% and
resolved Rodri↔Rodrigo (100) and Pedri↔Pedro González López (89). The guard
(shared surname token OR fuzzy >= 80) rejects same-birth-year collisions such as
Yeremi Pino (2002) -> Pedri (2002), which a bare year+threshold would accept.
"""

from __future__ import annotations

import unicodedata
from typing import List, Optional

from rapidfuzz import fuzz

_STRONG = 80  # fuzzy score that stands on its own, even without a shared surname


def _norm(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def _tokens(s: str) -> set:
    return set(_norm(s).split())


def _name_score(a: str, b: str) -> float:
    """max(token_set, partial) — partial_ratio is what catches nicknames whose
    legal name embeds the common name (Pedri in Pedro..., Rodri in Rodrigo...)."""
    na, nb = _norm(a), _norm(b)
    return max(fuzz.token_set_ratio(na, nb), fuzz.partial_ratio(na, nb))


def _is_match(a: str, b: str) -> bool:
    """Name-level match guard: shared name token OR a strong fuzzy score."""
    if _tokens(a) & _tokens(b):
        return True
    return _name_score(a, b) >= _STRONG


def find_match(name: str, born: Optional[int], candidates: List[dict]) -> Optional[dict]:
    """Best candidate sharing `born` year and passing the name guard, else None.

    `candidates` are dicts with at least `player` and `born`. Among those with the
    same birth year, the highest fuzzy-scoring name that clears the guard wins.
    """
    if born is None:
        return None
    same_year = [c for c in candidates if c.get("born") == born]
    scored = []
    for c in same_year:
        if _is_match(name, c["player"]):
            scored.append((_name_score(name, c["player"]), c))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def merge_goals(primary: List[dict], secondary: List[dict]) -> List[dict]:
    """Add `secondary` goal tallies onto `primary`, joined by birth year + name.

    `primary` is the authoritative roster (e.g. Sportmonks current squad); every
    primary player is kept. A matched secondary record adds its goals/minutes/
    appearances. Unmatched secondary players are dropped (not on the roster).
    Both lists carry {player, goals, minutes, appearances, born}.
    """
    merged = [dict(p) for p in primary]
    used = set()
    for p in merged:
        m = find_match(p["player"], p.get("born"), secondary)
        if m is None:
            continue
        key = (m["player"], m.get("born"))
        if key in used:  # never count one secondary record twice
            continue
        used.add(key)
        p["goals"] += m.get("goals", 0)
        p["minutes"] += m.get("minutes", 0)
        p["appearances"] += m.get("appearances", 0)
        p["matched_fbref"] = m["player"]
    return merged
