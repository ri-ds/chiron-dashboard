# Chiron Performance Instrumentation (Task 7)

Deliverable for Task 7: a benchmark suite (API + UI), a set of performance
controls run through it, a non-engineer-readable report, and an integration
recommendation. All driven by **synthetic** clinical data over Chiron's
**public API only** — no real PHI, no internals access.

Artifacts:
- **Suite code:** [`chiron-benchmark/`](chiron-benchmark/) (`bench/` package + `chiron-bench` CLI).
- **Performance report:** [`chiron-benchmark/PERFORMANCE_REPORT.md`](chiron-benchmark/PERFORMANCE_REPORT.md) (regenerated each run).
- **Raw data:** `chiron-benchmark/results/latest.json` (every metric + control result).

---

## 7a. Benchmark suite (both layers)

**API layer** (`bench/driver.py`, `bench/scenarios.py`):
- *Latency* — per-endpoint sequential sampling → **p50 / p95 / p99 / mean / min / max**
  (default 30 samples + 2 warmups).
- *Throughput* — a concurrent burst (default 60 requests @ 8 workers, independent
  sessions) → **req/s** and latency-under-load.
- *Error rate* — expected-status aware (e.g. `table_def` returns `400 "no active
  snapshot"` by design, so it is not counted as an error).
- 18 scenarios spanning **metadata** (auth, datasets, categories, concepts,
  collections), **query/warehouse** (concept statistics, cohort/table def, query
  preview + preview-metadata), and **reports** (list, viewable, report preview).
  Path ids are discovered live before the run.

**UI layer** (`bench/scenarios.py::flows` + real-browser capture):
- 4 **UI flows** measured as the end-to-end time of the API calls backing each
  interaction (bootstrap, open-dataset, run-query-preview, open-reports) — the
  API-bound portion of perceived responsiveness, repeatable in-suite.
- **Real in-browser** Navigation/Resource Timing captured separately (below) to
  ground the flow numbers in an actual browser.

Run it:
```bash
cd chiron-benchmark && python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/chiron-bench --base-url http://127.0.0.1:8000 \
    --username admin --password chiron-dev-pw --verbose
```

## 7b. Controls & performance report

A **control** is one pass/fail assertion: a metric + comparator + threshold, with
a plain-language name. `bench/controls.py` generates them from the scenarios so
the count scales with what the system exposes.

**Realistic count: 60 controls** (the team's ~50 was directional; the read-only
API surface genuinely supports ~60). Breakdown:

| Category | Controls | What it asserts |
|----------|----------|-----------------|
| API latency | 34 | p95 + p99 under a per-endpoint tier threshold |
| API availability | 17 | zero unexpected-status responses per endpoint |
| API throughput | 5 | sustained req/s under concurrency (burst-tagged endpoints) |
| UI flow | 4 | each key flow's p95 under a target |
| **Total** | **60** | |

This could grow to ~90+ by adding **write-path** controls (create/update cohort,
table, report; CSV/JSON export latency + payload size) once the runner is allowed
to mutate data — deliberately excluded here to keep default runs read-only and
safe. It is honestly **larger than ~50**, not smaller.

**Threshold rationale** — endpoints are tiered:
- `light` (cached/metadata reads): p95 ≤ 300 ms, p99 ≤ 600 ms.
- `medium` (metadata joins / list building): p95 ≤ 900 ms, p99 ≤ 1800 ms.
- `heavy` (warehouse queries — counts / previews / stats / exports): p95 ≤ 2500 ms, p99 ≤ 5000 ms.
- Throughput targets (single-node dev server): light 25, medium 12, heavy 4 req/s.

Thresholds are conservative targets for a single-process dev server on synthetic
data; a deployment would recalibrate against production hardware + data volume.

### Headline result (latest run, dataset `dataset1_stored`)

**58 / 60 controls passing (96.7%).**

| Area | Pass | Notes |
|------|------|-------|
| API latency (p95/p99) | 34/34 ✅ | all endpoints comfortably inside tier thresholds |
| API availability | 17/17 ✅ | no unexpected errors on read endpoints |
| API throughput | 3/5 ❌ | **2 misses — see below** |
| UI flows | 4/4 ✅ | bootstrap 10 ms, open-dataset 398 ms, query-preview 33 ms, reports 103 ms (API-bound p95) |

**The 2 failing controls (genuine findings):**
1. **List concepts (page 1): ~3.4 req/s** under concurrency (target ≥ 12). The
   concepts list is the single most expensive metadata endpoint (p95 ≈ 326 ms
   single-client) — per-concept permission checks + serialization. It is also the
   dominant cost in the open-dataset flow (183 ms of ~219 ms in-browser).
2. **List reports (paginated): ~6.7 req/s** (target ≥ 12) — returns up to the full
   set (103 reports here) with per-row project/sharing lookups.

Both corroborate the efficiency review (see `INEFFICIENCIES.md`) and are the
best targets for optimization + caching.

### Representative raw metrics

| Endpoint | tier | p95 (ms) | p99 (ms) | throughput |
|----------|------|----------|----------|-----------|
| Auth / whoami | light | 3.8 | 4.6 | 372 req/s |
| List concepts (page 1, 100) | medium | 326 | 335 | **3.4 req/s** |
| Concept detail + statistics | heavy | 212 | 291 | — |
| Query preview (warehouse) | heavy | 40 | 42 | — |
| Report preview (warehouse) | heavy | 70 | 70 | — |
| List reports (paginated) | medium | 90 | 264 | **6.7 req/s** |

_(Warehouse queries are fast here because the demo dataset is tiny — 6 subjects.
On production-scale data these `heavy`-tier endpoints are where the tiered
thresholds matter; the suite is built to catch regressions there.)_

### Real in-browser UI timings (captured via Navigation/Resource Timing)

Environment: **Vite dev server** (unbundled ESM, on-the-fly compile) — dev-mode
numbers; a production build would cut page-load markedly.

| Measurement | Value |
|-------------|-------|
| Dataset-select cold SPA load — `domContentLoaded` | ~1420 ms (Vite dev module loading, **not** the API) |
| — `domInteractive` | ~11 ms |
| On-load API calls | `/api/v2/auth/` 13 ms, `/api/v2/dataset/` 7 ms |
| Open-dataset flow (real browser fetch, warm) | **219 ms total** — concept_categories 24, **concepts 183**, collections 12 |

Takeaway: the API is fast for metadata (7–24 ms); the **concepts list dominates**
both the throughput miss and the open-dataset interaction — one endpoint to
optimize/cache buys the most perceived-performance improvement.

## 7c. Integration recommendation

Both this suite and the Task 3 validator are **black-box HTTP tools with a
`--fail-on-*` CI gate and machine-readable JSON output**, so they slot into
Chiron's lifecycle without coupling to its code:

| Option | Effort | Recommendation |
|--------|--------|----------------|
| **CI job** (GitHub Actions) — spin up Chiron + Postgres, run validator + benchmark on every PR, gate on `--fail-on-error` / `--fail-on-miss` | Low | **Do this first.** A ready-to-use workflow is provided: [`integration/ci-chiron-quality.yml`](integration/ci-chiron-quality.yml). |
| **Scheduled nightly health check** — same two tools on a cron, trend the SQLite history, alert on regressions | Low | **Do this.** A runner script + scheduled-task setup is provided (see `integration/` and the Final section of `CHIRON_REVIEW_LOG.md`). |
| **CLI / management command** inside Chiron (`manage.py chiron_selfcheck`) that shells to both tools | Low–Med | Optional convenience; keep the tools as separate repos so they can target any environment, not just localhost. |
| **Dashboard panel** — the validator + benchmark both already write to structured stores (SQLite / JSON); a small static dashboard could read the run history | Med | Recommended later; the data model already supports it (`run`/`result`/`issue` tables track history over time). |

**Minimal implementation provided** (low-effort, low-risk):
- A CI workflow YAML that stands up Postgres + Chiron, seeds the demo data, and
  runs both tools as PR gates.
- A nightly runner script wiring both tools together (see the Final section).

Rough effort to production-harden: **~1–2 engineer-days** (secrets/env wiring,
threshold calibration against prod data, wiring alerts to the team's existing
channel). The tools themselves are done.
