# wc26 — World Cup 2026 Betting Recommendations

Betting-recommendation app built on [penaltyblog](https://github.com/martineastwood/penaltyblog):
fits goal models on international results, prices every market from one scoreline
grid, compares against de-vigged bookmaker odds, and sizes a diverse slate with
fractional Kelly. Includes in-play conditional repricing.

## How it works

```
international results (martj42 CSV, free)
        │  time-decay weights, friendly down-weighting (hosts exempt),
        │  per-match neutral_venue flags
        ▼
penaltyblog goal model (Dixon-Coles default)
        ▼
FootballProbabilityGrid ──> model probability for any market
        │                       (1X2, AH, totals, BTTS, DNB, DC, exact)
bookmaker odds CSV ──> de-vig (power method, favourite-longshot aware)
        ▼
edge engine (EV per unit, push-aware) ──> diversity filter ──> fractional Kelly
        ▼
recommendation slate
```

In-play: pre-match goal expectations are conditioned on (minute, score, red
cards) — no refit — producing a new grid so every market reprices live.

## Usage

```bash
python -m wc26.cli update                          # refresh results data
python -m wc26.cli --asof 2026-06-11 fixtures      # model 1X2 for upcoming WC games
python -m wc26.cli --asof 2026-06-11 recs --odds-file odds.csv --bankroll 1000
python -m wc26.cli --asof 2026-06-11 live --home Mexico --away "South Africa" \
    --not-neutral --minute 60 --score 0-1 --reds 0-1 --odds-file live_odds.csv
# knockout: P(advance) incl. extra time + penalties, optional to-qualify EV
python -m wc26.cli advance --home Brazil --away Morocco --odds 1.55,2.45
```

Odds CSV columns: `home,away,market,outcome,line,odds[,bookmaker]`. Markets: `1x2`
(home/draw/away), `ou` (over/under + line), `ah` (home/away + line), `btts`
(yes/no), `dnb` (home/away), `dc` (1x/x2/12), `exact` ("2-1"). Multiple
bookmaker rows per outcome → best price is taken; fair probs anchored to
Pinnacle's set when present.

Fitted models are cached in `~/.cache/wc26/models` keyed by training-input
hash (first run ~7s, then ~1s); `--no-cache` forces a refit.

## Live providers

```bash
export WC26_APIFOOTBALL_KEY=...   # api-sports.io, free tier 100 req/day
export WC26_SPORTMONKS_KEY=...    # WC2026 needs paid plan / 14-day trial

# auto-fetch live state + in-play odds, then recommend
python -m wc26.cli live --home Mexico --away "South Africa" --provider api-football

# measure real latency before trusting vendor claims
python -m wc26.cli benchmark --provider api-football --home Mexico \
    --away "South Africa" --polls 20 --interval 5 --odds
```

Adapters: `api-football` (endpoints fully verified from official docs),
`sportmonks` (verified from docs.sportmonks.com). TheStatsAPI is documented in
`.omc/research/vendor-api-specs.md` but not integrated — its JSON shapes are
vendor-marketing-only; confirm with a trial key first. Vendor latency claims
describe their pipelines, not yours: run `benchmark` with your key.

## Honest framing

- There are no risk-free bets. Edges are model-vs-market opinions bounded by
  bookmaker margin and market efficiency; sharp closing lines are close to
  efficient.
- "Lower risk" here means lower variance (AH/DNB tiers, diversity caps,
  quarter-Kelly, slate cap at 15% of bankroll) — not certainty.
- Red-card and late-game multipliers in `live.py` are uncalibrated defaults;
  backtest before staking real money.
- Hosts (USA/Mexico/Canada) skip qualification, so their recent data is
  friendly-heavy; `training_data` keeps host friendlies at full weight to
  compensate, but host ratings remain the most uncertain.

## Tests

```bash
cd wc2026_app && python -m pytest tests/
```

## Documentation

Full documentation lives in [`docs/`](docs/):

- [Getting started](docs/getting-started.md) — prerequisites, install, first run, cache, timings.
- [CLI reference](docs/cli-reference.md) — every command, flag, and the odds CSV format.
- [API keys](docs/api-keys.md) — obtaining and validating live-provider keys.
- [Methodology](docs/methodology.md) — the full pipeline with cited evidence.
- [Limitations](docs/limitations.md) — where the model is thin and what it does not claim.
