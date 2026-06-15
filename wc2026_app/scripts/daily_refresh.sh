#!/usr/bin/env bash
# Daily model refresh: pull latest finished results from Sportmonks, backfill
# the local results cache, and warm the fitted-model cache so the next
# prediction loads instantly. The model auto-refits because its cache key is a
# hash of the training inputs — new scores => new key => refit.
#
# Usage:   scripts/daily_refresh.sh
# Cron:    0 6 * * *  /full/path/to/wc2026_app/scripts/daily_refresh.sh >> ~/.cache/wc26/refresh.log 2>&1
set -euo pipefail

# Resolve the app directory regardless of where cron invokes us from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
cd "$APP_DIR"

# Self-log to a rotating-ish file so cron needs no redirect (and we keep history).
mkdir -p "$APP_DIR/logs"
exec >>"$APP_DIR/logs/refresh.$(date +%Y%m).log" 2>&1

# Load the API key from .env (gitignored). Never hard-code it here.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${WC26_SPORTMONKS_KEY:-}" ]]; then
  echo "ERROR: WC26_SPORTMONKS_KEY not set (create $APP_DIR/.env from .env.example)" >&2
  exit 1
fi

PY="${PYTHON:-python}"
TODAY="$(date +%F)"

echo "[$(date '+%F %T')] refresh start (asof $TODAY)"

# 1) refresh martj42 results + backfill finished WC26 scores from Sportmonks
PYTHONPATH="$APP_DIR" "$PY" -m wc26.cli --asof "$TODAY" update --source sportmonks

# 2) warm the model cache (forces a refit on the freshly updated data)
PYTHONPATH="$APP_DIR" "$PY" -m wc26.cli --asof "$TODAY" fixtures --days 3 >/dev/null

echo "[$(date '+%F %T')] refresh done"
