"""Live data providers: match state + odds from external APIs or CSV files."""

from .base import LiveState, OddsProvider, OddsQuote  # noqa: F401
from .csv_provider import CsvOddsProvider  # noqa: F401


def make_provider(name: str, **kwargs):
    """Factory: 'api-football' | 'sportmonks' | 'csv'."""
    name = name.lower().replace("_", "-")
    if name == "api-football":
        from .apifootball import ApiFootballProvider

        return ApiFootballProvider(**kwargs)
    if name == "sportmonks":
        from .sportmonks import SportmonksProvider

        return SportmonksProvider(**kwargs)
    if name == "csv":
        return CsvOddsProvider(**kwargs)
    raise ValueError(f"unknown provider '{name}'")
