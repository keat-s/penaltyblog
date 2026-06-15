"""FBref player-goal adapter (via the `soccerdata` scraper).

The Sportmonks "World Cup 2026" plan exposes only World Cup + WC-Qualifying
goals, so national-team scorers are undercounted (no Euros). FBref (via
soccerdata) carries the European Championship, so this provider supplements the
tallies with Euro goals. Note: soccerdata's FBref reader does NOT expose the
UEFA Nations League — only the Euros and (Women's/Men's) World Cup — so Nations
League goals remain unavailable from this source.

FBref sits behind Cloudflare and its terms discourage aggressive scraping, so we
go through `soccerdata` (a maintained client that rate-limits and disk-caches)
rather than hitting the site directly. `soccerdata` is an OPTIONAL dependency —
imported lazily so the rest of the package works without it.

Player identity is matched to other sources on BIRTH YEAR + name, not raw name:
FBref uses common names ("Pedri", "Rodri") while Sportmonks uses legal names
("Pedro González López", "Rodrigo Hernández Cascante"), which share no tokens.
See `wc26.playermatch`. The spike that established this is documented there.
"""

from __future__ import annotations

from typing import List, Optional

# soccerdata's FBref reader only exposes these national-team competitions; the
# Euros are the one Sportmonks doesn't already cover, so default to it.
DEFAULT_LEAGUES = ["INT-European Championship"]


class FbrefProvider:
    name = "fbref"

    def __init__(self, leagues: Optional[List[str]] = None):
        self.leagues = leagues or DEFAULT_LEAGUES

    def _reader(self, seasons):
        try:
            import soccerdata as sd
        except ImportError as e:  # pragma: no cover - optional dep
            raise RuntimeError(
                "fbref provider needs the 'soccerdata' package: pip install soccerdata"
            ) from e
        return sd.FBref(leagues=self.leagues, seasons=seasons)

    def team_player_goals(self, team: str, seasons) -> List[dict]:
        """Per-player goals for `team` across the configured leagues/seasons.

        Returns [{player, goals, minutes, appearances, born}] — same shape as the
        other adapters plus `born` (birth year) for cross-source matching. Goals
        are summed across every league/season requested.
        """
        df = self._reader(seasons).read_player_season_stats(stat_type="standard")
        # rows are indexed by (league, season, team, player)
        try:
            sub = df.xs(team, level="team")
        except KeyError:
            return []

        gls = ("Performance", "Gls")
        mins = ("Playing Time", "Min")
        apps = ("Playing Time", "MP")
        born = ("born", "")

        agg: dict = {}
        for idx, row in sub.iterrows():
            name = idx[-1] if isinstance(idx, tuple) else idx
            rec = agg.setdefault(
                name, {"player": name, "goals": 0, "minutes": 0, "appearances": 0, "born": None}
            )
            rec["goals"] += int(row.get(gls) or 0)
            rec["minutes"] += int(row.get(mins) or 0)
            rec["appearances"] += int(row.get(apps) or 0)
            if rec["born"] is None and row.get(born) is not None:
                try:
                    rec["born"] = int(row.get(born))
                except (TypeError, ValueError):
                    pass
        return list(agg.values())
