# Getting started

Install the dependencies, fetch the results data, and produce your first model output and recommendation slate. Reading time: ~6 minutes.

## Prerequisites

- Python 3.10 or newer.
- A C compiler. `penaltyblog` ships Cython extensions that are built at install time. macOS: Xcode command-line tools (`xcode-select --install`). Debian/Ubuntu: `build-essential`.
- The `penaltyblog` repository checked out. This app lives inside it at `wc2026_app/` and imports `penaltyblog` directly.

## Install

Install `penaltyblog` in editable mode from the repository root. This compiles the Cython extensions and pulls in `numpy`, `pandas`, and `scipy`, which the app also uses.

```bash
cd /path/to/penaltyblog
pip install -e .
```

Expected result: the build finishes without errors and `python -c "import penaltyblog"` succeeds.

> **Note**: The app itself has no separate install step. Run every command below from the `wc2026_app/` directory so `python -m wc26.cli` resolves the `wc26` package.

Verify the install by running the test suite:

```bash
cd /path/to/penaltyblog/wc2026_app
python -m pytest tests/ -q
```

Expected result: all tests pass.

## First run

Run these three commands in order from `wc2026_app/`. The first command downloads data; the second and third fit the model.

### 1. Refresh the results data

```bash
python -m wc26.cli update
```

Expected output shape:

```
results: 48000 rows, latest played 2026-06-09
```

This downloads the [martj42/international_results](https://github.com/martj42/international_results) CSV to `~/.cache/wc26/results.csv`. The row count and date reflect whatever the source contains at download time.

### 2. Model upcoming fixtures

```bash
python -m wc26.cli --asof 2026-06-11 fixtures
```

Expected output shape (one line per upcoming World Cup fixture in the window):

```
training on 5800 matches (asof 2026-06-11)
2026-06-12 Mexico v South Africa                       1X2 0.512/0.258/0.230  O2.5 0.541  BTTS 0.518
2026-06-12 Canada v Croatia                            1X2 0.331/0.279/0.390  O2.5 0.567  BTTS 0.561
```

The first invocation fits the Dixon-Coles model from scratch (~7 seconds). The fitted model is cached, so later invocations on the same training inputs load in ~1 second.

### 3. Produce a recommendation slate

Create an odds CSV (`odds.csv`) with the columns described in the [CLI reference](cli-reference.md#odds-csv-format):

```csv
home,away,market,outcome,line,odds,bookmaker
Mexico,South Africa,1x2,home,,2.10,pinnacle
Mexico,South Africa,1x2,draw,,3.40,pinnacle
Mexico,South Africa,1x2,away,,3.80,pinnacle
Mexico,South Africa,1x2,home,,2.25,bet365
```

```bash
python -m wc26.cli --asof 2026-06-11 recs --odds-file odds.csv --bankroll 1000
```

Expected output shape:

```
training on 5800 matches (asof 2026-06-11)

1 recommendations (bankroll 1000):
  Mexico v South Africa | 1x2 home @ 2.25 | model p=0.512 fair=0.476 ev=+0.152 tier=medium | stake 38.00 (3.80%)

total staked: 38.00
```

If nothing clears the thresholds, the command prints `no +EV recommendations at current thresholds`. This is the common case and is expected; see [methodology](methodology.md#honest-expectations).

## Where the model cache lives

| Path | Contents |
|---|---|
| `~/.cache/wc26/results.csv` | Downloaded international results data. |
| `~/.cache/wc26/models/<kind>-<hash>.pkl` | Pickled fitted models, keyed by model kind plus a hash of the exact training inputs. |

Any change to the training data, weights, `--years`, `--asof`, or `--model` produces a new hash and a fresh fit. Pass `--no-cache` to force a refit and skip the cache entirely.

## Expected timings

| Operation | Time |
|---|---|
| `update` (download) | Seconds, network-bound. |
| First model fit (cold cache) | ~7 seconds. |
| Subsequent fits (warm cache) | ~1 second. |
| `--no-cache` fit | ~7 seconds every time. |

## Dashboard

A Streamlit web UI exposes the same model, slate, and live-pricing logic as the CLI. Install Streamlit, then launch from `wc2026_app/`:

```bash
pip install streamlit
streamlit run dashboard.py
```

See [Dashboard](dashboard.md) for the full tab walkthrough, sidebar controls, quota guidance, and troubleshooting.

## Next steps

- [CLI reference](cli-reference.md) — every command, flag, and the odds CSV format.
- [API keys](api-keys.md) — wire up live data providers.
- [Methodology](methodology.md) — what the model does and what to expect from it.
- [Limitations](limitations.md) — where the model is thin and what it does not claim.
- [Dashboard](dashboard.md) — Streamlit web UI guide.
