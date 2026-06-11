# Props

Prop-market pricing for anytime scorer, corners, and shots on target — the **Props** tab of the [dashboard](dashboard.md). Reading time: ~6 minutes.

Read the [caveats](#honest-caveats) first. Props are the most speculative module in the app: thinner data, higher margins, and no efficiency evidence.

## Model assumptions

### Anytime scorer: Poisson thinning

The scorer model is a thinning of the team goal model, not a separate player model:

```
P(player scores ≥ 1) = 1 − exp(−λ_team × share)
```

- `λ_team` is the team's goal expectation for the selected fixture from the cached match model (Dixon-Coles by default), neutral-venue aware exactly like the other tabs.
- `share` is the player's Laplace-smoothed share of the team's season goals: `(goals_i + s) / (Σ goals + s·n)` with `s = 1`. Smoothing pulls shares toward uniform, so zero-goal players keep a small nonzero share and thin samples are not taken at face value.

What this deliberately ignores: lineups (a benched player still gets a share), penalties/set-piece roles, minutes played, and opposition-specific matchups. **Shares are the weakest input in the whole app** — international scoring samples are small, which is why the tab warns when a player has fewer than 5 appearances: at that point the share is mostly smoothing, not signal.

### Corners / shots on target: shrunk for/against rates

There is no corners or shots data in the local results dataset; it is collected from API-Football per-fixture statistics. The count model is one generic implementation:

1. Each finished fixture yields two records per stat: what each team produced (a FOR observation for that team, an AGAINST observation for its opponent).
2. Per-team FOR and AGAINST means are shrunk toward the global mean with weight `n / (n + k)` (`k = 5`, empirical-Bayes style) — small samples shrink harder.
3. Match expectations are multiplicative: `λ_home = for[home] × against[away] / global_mean` (mirrored for away). A team with no records at all falls back to the global mean outright.
4. Totals come from an independent Poisson grid over the two team counts, with push-aware over/under for integer lines.

Independence between the two teams' counts is an approximation (corners in particular are negatively correlated with possession dominance), and Poisson dispersion is assumed rather than fitted.

## Request costs and caching

All props data comes from API-Football (free tier: 100 requests/day; see [API keys](api-keys.md)). Responses are disk-cached at `~/.cache/wc26/apifootball/`, and a request is only spent on a cache miss.

| Button | First click | Repeat clicks |
|---|---|---|
| **Fetch player stats** | ~2–6 requests per team (1 team lookup + 1 per page of the squad list) | 0 for 24 hours (player stats TTL), then refreshed |
| **Collect team stats** | ≈ 2 × last_n requests (1 fixture-list + 1 statistics request per finished fixture, per team) | 0 — finished-fixture statistics are cached immutably |

Practical consequence: the count model **gets better the more you use it**. Every collected fixture stays on disk forever, so widening `last_n` or pricing more teams only costs the not-yet-cached fixtures.

The sidebar API-call counter increments once per button-triggered provider call; it counts calls made, not raw HTTP requests (cached calls may cost zero requests).

## Honest caveats

State these plainly before staking anything — they are stronger versions of the caveats in [methodology](methodology.md#honest-expectations):

- **Higher margins.** Bookmaker overround on player and stat props is materially higher than on main markets — typically well above the 2–5% seen on sharp 1X2/AH lines — so a larger model edge is needed just to break even.
- **Lower limits.** Prop stake limits are a fraction of main-market limits, capping any theoretical value.
- **No verified efficiency evidence.** Our research base ([methodology](methodology.md), [limitations](limitations.md)) contains **zero verified evidence** of exploitable inefficiency in prop markets. Everything this tab outputs is a fair price under stated assumptions, not a proven edge.
- **Scorer shares are thin.** International goal samples per player are small; a season at 2024/2025 club level mixes competitions and roles. The model does not know who starts.
- **Count data starts empty.** Rates are only as good as the fixtures collected so far. Early on, almost everything shrinks to the global mean.

## Thin-data warnings

The tab surfaces sample sizes instead of hiding them:

- **Scorer:** a warning when any player has fewer than 5 appearances — their share is dominated by the Laplace smoothing term.
- **Counts:** per-team sample metrics, with a warning when either team has fewer than 8 collected fixtures. A count of **0** means the team name did not match any collected record (e.g. provider naming differences, see troubleshooting) and the prediction is the global mean — a prior, not an estimate.

## Troubleshooting

**`Provider error: api-football … error: {'requests': 'You have reached the request limit for the day…'}`**
The free tier's 100 daily requests are exhausted. Both buttons fail gracefully with the API's error text; nothing is cached from a failed call. Wait for the daily reset (UTC midnight at api-sports.io) or upgrade the plan. Already-cached data keeps working — only cache misses need quota.

**`Provider unavailable — select api-football…`**
Props data requires the `api-football` provider. Select it in the sidebar and make sure `WC26_APIFOOTBALL_KEY` is exported in the shell that launched Streamlit (see [dashboard troubleshooting](dashboard.md#troubleshooting)).

**Team shows 0 samples / no player stats returned.**
The fixture dataset's team name (e.g. `United States`) may not match API-Football's (`USA`). The provider tries exact then fuzzy team lookup, but a miss returns no records and the model falls back to the global mean. Cross-check the name at api-sports.io.

**Cache location / reset.**
Props responses live at `~/.cache/wc26/apifootball/` (JSON files keyed by request hash). Delete the directory to force re-fetching — this will re-spend API requests:

```bash
rm -rf ~/.cache/wc26/apifootball
```

## See also

- [Dashboard](dashboard.md) — the rest of the web UI, sidebar settings, quota guidance.
- [Methodology](methodology.md) — the match model the scorer thinning is built on.
- [Limitations](limitations.md) — the full risk list.
- [API keys](api-keys.md) — obtaining and validating the API-Football key.
