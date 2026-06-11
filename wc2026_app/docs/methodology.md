# Methodology

How the app turns international results into a sized recommendation slate, with the evidence behind each design choice. Reading time: ~15 minutes.

Read the [honest-expectations section](#honest-expectations) before staking anything. Evidence citations below point to the deep-research report at `.omc/research/wc2026-deep-research.md`, which records the source URL for each verified claim.

## Pipeline overview

```
international results (martj42 CSV, free)
        │  time-decay weights, friendly down-weighting (hosts exempt),
        │  per-match neutral_venue flags
        ▼
penaltyblog goal model (Dixon-Coles default)
        ▼
FootballProbabilityGrid ──> model probability for any market
bookmaker odds CSV ──> de-vig (power method, favourite-longshot aware)
        ▼
edge engine (EV per unit, push-aware) ──> diversity filter ──> fractional Kelly
        ▼
recommendation slate
```

Each stage is described below. The defensible product is a **discipline tool**: bias-aware de-margining, Pinnacle-anchored value detection, best-price routing, quarter-Kelly stakes, longshot filters, and variance warnings.

## Training data and weighting

Source: martj42/international_results — every international since 1872, with future WC2026 fixtures (blank scores) and a per-match `neutral` flag. The flag maps directly onto penaltyblog's `neutral_venue` input.

`data.training_data` builds the model inputs from matches in a window before `--asof` (default 6 years):

- **Exponential time decay.** Each match is weighted `exp(-xi * days_ago)` with `xi = 0.0019`. Recent matches dominate; a match ~1 year old keeps ~50% weight, ~2 years ~25%.
- **Friendly down-weighting.** Friendlies carry less signal than competitive matches and are weighted `0.6`. Competitive matches (World Cup, qualification, Copa, Euro, Nations League, Cup of Nations, Gold Cup, Asian Cup) keep weight `1.0`.
- **Host exemption.** The three hosts (United States, Mexico, Canada) skip qualification, so friendlies are their only recent matches. Down-weighting those would starve the model of host signal. Friendlies involving a host keep full weight (`host_friendly_weight = 1.0`). Host ratings remain the most uncertain in the model regardless; see [limitations](limitations.md#host-calibration-is-thin).
- **Neutral venue.** Each match's `neutral` flag is passed through so the model removes home advantage where it does not apply. World Cup matches are neutral except for host games.

## The goal model

`model.fit_model` fits a penaltyblog goal model on the weighted, neutral-aware inputs. The default is **Dixon-Coles**; `poisson`, `bivariate`, and `negbin` are also available via `--model`.

`model.predict_fixture` produces a `FootballProbabilityGrid` — a matrix of scoreline probabilities — for any pairing. The grid is the single source of every market probability.

Fitted models are cached (`cache.fit_cached`) keyed by a SHA-256 hash of the model kind plus the exact training arrays (goals, teams, rounded weights, neutral flags). Identical inputs load instantly; any change in data or config produces a new key and a fresh fit. See [getting started](getting-started.md#where-the-model-cache-lives).

## Market pricing from the scoreline grid

`markets.model_probs` maps any `(market, outcome, line)` onto a `(p_win, p_push)` pair read off the grid, so downstream EV and Kelly logic is uniform:

```
EV = p_win * odds + p_push - 1     (a push refunds the stake)
```

| Market | Source on the grid | Push |
|---|---|---|
| `1x2` | `home_win` / `draw` / `away_win` | none |
| `ou` | `totals(line)` | on integer lines |
| `ah` | `asian_handicap_probs(outcome, line)` | quarter/half-goal pushes handled |
| `btts` | `btts_yes` / `btts_no` | none |
| `dnb` | `home_win` / `away_win`, push on the draw | the draw |
| `dc` | `double_chance_1x` / `x2` / `12` | none |
| `exact` | `exact_score(h, a)` | none |

Markets carry a variance tier used later for diversity: `ah`/`dnb`/`dc` are **low**, `ou`/`1x2`/`btts` are **medium**, `exact` is **high**.

## De-vigging: bias-aware, Pinnacle-anchored

Bookmaker odds embed a margin (overround). To recover a fair probability you must remove it — but **how** you remove it matters.

### Why multiplicative (equal-margin) de-vig is wrong

Naive equal-proportional de-margining assumes the margin is spread evenly across outcomes. Bookmakers do not do this: they **load margin onto longshots** (the favourite-longshot bias). Equal-margin de-vig therefore overstates longshot fair probabilities and manufactures false value. In a sample of 111,909 odds, the equal-margin model flagged 3,957 "value" bets that all three bias-aware methods rejected ([football-data.co.uk, Wisdom of the Crowd](https://www.football-data.co.uk/The_Wisdom_of_the_Crowd_updated.pdf), via `.omc/research/wc2026-deep-research.md` §5).

The app therefore defaults to the bias-aware **power** method (`edge.DEFAULT_DEVIG_METHOD = "power"`), via penaltyblog's `calculate_implied`.

### Pinnacle anchoring

`edge.build_candidates` de-vigs one bookmaker's **complete** outcome set per `(market, line)`. When a sharp book (Pinnacle) quotes the complete set, it is preferred: Pinnacle's de-margined closing odds are close to efficient, so its de-vigged probabilities are the best available proxy for true probabilities. A 5% price edge over Pinnacle's implied true price realizes ≈5% ROI over the long run; the reverse (anchoring to soft books) carries essentially no information ([football-data.co.uk](https://www.football-data.co.uk/The_Wisdom_of_the_Crowd_updated.pdf), §1, §6). When no sharp book is present, the lowest-margin complete set is used.

Double chance is excluded from de-vigging because its outcomes overlap.

### Line shopping

The EV uses the **best (highest) price** across all bookmakers for each outcome, independent of which book anchors the fair probability. Taking best-available rather than average odds increased profits by 42–296% in backtests ([SAGE / JSA-200588](https://journals.sagepub.com/doi/10.3233/JSA-200588), §1, §6) — a first-order effect, worth more than marginal model refinement. See the [odds CSV format](cli-reference.md#multi-bookmaker-line-shopping).

## Edge and EV

Each `Candidate` (`edge.Candidate`) exposes:

- `ev = p_win * odds + p_push - 1` — expected value per unit stake, push-aware.
- `p_eff = p_win / (1 - p_push)` — win probability conditional on not pushing, used for Kelly.
- `edge_vs_market = p_eff - fair_prob` — model minus de-vigged market probability, when a complete market is present.

## Selection: longshot guardrail and diversity

`recommend.select_diverse` filters and diversifies:

- **EV floor.** Keep only `ev >= min_ev` (default `0.02`).
- **Longshot guardrail.** Drop candidates with `p_eff < min_prob` (default `0.10`). Bookmakers price longshots **more** accurately than favourites (lower Brier) and load margin onto them, so model "value" below ~10% win probability is the most likely false-signal class — a 12.0-odds group-stage upset is the single most likely false positive ([Buhagiar et al.](https://www.sciencedirect.com/science/article/abs/pii/S2214635018300285); [JGBE 630](https://www.ubplj.org/index.php/jgbe/article/view/630), §1, §5).
- **No both-sides.** At most one bet per `(match, market, line)`; the higher-EV side wins.
- **Per-match cap.** At most `max_per_match` (default 2) bets on one game, limiting correlated exposure.
- **Per-tier caps.** Defaults `{low: 6, medium: 6, high: 2}`, capping how many high-variance (e.g. `exact`) bets reach the slate.

The selection sorts by EV descending and fills under the caps.

## Staking: quarter-Kelly with a slate cap

`recommend.size_stakes` sizes each selected bet with independent fractional Kelly (penaltyblog's `kelly_criterion`) on its push-conditional win probability:

- Bets across different matches are independent events, not mutually exclusive outcomes of one market, so each gets its own Kelly stake.
- **Quarter-Kelly default** (`kelly_fraction = 0.25`). Full Kelly assumes the edge estimate is exact; because the edge is an estimate, overbetting turns long-run growth negative while underbetting only slows it — the penalty is asymmetric. Quarter-Kelly cuts variance enough that a deep drawdown becomes informative evidence that the edge is not real. No Kelly fraction saves an illusory edge ([Wikipedia, Kelly criterion](https://en.wikipedia.org/wiki/Kelly_criterion); [Crane](https://harrycrane.substack.com/p/two-arguments-for-fractional-kelly); [Downey/Thorp](https://matthewdowney.github.io/uncertainty-kelly-criterion-optimal-bet-size.html), §2). Configurable via `--kelly` up to `0.5`; do not exceed it.
- **15% slate cap.** If summed stakes exceed `max_total_stake` (default `0.15` of bankroll), the whole slate is scaled down proportionally.

International tournaments are a known regime for **overestimated** win probabilities. Where model and market disagree most, the honest response is a smaller relative stake, not a larger one ([Kelly](https://en.wikipedia.org/wiki/Kelly_criterion), §5).

## In-play conditional pricing

`live.live_grid` reprices a match mid-game **without refitting**. It takes the pre-match goal expectations, scales them by remaining time and live state, builds the remaining-goals Poisson grid, and shifts it by the current score. The result is an ordinary `FootballProbabilityGrid`, so every market reprices for free.

Parameter provenance (`.omc/research/wc2026-deep-research.md` §4):

- **Rising intensity.** Scoring intensity is not constant: it rises through a match. A constant-λ model systematically underprices late goals. The app models λ(t) as proportional to `1 + drift * t/T` with `drift = 0.55` per 90 minutes ([JRSS-D, Dixon-Robinson](https://academic.oup.com/jrsssd/article-abstract/47/3/523/7123296); [arXiv:1811.03931](https://arxiv.org/pdf/1811.03931)). `remaining_fraction` integrates this rising rate over the remaining time.
- **Red cards: asymmetric, side-specific, multiplicative.** The sanctioned side's scoring rate falls and the opponent's rises. Defaults: `RED_CARD_OWN = 0.70` (sanctioned side) and `RED_CARD_OPP = 1.65` (opponent), applied per red card. The asymmetric direction is replicated specifically on FIFA World Cup matches 1998–2014 ([Titman, Lancaster](https://www.maths.lancs.ac.uk/~titman/football_rss.pdf); [Springer, Empirical Economics](https://link.springer.com/article/10.1007/s00181-017-1287-5)).
- **Yellow cards are ignored** — they carry no scoring-rate signal worth modelling ([Titman](https://www.maths.lancs.ac.uk/~titman/football_rss.pdf)).

These defaults are literature-derived but **not backtested in this app**. In-play is the most speculative module; no verified evidence shows realized in-play ROI net of margin. See [limitations](limitations.md#in-play-latency-and-the-absence-of-realized-roi-evidence).

## Knockout: extra time and penalties

Dixon-Coles outputs are 90-minute probabilities. For a knockout tie the question is "who advances", which needs an explicit extra-time and penalty layer (`knockout.advance_probabilities`):

```
P(advance) = P(win 90') + P(draw 90') * [P(win ET) + P(draw ET) * P(win pens)]
```

Research found **no verified evidence** on pricing ET or penalties, so this layer makes its assumptions explicit and configurable rather than claiming accuracy ([§5](limitations.md#knockout-extra-time-and-penalty-assumptions-are-unvalidated)):

- **Extra time** is a 30-minute mini-match with independent Poisson goals at the pre-match rates scaled by `30/90`, times `et_factor` (default `1.0`, `--et-factor`). Conditioning on "90' was a draw" is ignored; if anything ET rates run lower than this assumes.
- **Penalties** default to a coin flip (`pens_home = 0.5`, `--pens-home`). Plug in a shootout prior if you have one.

## Honest expectations

State these plainly to yourself before staking. There is no "high profit, low risk" configuration; the verified efficiency literature is unambiguous that persistent systematic inefficiency does not exist in modern 1X2 markets (`.omc/research/wc2026-deep-research.md` §2, §5).

- **ROI ceiling ~3–5% of turnover**, realized only across many bets. Pinnacle-anchored value at soft books realizes expected value roughly 1:1 in the long run, and a realistic systematic edge is low single digits per bet, not double digits ([football-data.co.uk](https://www.football-data.co.uk/The_Wisdom_of_the_Crowd_updated.pdf); [RebelBetting](https://www.rebelbetting.com/faq/expected-value-and-variance)).
- **A losing tournament at +EV is roughly 1-in-5.** ~104 matches is far too small to converge; even genuine value bettors placing 100+ bets are unprofitable in about 1 of 5 such periods ([RebelBetting](https://www.rebelbetting.com/faq/expected-value-and-variance)).
- **Long losing streaks are normal.** Staking must survive a 10-loss run.
- **Single-tournament results carry almost no signal.** A season-sized sample for an identical strategy can range roughly ±30% ROI purely from variance ([SAGE 15270025231204997](https://journals.sagepub.com/doi/10.1177/15270025231204997)).
- **Closing-line value is the right proxy for edge** where realized ROI has not converged. Track it; a drawdown beyond the quarter-Kelly envelope is evidence the edge is not real — stop, do not chase.
- **In-play is unvalidated.** Do not treat in-play picks with the same confidence as pre-match.

See [limitations](limitations.md) for the full risk list and a responsible-gambling note.

## See also

- [CLI reference](cli-reference.md)
- [Limitations](limitations.md)
- [Getting started](getting-started.md)
