# Chiron Validator + Engineering Review — Summary

Program of work against **Chiron** (a clinical-research data-exploration tool:
Django + DRF backend `is4r-chiron-develop`, React/Vite UI `is4r-chiron-ui-develop`).
Two workstreams delivered in order: **(A)** built a standalone API-correctness
validator and ran it against a live local Chiron; **(B)** reviewed, improved, and
instrumented Chiron. Everything ran **local/sandbox only** with **synthetic data**
(Synthea-style warehouse records + synthetic query payloads — no real PHI). The
pre-existing `chiron-data-validator/` folder was left untouched per the brief.

Full chronological log: [`CHIRON_REVIEW_LOG.md`](CHIRON_REVIEW_LOG.md).

---

## Validator results (Part A)

Built [`chiron-validator/`](chiron-validator) — a **queryable SQLite "database of
type validations."** It derives expected request/response field types from
Chiron's own DRF serializers + Django models (127 endpoints, 41 models inventoried
in [`CHIRON_OVERVIEW.md`](CHIRON_OVERVIEW.md)), stores them, then calls the **live
public API only** (black-box) with synthetic data and checks every response
field-by-field. 24 unit tests pass.

**Canonical run (v1 + v2, `dataset1_stored`): 63 pass / 2 fail / 92%+ type-valid**
(after the Task-6 fixes; was 60/5 before). The validator's headline power was
finding **5 endpoints that return HTTP 500 on ordinary reads** → full report:
[`VALIDATOR_REPORT.md`](VALIDATOR_REPORT.md):

1. `GET /api/v2/{ds}/query_tools/` — `list() got an unexpected keyword 'dataset_string'`
2. `GET /api/v2/{ds}/report_tools/{pk}/` — same root cause on `retrieve()`
3. `GET /api/me/` — `MultipleObjectsReturned` (one ChironUser per dataset)
4. + 5. `analysis_tools/export_csv/` (v1 & v2) — pandas `No group keys passed!`

It also showed the v2 API's auth is non-uniform (some viewsets reject HTTP Basic,
only accept session) and `GET /api/v2/dataset/{pk}/` 404s on an id the list returns.

## Top vulnerabilities (Part B, Task 4)

39 verified findings in [`VULNERABILITIES.md`](VULNERABILITIES.md) (3 high, 11
medium, 14 low, 11 info; 16 false positives dropped by an adversarial pass). Top:

| Sev | Finding | Where |
|-----|---------|-------|
| 🟥 High | **Object-level auth bypass** on v1 report actions (`edit_form`/`delete_form`/`share_form`/`flag`) — act on reports you don't own/can't access | `chiron/api/viewsets/report.py` |
| 🟥 High | **Stored XSS** — concept description rendered via `dangerouslySetInnerHTML` with no sanitisation | `ui/src/routes/query.tsx:211` |
| 🟥 High | **PHI exposure** — ETL log / data-issue views surface raw subject-matching identifiers + source values | `chiron/views/views_backend.py` |
| 🟧 Med | Snapshot **IDOR** (read any user's cohort/table/analysis def by pk); cross-dataset user enumeration; unrestricted `view_as_other_user` impersonation | viewsets + middleware |
| 🟧 Med | **CSRF disabled** on session-authed state-changing API; hardcoded `SECRET_KEY` (also the de-id salt); **CSV formula injection** in exports; DDL/identifier injection in ETL; broken (misspelled) HSTS | settings / export / query_engine / nginx |

## Top inefficiencies (Part B, Task 5)

25 verified findings in [`INEFFICIENCIES.md`](INEFFICIENCIES.md) (5 high, 9 medium,
11 low). Top:

| Sev | Finding | Impact |
|-----|---------|--------|
| 🟥 High | **Stats cache-hit path skips small-cell suppression** — serves *un-suppressed* counts | privacy **and** perf cross-cut |
| 🟥 High | `ConceptSerializer` does multiple related lookups **per concept** (N+1) | slow concept list |
| 🟥 High | CSV export **buffers the whole dataset in memory** (no streaming/cap) | OOM risk at scale |
| 🟥 High | Concept-list **permission loop scans the full queryset every request** | matches the benchmark's ~3.4 req/s concepts-list miss |
| 🟥 High | Reports list default `page_size=1000` (max 10000) with heavy per-item payloads | large responses |

## What I improved (Part B, Task 6)

Branch **`fix/api-500-robustness`** (commit `e9a35b5`, off baseline `6cf8412`) — 3
low-risk correctness fixes + regression tests. Details + verify steps:
[`IMPROVEMENTS.md`](IMPROVEMENTS.md).

- Fixed the two v2 `dataset_string`-kwarg 500s and corrected the v2 `query_tools`
  action URLs; fixed the `/api/me/` multi-dataset 500 (dataset-aware resolution).
- **Before/after (validator): 5 failing endpoints → 2** (the 3 fixed ones now 200).
- **Regression tests fail on baseline** (incl. the exact `MultipleObjectsReturned …
  returned 2!`) and **pass on the fix**; the full suite shows **no new failures**
  (the 5 `test_report.py` failures are pre-existing test-ordering pollution).

## Benchmark headline (Part B, Task 7)

[`chiron-benchmark/`](chiron-benchmark) measures API latency (p50/p95/p99),
throughput, error rate, and 4 UI flows, evaluated against **60 controls**. Report:
[`BENCHMARKING.md`](BENCHMARKING.md) + [`chiron-benchmark/PERFORMANCE_REPORT.md`](chiron-benchmark/PERFORMANCE_REPORT.md).

- **58 / 60 controls passing (97%).** API latency 34/34, availability 17/17, UI
  flows 4/4; **2 throughput misses** — **concepts list ~3.4 req/s** and **reports
  list ~6.7 req/s** (real hotspots, corroborated by the efficiency review).
- Real in-browser UI: cold SPA load ~1.42 s (Vite **dev** module loading, not the
  API); open-dataset flow ~219 ms, of which the concepts list is 183 ms.
- 5 unit tests pass. `realistic control count ≈ 60` (honestly larger than the ~50
  target; ~90+ with write-path controls).

## Recommended next steps

1. **Fix the remaining 500** (`analysis_tools/export_csv` → clean 400 when no active
   analysis) — noted as a follow-up in `IMPROVEMENTS.md`.
2. **Security (high first):** sanitise the concept-description HTML (XSS); add
   object-level auth to the v1 report actions; gate the ETL log/data-issue views
   and dataset-scope snapshot retrieves; rotate the hardcoded `SECRET_KEY`/de-id
   salt out of source; neutralise CSV formula injection; quote/allowlist ETL
   identifiers; fix the misspelled HSTS header. (`VULNERABILITIES.md` has fixes.)
3. **Privacy-critical:** the stats cache-hit path must re-apply small-cell
   suppression — it currently serves un-suppressed counts on cache hits.
4. **Performance:** optimise the concept-list permission loop + `ConceptSerializer`
   N+1 (biggest perceived-latency win); stream CSV exports; lower the reports-list
   default page size; turn on the concept-stats cache with correct invalidation.
5. **Fix the pre-existing test-isolation bug** so `test_report.py` passes in the
   full suite, then wire the provided **CI gate** ([`integration/ci-chiron-quality.yml`](integration/ci-chiron-quality.yml)).
6. **Adopt OpenAPI** (drf-spectacular) so the validator can diff a generated schema
   instead of an inferred inventory.
7. **Keep the nightly monitor running** (already set up — see below) and add an
   alert when `trend.log` shows a regression.

## Ongoing monitoring (set up)

A durable **nightly scheduled task** `chiron-nightly-quality` (~02:27 local) runs
[`integration/nightly_quality_run.sh`](integration/nightly_quality_run.sh) — the
validator + benchmark, reachability-guarded — and appends to
`integration/history/trend.log`. The trend log already captures the Task-6
improvement automatically (validator `fail=5` → `fail=2` across runs).

---

## Every artifact produced

**Root reports (`/Users/pot95a/2026/new_chiron/`)**
- `CHIRON_OVERVIEW.md` — architecture + 127-endpoint field-level inventory + 41 models + auth model + how-to-run (Tasks 1–2)
- `VALIDATOR_REPORT.md` — validator run results (Task 3)
- `VULNERABILITIES.md` — 39 verified security findings (Task 4)
- `INEFFICIENCIES.md` — 25 verified efficiency findings (Task 5)
- `IMPROVEMENTS.md` — the 3 fixes, before/after, verify steps (Task 6)
- `BENCHMARKING.md` — benchmark suite + controls + results + integration (Task 7)
- `CHIRON_REVIEW_LOG.md` — running log of the whole program
- `SUMMARY.md` — this file

**`chiron-validator/`** — the validator tool
- `chiron_validator/{typecheck,normalize,db,load_specs,client,synthetic,runner,report,cli}.py`, `__init__.py`
- `specs/inventory.json` (field-level inventory), `specs/overrides.json` (17 serializer-verified strict contracts)
- `tests/test_typecheck.py`, `tests/test_normalize.py` (24 tests), `pyproject.toml`, `README.md`
- generated: `validator.db` (SQLite store), `reports/latest_run.json`

**`chiron-benchmark/`** — the benchmark suite
- `bench/{stats,driver,scenarios,controls,runner,report,cli}.py`, `__init__.py`
- `tests/test_stats.py` (5 tests), `pyproject.toml`, `README.md`
- generated: `PERFORMANCE_REPORT.md`, `results/latest.json`

**`integration/`** — deployment/monitoring
- `ci-chiron-quality.yml` (GitHub Actions PR gate), `nightly_quality_run.sh` (nightly runner), `history/` (dated reports + `trend.log`)

**Code change (in `is4r-chiron-develop`, git branch `fix/api-500-robustness`)**
- Edited: `chiron/api/viewsets/query_tools.py`, `chiron/api_v2/viewsets/query_tools.py`, `chiron/api_v2/viewsets/report_tools.py`, `chiron/api/viewsets/chiron_user.py`
- Added tests: `chiron/api_v2/tests/test_dataset_scoped_action_regression.py`, `chiron/api/tests/test_me_multidataset_regression.py`

**Scheduled task**: `chiron-nightly-quality` (`~/.claude/scheduled-tasks/`)
