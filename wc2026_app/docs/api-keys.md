# API keys

How to obtain and configure keys for the live data providers, and how to validate them before the tournament. Reading time: ~6 minutes.

The app fits its model entirely on free data ([martj42/international_results](https://github.com/martj42/international_results)). API keys are only needed for the `live` and `benchmark` commands, which fetch in-play match state and odds. You can use the app for pre-match work without any key.

Two providers are integrated. A third is documented but deliberately not integrated.

| Provider | Status | Free tier | Env var |
|---|---|---|---|
| API-Football (api-sports.io) | Integrated, endpoints verified | 100 req/day | `WC26_APIFOOTBALL_KEY` |
| Sportmonks | Integrated, endpoints verified | None for WC2026 (14-day trial) | `WC26_SPORTMONKS_KEY` |
| TheStatsAPI | Not integrated | None (7-day trial) | — |

## API-Football (primary)

Use the direct api-sports.io product, **not** the RapidAPI variant. The adapter authenticates with the `x-apisports-key` header against `https://v3.football.api-sports.io`, which is the direct product's scheme; the RapidAPI listing uses different headers and a different base URL and will not work.

1. Create an account at <https://dashboard.api-football.com>. Expected result: you land on the dashboard.
2. Open the dashboard's account or profile section and copy the API key shown there.
3. Confirm the free tier suits your needs: 100 requests per day. Live state plus odds is roughly two requests per poll, so budget your polling accordingly.
4. Export the key:

   ```bash
   export WC26_APIFOOTBALL_KEY=your_key_here
   ```

5. Validate it (see [Benchmark first](#benchmark-first)).

## Sportmonks (secondary)

1. Sign up at <https://my.sportmonks.com>.
2. Confirm WC2026 coverage requires a paid plan or the 14-day free trial. WC2026 is not on the free plan. Start the trial or subscribe.
3. Copy the API token from your Sportmonks dashboard.
4. Export it:

   ```bash
   export WC26_SPORTMONKS_KEY=your_token_here
   ```

5. Validate it (see [Benchmark first](#benchmark-first)).

> **Note**: Sportmonks rate limits are per-entity, per-hour. A `429` response carries a `retry_after` value. The `minute` field is period-local and the adapter anchors it to the match clock using `counts_from`; this `counts_from` semantics is not shown in a worked example in the vendor docs, so verify it against a real trial-key payload. See [limitations](limitations.md#unverified-sportmonks-clock-semantics).

## Why TheStatsAPI is not integrated

TheStatsAPI advertises attractive coverage (all 104 WC2026 matches, odds including Pinnacle and Betfair Exchange, confirmed XIs ~75 minutes pre-kickoff). It is not integrated for three reasons:

- **Unverified JSON shapes.** It publishes no public API reference (the docs URL returns 404). The response shapes are known only from vendor marketing and a blog post, which is not enough to build a reliable adapter.
- **No free tier.** Access is a 7-day trial, then $50/month.
- **Cost of verification.** Confirming the shapes requires a paid trial key first.

If you obtain a trial key and confirm the shapes, an adapter can be added following the pattern in `wc26/providers/`. Until then, do not rely on it. Details are in `.omc/research/vendor-api-specs.md`.

## Benchmark first

Vendor latency claims (Sportmonks "<15s", API-Football "~5s refresh") describe the vendor's internal pipeline, not the latency your process actually sees. As soon as a key is set, run `benchmark` to measure real round-trip time and how often the live payload actually changes:

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

Run this against a match that is actually in play; change cadence is meaningless otherwise. The measured gap between payload changes is the real floor on in-play update latency for that provider and key. Because this floor is always larger than zero, the market reprices before you see the event — latency-arbitrage is not viable, and in-play use is confined to model-based repricing. See [methodology](methodology.md#in-play-conditional-pricing) and [limitations](limitations.md#in-play-latency-and-the-absence-of-realized-roi-evidence).

## Using a key

Once a key is exported, point the `live` command at the provider:

```bash
python -m wc26.cli live --home Mexico --away "South Africa" --provider api-football
```

The provider supplies the minute, score, and red cards; the model reprices and (if odds are available) recommends. See the [CLI reference](cli-reference.md#live).

You can also pass a key explicitly in Python rather than via the environment:

```python
from wc26.providers import make_provider

provider = make_provider("api-football", api_key="your_key_here")
state = provider.live_state("Mexico", "South Africa")
```

## See also

- [CLI reference](cli-reference.md) — the `live` and `benchmark` commands.
- [Limitations](limitations.md) — vendor-latency and Sportmonks-clock caveats.
