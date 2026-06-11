# Limitations

What the model does not know, what it does not claim, and where it can mislead you. Reading time: ~7 minutes.

Read this alongside [methodology § honest expectations](methodology.md#honest-expectations). Nothing here is a configuration that produces "high profit, low risk" — no such configuration exists. Evidence citations point to `.omc/research/wc2026-deep-research.md`.

## Host calibration is thin

The three hosts (United States, Mexico, Canada) skip qualification. Their only recent matches are friendlies, which carry less signal than competitive games. The model keeps host friendlies at full weight to avoid starving itself of host data (see [methodology](methodology.md#training-data-and-weighting)), but this is a compensation, not a fix. **Host ratings are the most uncertain in the model.** Treat host-team value signals with extra scepticism, and expect host probabilities to move most as real tournament data arrives.

No verified evidence quantifies Dixon-Coles accuracy degradation on international data specifically — this is a genuine gap. International tournaments are also a known regime for **overestimated** win probabilities (§5), which is the asymmetrically punished error under Kelly staking.

## Vendor-latency claims are not your latency

Every coverage and latency figure published by API-Football, Sportmonks, and TheStatsAPI is vendor-marketing self-description, not an independent benchmark (§3). The vendor's "<15s" or "~5s refresh" describes their internal pipeline floor, not the end-to-end latency your process sees.

Run `benchmark` with your own key against a live match before trusting any of it (see [API keys](api-keys.md#benchmark-first)). The measured gap between payload changes is the real update floor. Because that floor is always greater than zero, the market reprices before you observe the event — latency-arbitrage is ruled out and in-play use is confined to model-based repricing.

## Unverified Sportmonks clock semantics

The Sportmonks adapter computes the match minute as `counts_from + minutes`, where `minutes` is period-local and `counts_from` anchors it to the match clock (e.g. 45 for the second half). The vendor docs do not show a worked example of `counts_from`, so this is an inference. **Verify it against a real trial-key payload** before trusting in-play minutes from Sportmonks; an off-by-a-half error feeds a wrong remaining-time fraction into the live grid. API-Football's `elapsed` field is verified by contrast.

## In-play latency and the absence of realized-ROI evidence

The in-play module (`live.py`) is the most speculative part of the app:

- The rising-intensity drift (`0.55`/90min), red-card multipliers (`0.70`/`1.65`), and yellow-card omission are literature-derived and directionally validated (the red-card asymmetry is replicated on World Cup matches 1998–2014), but the specific defaults are **not backtested in this app** (§4).
- **No verified evidence demonstrates realized in-play betting ROI** for models like this against modern books. The literature validates model fit and market-consistency, not net-of-margin profitability.
- The constant 15-second-plus data floor means model-based repricing only — no event-racing.

Do not present or treat in-play picks with the same confidence as pre-match recommendations. Backtest before staking real money.

## Knockout extra-time and penalty assumptions are unvalidated

Research found **no verified evidence** on pricing extra time or penalty shootouts (§5). The `advance` command therefore makes explicit, configurable assumptions rather than claiming accuracy:

- Extra time is a scaled Poisson mini-match that ignores conditioning on "90' was a draw" (drawn games skew toward closely-matched or low-scoring states, so true ET rates may run lower).
- Penalties default to a coin flip.

These are reasonable defaults, not validated estimates. Tune `--et-factor` and `--pens-home` if you have better priors, and treat to-qualify EV as indicative.

## Single-tournament variance

A ~104-match tournament is far too small for a true edge to express itself. Single-season results for an identical strategy range roughly ±30% ROI purely from variance, and under fully efficient markets there is a >75% chance of "discovering" a significant single-season bias by Type I error alone (§2, §5). **Any edge that appears to exist on one tournament's data is presumptively noise.** A losing tournament at genuine +EV is roughly a 1-in-5 outcome, and 10-loss streaks are normal.

## Bookmaker limiting of winners

The realized value is at **soft books**, which discourage and ban consistently winning accounts. Sharp books (Pinnacle-style, AH-centric) accept winners but offer thin, near-efficient prices (§1, §5). A user who wins consistently should expect soft-book limiting. The verified evidence establishes the structural distinction, not the speed or thresholds of limiting.

## Market-efficiency bounds

Across 14 seasons, 5 leagues, ~51k observations, inefficiencies appear only in isolated single seasons and are not persistent or systematic. Margins have roughly halved to ~5% while predictive accuracy held or improved (§5). The model's edge, where it exists, is a few percent of turnover bounded by margin and market efficiency. Sharp closing lines are close to efficient. Closing-line value is the correct proxy metric for edge where realized ROI has not converged.

## What the app does not claim

- No outright-tournament-winner profit claims. The supporting study was refuted in adversarial review (§1, §5).
- No arbitrage between Asian Handicap and 1X2.
- No "high profit, low risk" framing anywhere. "Lower risk" in this project means **lower variance** (AH/DNB tiers, diversity caps, quarter-Kelly, the 15% slate cap) — not certainty. There are no risk-free bets.

## Responsible gambling

Betting carries real financial risk. This app is a discipline and analysis tool, not a guarantee of profit, and a positive expected value does not prevent — or even make unlikely — a losing tournament. Only stake money you can afford to lose. Set limits before you start and keep to them. If gambling stops being something you control, seek help: in the US call 1-800-GAMBLER; in the UK contact GamCare (<https://www.gamcare.org.uk>) or the National Gambling Helpline on 0808 8020 133. Equivalent services exist in most jurisdictions.

## See also

- [Methodology](methodology.md) — the full pipeline and the evidence behind each choice.
- [API keys](api-keys.md) — provider setup and the benchmark step.
- [Getting started](getting-started.md)
