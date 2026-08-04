# chiron-benchmark

Repeatable performance benchmarking for Chiron. Drives the **live public API**
and the **key UI flows** with synthetic clinical data, measures latency
(p50/p95/p99), throughput, and error rate, and evaluates the results against a
set of **controls** (pass/fail assertions with thresholds). Produces a report a
non-engineer can skim, plus the full raw data as JSON.

> Standalone tool. Black-box: HTTP only, no Chiron internals/DB access. Synthetic
> data only (the warehouse holds Synthea-style synthetic records; request
> payloads are synthetic).

## What it measures
- **API latency** — p50/p95/p99 per key endpoint, single-client sequential samples.
- **API throughput** — sustained req/s + latency-under-load via a concurrent burst.
- **API availability** — error rate (expected-status aware; e.g. `table_def` 400
  "no active snapshot" is not counted as an error).
- **UI flows** — end-to-end time of the API calls backing each key interaction
  (bootstrap, open dataset, run query preview, open reports). This is the
  API-bound portion of perceived responsiveness; real in-browser Navigation
  Timing numbers are captured separately in `BENCHMARKING.md`.

## Controls
`bench/controls.py` generates ~60 controls from the scenarios + flows
(`bench/scenarios.py`): for each endpoint a p95, p99 and error-rate control, a
throughput control for the burst-tagged ones, and one control per UI flow.
Thresholds come from a per-endpoint *tier* (light/medium/heavy) — see
`BENCHMARKING.md` for the rationale and the realistic count.

## Install & run
```bash
python3 -m venv .venv && .venv/bin/pip install -e .
chiron-bench --base-url http://127.0.0.1:8000 \
             --username admin --password demo1234 \
             --iterations 30 --burst-total 60 --concurrency 8 --verbose
# writes PERFORMANCE_REPORT.md + results/latest.json
# --fail-on-miss exits 1 if any control fails (CI gate)
```
Env vars `CHIRON_BASE_URL`, `CHIRON_USER`, `CHIRON_PASSWORD` are honoured.

## Layout
| Path | What |
|------|------|
| `bench/driver.py` | HTTP load driver (session auth; sequential + concurrent) |
| `bench/stats.py` | percentiles / throughput / error-rate summariser |
| `bench/scenarios.py` | endpoint scenarios + UI flows + latency tiers (discovers live ids) |
| `bench/controls.py` | control generation + evaluation |
| `bench/runner.py` | orchestrates measurement + control evaluation |
| `bench/report.py` | non-engineer report (Markdown) + raw JSON |
| `bench/cli.py` | `chiron-bench` command |
