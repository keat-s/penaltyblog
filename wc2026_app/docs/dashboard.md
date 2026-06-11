# Dashboard

Streamlit web app wrapping the same model, slate, and live-pricing logic as the CLI. Reading time: ~8 minutes.

## Install

Install Streamlit alongside the app's other dependencies:

```bash
pip install streamlit
```

Streamlit is not listed in `penaltyblog`'s core dependencies, so it is not pulled in by `pip install -e .`. Everything else (`pandas`, `numpy`, `scipy`) is already installed by the main install step in [Getting started](getting-started.md).

## Launch

Run from the `wc2026_app/` directory:

```bash
cd /path/to/penaltyblog/wc2026_app
streamlit run dashboard.py
```

Streamlit opens a browser tab at `http://localhost:8501`. The first load fits the model (~7 seconds cold, ~1 second warm cache). Subsequent visits with the same training inputs load from cache.

Before launching, make sure results data is fresh:

```bash
python -m wc26.cli update
```

## Sidebar controls

All tabs share the same sidebar settings.

| Control | Default | Effect |
|---|---|---|
| Bankroll (£) | 1000 | Stake sizing denominator. |
| Kelly fraction | 0.25 | Fractional Kelly multiplier. Quarter-Kelly is the default; do not exceed 0.5. |
| Minimum EV | 0.02 | Bets below this EV per unit stake are excluded from slates. |
| As-of date | today | Model trains only on matches before this date. |
| Model kind | `dixon_coles` | One of `dixon_coles`, `poisson`, `bivariate`, `negbin`. |
| Odds provider | `api-football` | One of `api-football`, `sportmonks`, `csv-upload`. |
| Live refresh interval (s) | 15 | How often the Live tab auto-refreshes when a provider key is set. |

**Key-status indicator.** Directly below the provider selector the sidebar shows whether the corresponding environment variable is set. It displays `set ✓` (green) or `missing` (yellow) — the key value itself is never shown. Selecting `csv-upload` shows `CSV upload — no API key needed` instead.

**API-call counter.** The sidebar also shows `API calls this session`: the total number of `odds` and `live_state` provider calls made since the page loaded. The counter resets on page reload.

## Tabs

### Fixtures

Displays model win/draw/loss, Over 2.5, and BTTS probabilities for upcoming WC2026 fixtures.

- **Days ahead** slider (1–14, default 7): controls how many days of fixtures are shown.
- The table formats probabilities as percentages (e.g. `51.2%`).
- No API key required; all data comes from the local results cache.

### Pre-match slate

Builds a Kelly-sized recommendation slate for selected fixtures.

1. Choose one or more fixtures from the **Select fixtures** multiselect.
2. Two paths to odds:

   **Option A — fetch from provider.** Click **Fetch odds & build slate**. The button is disabled until at least one fixture is selected. Each click calls the provider's `odds` endpoint once per selected fixture, incrementing the API-call counter. The provider and key are taken from the sidebar. If the provider is `csv-upload`, the key is missing, or the provider fails to initialise, an error is shown and Option B should be used instead.

   **Option B — upload odds CSV.** Upload a CSV file with columns `home`, `away`, `market`, `outcome`, `odds` (and optionally `line`, `bookmaker`). The full format is documented in [CLI reference](cli-reference.md#odds-csv-format). If fixtures are selected in the multiselect, only those matches are evaluated; otherwise every match in the CSV is evaluated.

The slate output shows total stake, number of candidates evaluated, and a recommendations table. If nothing clears the thresholds, `No +EV recommendations found with current settings.` is shown. This is the common case; see [Methodology](methodology.md#honest-expectations).

### Live

Reprices a match mid-game and, when odds are available, recommends in-play.

The tab works in two modes depending on whether a live API provider key is set.

**Provider mode (key set).** A `@st.fragment` auto-refreshes at the interval set in the sidebar. Each refresh calls the provider's `live_state` endpoint and, when the match is live, the `odds` endpoint as well — two API requests per tick, both incrementing the API-call counter (one request per tick when the match is not live). The fragment shows score, minute, red cards, win-probability bars (1X2 + Over 2.5), and any +EV recommendations.

**Manual fallback mode (key missing or `csv-upload` selected).** A warning banner reads `No live API provider available — using manual input mode.` A form accepts minute (0–120), home/away score, and home/away red cards. Submitting the form runs the live-pricing calculation locally using pre-match goal expectations conditioned on the entered state. No API call is made.

Fixture selection:

- The **Select today's fixture** dropdown lists fixtures from today's date. If no fixtures are scheduled today, it shows `(no fixtures today)`.
- The **Override home team / Override away team** text inputs take precedence over the dropdown if both are filled in. Use these for fixtures not in the local fixture data.

### Knockout

Computes the probability each side advances through a single knockout tie (90 minutes, extra time, and penalties).

| Control | Default | Notes |
|---|---|---|
| Home team / Away team | Argentina / France | Any team names in the results dataset. |
| Neutral venue | checked | Uncheck only if a genuine home-ground advantage applies. |
| Extra-time intensity factor | 1.0 | Multiplies pre-match scoring rates for the ET calculation. |
| Home penalty shootout win probability | 0.50 | Prior for the shootout leg only. |

Output includes advance probability and fair decimal odds for each side, a full phase-by-phase breakdown (win/draw/lose at 90', conditional ET outcomes, shootout prior), and optional to-qualify EV inputs where you can enter market odds and read the EV inline.

No API key is needed; the calculation runs entirely from the cached model.

## Quota guidance

The free tier for API-Football is 100 requests per day. See [API keys](api-keys.md) for details.

Actions that consume API requests:

- **Pre-match slate → Fetch odds & build slate**: one request per selected fixture, per button click.
- **Live tab auto-refresh**: two requests per refresh tick while the match is live (`live_state` + `odds`); one request per tick when the match is not live. Interval set in the sidebar, default 15 seconds.

Actions that do not consume API requests:

- Loading any tab (model runs locally).
- Using the CSV-upload path on the Pre-match slate tab.
- Using manual fallback mode on the Live tab.
- Anything on the Fixtures or Knockout tabs.

The API-call counter in the sidebar tracks total calls for the current page session. It resets on reload. Budget live-tab usage carefully on the free tier: at the 15-second default, a single live match watched for 45 minutes is ~180 refresh ticks at two requests each — roughly 360 requests, well over the 100/day free limit. At a 60-second interval the same 45 minutes is ~90 requests — just under the limit. Increase the refresh interval or switch to manual mode for light usage.

## Troubleshooting

**Provider key not recognised.**
Check that the environment variable is exported in the same shell that launched Streamlit:

```bash
export WC26_APIFOOTBALL_KEY=your_key_here
streamlit run dashboard.py
```

Variables set after `streamlit run` has started are not picked up; restart the server after changing them.

Environment variables:

| Provider | Variable |
|---|---|
| API-Football | `WC26_APIFOOTBALL_KEY` |
| Sportmonks | `WC26_SPORTMONKS_KEY` |

**Model refit on every load.**
The model cache lives at `~/.cache/wc26/models/`. If it is empty or stale, delete it to force a clean refit:

```bash
rm -rf ~/.cache/wc26/models
```

Then restart the dashboard. Both cache layers — the on-disk model cache and Streamlit's in-process `st.cache_resource` — are keyed on the training inputs (as-of date, model kind, results data), so revisiting the same inputs returns the same cached model; deleting `~/.cache/wc26/models` and restarting is the reliable way to force a refit. The in-process layer can also be cleared without a restart via **Clear cache** in the Streamlit menu (top-right).

**Stale results data.**
Refresh from the `wc2026_app/` directory before launching the dashboard:

```bash
python -m wc26.cli update
```

This re-downloads `~/.cache/wc26/results.csv`. The dashboard does not call `update` automatically.

**No fixtures shown in the Fixtures tab.**
The fixture window is driven by the as-of date in the sidebar. If the date is past the end of the tournament, no fixtures will match. Reset it to today.

## See also

- [Getting started](getting-started.md) — install, first run, model cache.
- [CLI reference](cli-reference.md) — the same logic as a command-line tool.
- [API keys](api-keys.md) — obtaining and validating provider keys.
- [Methodology](methodology.md) — model assumptions and honest expectations.
- [Limitations](limitations.md) — where the model is thin.
