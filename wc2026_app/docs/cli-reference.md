# CLI reference

Every command, flag, and the odds CSV format for `python -m wc26.cli`. Reading time: ~10 minutes.

All commands run from the `wc2026_app/` directory. The invocation form is:

```bash
python -m wc26.cli [GLOBAL FLAGS] <command> [COMMAND FLAGS]
```

Global flags must appear before the command. Command flags appear after it.

## Global flags

These apply to every command that fits a model (`fixtures`, `recs`, `live`, `advance`). `update` and `benchmark` ignore them.

| Flag | Default | Description |
|---|---|---|
| `--asof DATE` | today | Cutoff date (`YYYY-MM-DD`). The model trains only on matches before this date, and fixture windows start here. |
| `--years FLOAT` | `6.0` | Training window length in years before `--asof`. |
| `--model NAME` | `dixon_coles` | Goal model: `poisson`, `dixon_coles`, `bivariate`, or `negbin`. |
| `--no-cache` | off | Force a refit and bypass the on-disk model cache. |
| `--bankroll FLOAT` | `1000.0` | Bankroll for stake sizing. |
| `--kelly FLOAT` | `0.25` | Kelly fraction. Quarter-Kelly is the default; do not exceed `0.5`. See [methodology](methodology.md#staking). |
| `--min-ev FLOAT` | `0.02` | Minimum expected value per unit stake for a bet to enter the slate. |

## `update`

Download or refresh the international results data.

```bash
python -m wc26.cli update
```

Output:

```
results: 48000 rows, latest played 2026-06-09
```

Writes `~/.cache/wc26/results.csv`. Always re-downloads; run it before a session to pick up recent results.

## `fixtures`

Print model probabilities for upcoming World Cup fixtures.

| Flag | Default | Description |
|---|---|---|
| `--days N` | `7` | Fixture window length in days from `--asof`. |

```bash
python -m wc26.cli --asof 2026-06-11 fixtures --days 3
```

Output:

```
training on 5800 matches (asof 2026-06-11)
2026-06-12 Mexico v South Africa                       1X2 0.512/0.258/0.230  O2.5 0.541  BTTS 0.518
2026-06-13 Canada v Croatia                            1X2 0.331/0.279/0.390  O2.5 0.567  BTTS 0.561
```

Each line shows home/draw/away win probabilities, the Over 2.5 probability, and the both-teams-to-score probability. Venue neutrality is read from the fixture data.

## `recs`

Produce a Kelly-sized recommendation slate from an odds CSV.

| Flag | Default | Description |
|---|---|---|
| `--odds-file PATH` | required | Path to the odds CSV. |
| `--days N` | `7` | Fixture window used to resolve each match's neutral-venue flag. |

```bash
python -m wc26.cli --asof 2026-06-11 recs --odds-file odds.csv --bankroll 1000 --kelly 0.25 --min-ev 0.02
```

Output:

```
training on 5800 matches (asof 2026-06-11)

2 recommendations (bankroll 1000):
  Mexico v South Africa | 1x2 home @ 2.25 | model p=0.512 fair=0.476 ev=+0.152 tier=medium | stake 38.00 (3.80%)
  Canada v Croatia | ah -0.50 away @ 2.00 | model p=0.390 ev=+0.111 tier=low | stake 22.50 (2.25%)

total staked: 60.50
```

Each recommendation line reads: `match | market [line] outcome @ price | model p=<model prob> [fair=<de-vigged market prob>] ev=<EV per unit> tier=<variance tier> | stake <amount> (<fraction of bankroll>)`.

Behaviour notes:

- A match in the odds file but not in the fixture window prints a warning and is priced as a neutral-venue game. Spell team names exactly as the results dataset spells them.
- `total staked` is capped at 15% of the bankroll across the whole slate.
- An empty slate prints `no +EV recommendations at current thresholds`.

## `live`

Reprice a match mid-game and (optionally) recommend in-play. The model is not refit; pre-match goal expectations are conditioned on the live state. See [methodology](methodology.md#in-play-conditional-pricing).

| Flag | Default | Description |
|---|---|---|
| `--home NAME` | required | Home team. |
| `--away NAME` | required | Away team. |
| `--provider NAME` | `manual` | `manual`, `api-football`, or `sportmonks`. |
| `--minute FLOAT` | — | Match minute. Required with `--provider manual`. |
| `--score H-A` | — | Current score, e.g. `1-0`. Required with `--provider manual`. |
| `--reds H-A` | `0-0` | Red cards per side, e.g. `0-1`. |
| `--not-neutral` | off | Treat the match as non-neutral (home advantage applies). |
| `--odds-file PATH` | — | Odds CSV for in-play recommendations. |

Manual state:

```bash
python -m wc26.cli --asof 2026-06-11 live --home Mexico --away "South Africa" \
    --not-neutral --minute 60 --score 0-1 --reds 0-1 --odds-file live_odds.csv
```

Output:

```
training on 5800 matches (asof 2026-06-11)
Mexico v South Africa 0-1 @ 60.0' -> 1X2 0.331/0.297/0.372
  Mexico v South Africa | 1x2 home @ 3.50 | model p=0.331 ev=+0.159 tier=medium | stake 15.20 (1.52%)
```

Provider-fed state (fetches minute, score, and red cards live; see [API keys](api-keys.md)):

```bash
python -m wc26.cli live --home Mexico --away "South Africa" --provider api-football
```

With a provider, `--minute`, `--score`, and `--reds` are ignored — the provider supplies them, and the line `[api-football] 60' 0-1 reds 0-1` is printed first. If no `--odds-file` is given, the same provider instance is reused to fetch in-play odds.

## `advance`

Knockout tie: probability each side advances, including extra time and penalties. See [methodology](methodology.md#knockout-extra-time-and-penalties).

| Flag | Default | Description |
|---|---|---|
| `--home NAME` | required | Home/first team. |
| `--away NAME` | required | Away/second team. |
| `--not-neutral` | off | Treat as non-neutral. |
| `--et-factor FLOAT` | `1.0` | Multiplier on extra-time scoring rates. |
| `--pens-home FLOAT` | `0.5` | Prior probability the home side wins a shootout. |
| `--odds DECIMAL,DECIMAL` | — | To-qualify decimal odds `home,away` for EV. |

```bash
python -m wc26.cli advance --home Brazil --away Morocco --odds 1.55,2.45
```

Output:

```
training on 5800 matches (asof 2026-06-11)
Brazil v Morocco (knockout)
  90': 0.512/0.262/0.226  ET (if drawn): 0.402/0.430/0.168  pens(home): 0.50
  advance: Brazil 0.681 (fair 1.47) | Morocco 0.319 (fair 3.13)
  to-qualify EV: Brazil @ 1.55 -> +0.055 | Morocco @ 2.45 -> -0.219
```

## `benchmark`

Measure real provider latency with your API key. Run this before trusting any vendor latency claim. See [API keys](api-keys.md#benchmark-first).

| Flag | Default | Description |
|---|---|---|
| `--provider NAME` | required | `api-football` or `sportmonks`. |
| `--home NAME` | required | Home team. |
| `--away NAME` | required | Away team. |
| `--polls N` | `20` | Number of polls. |
| `--interval FLOAT` | `5.0` | Seconds between polls. |
| `--odds` | off | Also poll the odds endpoint each cycle. |

```bash
python -m wc26.cli benchmark --provider api-football --home Mexico \
    --away "South Africa" --polls 20 --interval 5 --odds
```

Output:

```
benchmarking api-football: 20 polls @ 5.0s ...
api-football: 19/20 polls ok, 1 errors
  rtt: median 240ms  p95 410ms  max 612ms
  payload changes observed: 3
  gap between changes: median 14.8s  min 9.3s
  note: change cadence only meaningful while the match is in play
```

Change cadence is only meaningful while the match is actually live.

## Odds CSV format

Required columns: `home`, `away`, `market`, `outcome`, `odds`. Optional columns: `line`, `bookmaker`.

| Column | Required | Notes |
|---|---|---|
| `home` | yes | Home team, spelled as in the results dataset. |
| `away` | yes | Away team, spelled as in the results dataset. |
| `market` | yes | One of the markets below. |
| `outcome` | yes | Outcome for the market (see table). |
| `odds` | yes | Decimal odds. |
| `line` | for `ou`, `ah` | Goal line or handicap. Leave blank for other markets. |
| `bookmaker` | no | Bookmaker name. Enables line shopping and Pinnacle anchoring. |

### Markets and outcomes

| `market` | `outcome` values | `line` | Variance tier |
|---|---|---|---|
| `1x2` | `home`, `draw`, `away` | — | medium |
| `ou` | `over`, `under` | required (e.g. `2.5`) | medium |
| `ah` | `home`, `away` | required (e.g. `-0.5`) | low |
| `btts` | `yes`, `no` | — | medium |
| `dnb` | `home`, `away` | — | low |
| `dc` | `1x`, `x2`, `12` | — | low |
| `exact` | a scoreline string, e.g. `2-1` | — | high |

### Multi-bookmaker line shopping

List one row per bookmaker per outcome. The engine takes the **best (highest) price** per `(market, line, outcome)` for the EV calculation — best-vs-average price routing is a first-order profit driver. For fair (de-vigged) probabilities, the engine de-vigs one bookmaker's complete outcome set, preferring Pinnacle when present and otherwise the lowest-margin complete set.

```csv
home,away,market,outcome,line,odds,bookmaker
Mexico,South Africa,1x2,home,,2.10,pinnacle
Mexico,South Africa,1x2,draw,,3.40,pinnacle
Mexico,South Africa,1x2,away,,3.80,pinnacle
Mexico,South Africa,1x2,home,,2.25,bet365
Mexico,South Africa,1x2,home,,2.18,williamhill
```

Here the EV uses bet365's `2.25` (best home price) while the fair probability is anchored to Pinnacle's complete `home/draw/away` set.

> **Note**: Double chance (`dc`) is never de-vigged. Its outcomes overlap (`1x` and `x2` share the draw), so margin removal across them is meaningless. Derive double-chance fair values from the de-vigged 1X2 set if you need them.

## See also

- [Getting started](getting-started.md)
- [API keys](api-keys.md)
- [Methodology](methodology.md)
- [Limitations](limitations.md)
