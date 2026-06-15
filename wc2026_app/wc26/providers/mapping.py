"""Vendor market/outcome name normalization shared by API adapters."""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Vendor market names -> internal market keys. Matched case-insensitively on
# normalized names; first hit wins, unmapped markets are skipped.
_MARKET_PATTERNS = [
    (r"^(match winner|fulltime result|match odds|1x2|full time result)$", "1x2"),
    (r"^(goals over/under|over/under|over/under line|goals over under)$", "ou"),
    (r"^asian handicap$", "ah"),
    (r"^(both teams score|both teams to score|btts)$", "btts"),
    (r"^(draw no bet)$", "dnb"),
]


# Sportmonks participant names -> martj42/international_results canonical names.
# Only the divergent ones; anything not listed passes through unchanged.
TEAM_NAME_MAP = {
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
    "Curacao": "Curaçao",
    "Côte d'Ivoire": "Ivory Coast",
    "Korea Republic": "South Korea",
    "Türkiye": "Turkey",
}


def normalize_team(vendor_name: str) -> str:
    """Map a vendor team name onto the results-dataset spelling."""
    return TEAM_NAME_MAP.get(vendor_name.strip(), vendor_name.strip())


def map_market(vendor_name: str) -> Optional[str]:
    name = vendor_name.strip().lower()
    for pattern, key in _MARKET_PATTERNS:
        if re.match(pattern, name):
            return key
    return None


def parse_outcome(
    market: str,
    label: str,
    handicap: Optional[str] = None,
    total: Optional[str] = None,
) -> Optional[Tuple[str, Optional[float]]]:
    """Normalize a vendor outcome label to (outcome, line).

    Handles both styles vendors use for lines: embedded in the label
    ("Over 2.5") and as a separate handicap/total field ("Over" + "2.5").
    Returns None for outcomes we don't price (e.g. "Exactly" on corners).
    """
    text = str(label).strip().lower()
    line = None
    for raw in (handicap, total):
        if raw not in (None, ""):
            try:
                line = float(raw)
                break
            except (TypeError, ValueError):
                pass

    if market == "1x2":
        mapping = {"home": "home", "1": "home", "draw": "draw", "x": "draw", "away": "away", "2": "away"}
        outcome = mapping.get(text)
        return (outcome, None) if outcome else None

    if market == "ou":
        m = re.match(r"^(over|under)(?:\s+([\d.]+))?$", text)
        if not m:
            return None
        if m.group(2):
            line = float(m.group(2))
        return (m.group(1), line) if line is not None else None

    if market == "ah":
        m = re.match(r"^(home|away)(?:\s+([+-]?[\d.]+))?$", text)
        if not m:
            return None
        if m.group(2):
            line = float(m.group(2))
        return (m.group(1), line) if line is not None else None

    if market == "btts":
        mapping = {"yes": "yes", "no": "no"}
        outcome = mapping.get(text)
        return (outcome, None) if outcome else None

    if market == "dnb":
        mapping = {"home": "home", "1": "home", "away": "away", "2": "away"}
        outcome = mapping.get(text)
        return (outcome, None) if outcome else None

    return None
