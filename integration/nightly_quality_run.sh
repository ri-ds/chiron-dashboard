#!/usr/bin/env bash
# Nightly Chiron quality run: validator (correctness) + benchmark (performance)
# against an already-running Chiron. Appends a dated summary and keeps history in
# each tool's own store (validator SQLite run table / benchmark JSON snapshots).
#
# Usage:  CHIRON_BASE_URL=http://127.0.0.1:8000 ./nightly_quality_run.sh
# Intended to be driven by cron / a scheduled task (see CHIRON_REVIEW_LOG.md).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$ROOT/integration/history"
mkdir -p "$OUT"

export CHIRON_BASE_URL="${CHIRON_BASE_URL:-http://127.0.0.1:8000}"
export CHIRON_USER="${CHIRON_USER:-admin}"
export CHIRON_PASSWORD="${CHIRON_PASSWORD:-demo1234}"
export CHIRON_DATASET="${CHIRON_DATASET:-dataset1_stored}"

echo "[$STAMP] Chiron nightly quality run against $CHIRON_BASE_URL"

# Reachability guard: if Chiron isn't up, log and exit cleanly (never error loudly
# on a nightly cron). A production setup would start/tear-down the server here.
if ! curl -sf -o /dev/null "$CHIRON_BASE_URL/api/version/"; then
  echo "  Chiron not reachable at $CHIRON_BASE_URL — skipping this run." | tee -a "$OUT/trend.log"
  exit 0
fi

# --- 1. correctness ---
( cd "$ROOT/chiron-validator" && .venv/bin/chiron-validator load >/dev/null \
  && .venv/bin/chiron-validator run --include-v1 \
       --report "$OUT/validator-$STAMP.md" ) \
  && echo "  validator OK" || echo "  validator reported failures (see report)"

# --- 2. performance ---
( cd "$ROOT/chiron-benchmark" && .venv/bin/chiron-bench \
       --md "$OUT/benchmark-$STAMP.md" \
       --json "$OUT/benchmark-$STAMP.json" ) \
  && echo "  benchmark OK" || echo "  benchmark reported misses (see report)"

# --- 3. one-line trend row ---
python3 - "$ROOT" "$STAMP" "$OUT" <<'PY' 2>/dev/null || true
import json, sys, sqlite3, os
root, stamp, out = sys.argv[1], sys.argv[2], sys.argv[3]
line = [stamp]
try:
    c = sqlite3.connect(f"{root}/chiron-validator/validator.db")
    r = c.execute("SELECT n_passed,n_failed,n_skipped FROM run ORDER BY id DESC LIMIT 1").fetchone()
    line.append(f"validator pass={r[0]} fail={r[1]} skip={r[2]}")
except Exception as e:
    line.append(f"validator n/a ({e})")
try:
    b = json.load(open(f"{out}/benchmark-{stamp}.json"))
    line.append(f"bench pass={b['n_pass']} fail={b['n_fail']}/{b['n_controls']}")
except Exception as e:
    line.append(f"bench n/a ({e})")
open(f"{out}/trend.log", "a").write(" | ".join(line) + "\n")
print("  trend:", " | ".join(line))
PY

echo "[$STAMP] done. Reports + trend in $OUT"
