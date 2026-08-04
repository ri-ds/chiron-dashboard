# Chiron Validator + Engineering Review — Running Log

Senior-engineer program of work against Chiron. Two workstreams: (A) build a
standalone API-correctness validator, then (B) review, improve, and instrument
Chiron. Entries are append-only, newest at the bottom of each task section.

**Working dir:** `/Users/pot95a/2026/new_chiron`
**Started:** 2026-07-20

## Repos in scope
- `is4r-chiron-develop/` — Chiron backend: Django + Django REST Framework, Python 3.12. Reusable `chiron` package + `test_project/` Django app used to run/test it.
- `is4r-chiron-ui-develop/` — Chiron UI: React 19 + Vite 7 + Redux Toolkit + MUI, TypeScript, pnpm.
- `chiron-data-validator/` — **IGNORED per brief.** Pre-existing, unrelated validator folder. Not touched.

---

## Task 1 — Understand Chiron end to end  (IN PROGRESS)

### Recon findings
- **Stack:** Backend is a reusable Django app (`chiron`) plus `test_project/` (a runnable Django project with a demo dataset in `db.sqlite3`). UI is a Vite/React SPA that talks to the backend over HTTP.
- **Two databases (key architecture point):**
  1. Django *metadata* DB — SQLite (`test_project/db.sqlite3`), holds Chiron's own models (concepts, reports, cohort/table/analysis definitions, users, logs).
  2. Chiron *data warehouse* — Postgres via SQLAlchemy (`CHIRON_SQL_ALCHEMY_CONNECTION_STRING = postgresql://postgres:postgres@localhost:5432/chiron`). Holds the actual research/patient data that gets queried/reported on.
- **Two API surfaces:**
  - `/api/` (v1) — flat DRF DefaultRouter: chiron_users, me, collections, concepts, concept_categories, cohort_def, table_def, analysis_def, query_tools, analysis_tools, project, reports, report_tools, version.
  - `/api/v2/` (v2) — dataset-scoped DRF router: `/api/v2/<dataset_string>/<resource>/`. Resources: auth, concepts, reports, cohort_def, table_def, analysis_def, analysis_tools, query_tools, report_tools, concept_categories, collections, plus top-level `dataset`.
  - **The React UI uses v2 exclusively.** v1 remains registered/available.
- **Non-API views:** `backend/*` (etl_logs, data_dictionary, source_logs, query_troubleshooting, user_report, view_schema), `workspace`, `report/<id>`, `reports`, plus `ajax/*` widgets.
- **Auth:** No DRF `DEFAULT_AUTHENTICATION_CLASSES` override → DRF defaults (Session + Basic). Production uses SSO headers (REMOTE_USER-style). Custom middleware `chiron.middleware.view_as_other_user.ViewAsOtherUser` allows admins to impersonate.
- **No OpenAPI/schema generator** (no drf-spectacular). Validator type expectations must be derived from DRF serializers + Django models + observed behavior.
- **Prior-setup artifacts present:** populated `db.sqlite3` (recent mtime), `.venv/`, `settings_custom.py` (adds `CSRF_TRUSTED_ORIGINS` for the Vite dev server on :3000). Suggests an earlier partial local setup.
- **Codebase size:** ~37k LOC Python (excluding migrations/venv).

### Endpoint inventory (built by parallel fan-out)
Ran an 8-agent workflow doing deep source reads across every viewset/serializer/model.
Result: **127 distinct endpoints** (52 v2, 56 v1, 19 non-API/server-rendered) + **41 models**
with field-level types. Saved machine-readable to `inventory.json` (reused to seed the validator).

### Task 1 — DONE
`CHIRON_OVERVIEW.md` written (2847 lines): architecture, two-DB model, both API surfaces,
full field-level endpoint inventory, data-model dictionary, auth/authz model, and a
consolidated open-questions/findings list (8 latent-bug candidates carried into Tasks 4–5,
e.g. v1 snapshot retrieve not scoped by user → possible IDOR; `ProjectViewSet.update` calls
`create`; analysis_tools GET param copy-paste bugs).

---

## Task 2 — Run Chiron locally  (DONE)
- Postgres 14 running; `chiron` DB has 3 populated schemas (dataset1/2/3_stored). Django
  sqlite metadata already migrated+seeded (prior setup). venv + node_modules present.
- Backend up via `manage.py runserver 127.0.0.1:8000 --noreload`; `check` clean.
- UI up via `vite --port 3000`, proxying /api etc. → :8000.
- Set local-only dev password `demo1234` on admin/demouser/agguser (only metadata change).
- **Verified end-to-end:** Basic-auth API calls return real data; UI logs in via session and
  renders "Select a Dataset" → dataset home (6 subjects, PHI access) → nav tabs. Screenshots captured.
- Full "how to run" + issues hit → `CHIRON_OVERVIEW.md` §8.
- Blockers/assumptions: dev-login buttons don't set a session (use admin form); `/query`
  deep-link needs an active dataset selected via normal flow; `--noreload` needed for stable bg server.

---

## Task 3 — Build the validator  (DONE)
Built `chiron-validator/` — a standalone "database of type validations" for Chiron's public API.
- **Store:** SQLite (`validator.db`) holding expectations (endpoint + expected_field) AND run
  history (run/result/issue) — queryable, tracks correctness over time. Source of truth = JSON
  in `specs/` (`inventory.json` from Task 1 + hand-written `specs/overrides.json`).
- **Engine:** `typecheck.py` — field-by-field checker with a compact type language
  (string/integer/number/boolean/enum/iso8601/url, array<T>, nested object_fields/item_fields).
  24 unit tests pass.
- **Two-tier contracts:** 17 hand-verified, serializer-accurate strict overrides for the key
  v1/v2 endpoints; the rest auto-derived + lenient (type-check present fields + container shape)
  so a reported failure is real, not prose-noise.
- **Runner:** black-box (HTTP only, session auth like the UI), discovers live IDs, exercises each
  endpoint with synthetic query data, records everything. Read-only by default (`--include-writes`
  / `--include-destructive` gated). CLI: `load` / `run` / `report` / `query`.
- **Canonical run (v1+v2, dataset1_stored):** 60 passed, **5 failed**, 3 unreached, 40 skipped;
  92.3% pass rate of the 65 type-checked. Report → `VALIDATOR_REPORT.md`.

### ⭐ 5 real correctness bugs the validator found (all return HTTP 500 on ordinary reads):
1. **v2 `GET /api/v2/{ds}/query_tools/`** → `QueryToolsViewSet.list() got an unexpected keyword argument 'dataset_string'` (action signature doesn't accept the URL kwarg).
2. **v2 `GET /api/v2/{ds}/report_tools/{pk}/`** → `ReportToolsViewSetV2.retrieve() got an unexpected keyword argument 'dataset_string'` (same root cause).
3. **v2 + v1 `analysis_tools/export_csv/`** → pandas `ValueError: No group keys passed!` (missing input guard → 500 instead of 400 when no active analysis).
4. **v1 `GET /api/me/`** → `MultipleObjectsReturned: get() returned more than one ChironUser -- it returned 3!` (`.get(user=...)` not dataset-scoped; breaks for multi-dataset users).
- Also observed: some v2 viewsets **reject HTTP Basic** (only session auth works) — API auth is non-uniform; `GET /api/v2/dataset/{pk}/` 404s on an id the list itself returns (lookup inconsistency).
These 5 carry into Tasks 4–6 (Task 6 will fix #1/#2/#4).

---

## Part B progress

### Task 4/5 — security + efficiency review (IN PROGRESS)
Launched a 14-finder find→adversarially-verify workflow over both repos + the validator
(security dims: SQLi, authz/IDOR, secrets/config, PHI exposure, deserialization/file, frontend
XSS, dep CVEs, validator self-review; efficiency dims: ORM N+1, warehouse indexes, caching,
frontend bundle/re-render, dead/dup code, payload/pagination). Awaiting results → VULNERABILITIES.md
+ INEFFICIENCIES.md. (Used a full-codebase audit workflow rather than the diff-oriented
/security-review skill, since this is a whole-repo, non-git review.)

### Task 7 — performance instrumentation (BUILT, pending final report/SUMMARY refs)
Built `chiron-benchmark/` (standalone, own venv, 5 unit tests pass) — API latency (p50/p95/p99),
throughput (concurrent burst), error rate, + 4 UI flows. **60 controls** generated from
scenarios/flows (34 latency + 17 availability + 5 throughput + 4 UI); realistic count is ~60
(honestly larger than the ~50 target; ~90+ if write-path controls added). Canonical run:
**58/60 pass**. 2 real fails: concepts-list ~3.4 req/s and reports-list ~6.7 req/s under
concurrency (throughput hotspots — corroborate the efficiency review). Real in-browser UI timings
captured (cold SPA load ~1.42s Vite-dev; open-dataset flow 219ms, concepts list 183ms dominant).
Deliverables: `BENCHMARKING.md`, `chiron-benchmark/PERFORMANCE_REPORT.md`, `integration/`
(CI workflow YAML + `nightly_quality_run.sh`, tested end-to-end — writes dated reports + trend log).

### Task 7 — DONE + scheduled run set up
Final benchmark against the fixed server: **58/60 controls pass** (97%). 5 unit tests pass.
Registered a durable **nightly scheduled task** `chiron-nightly-quality` (~02:27 local) that runs
`integration/nightly_quality_run.sh` (validator + benchmark, reachability-guarded, appends to
`integration/history/trend.log`). The trend log already shows the Task-6 improvement automatically
(validator 5→2 fails across runs). This exercises the periodic-execution setup end-to-end.

---

## Follow-on — Chiron Control dashboard (`chiron-dashboard/`)  (DONE)
A shared, team-reachable web control layer over Chiron + all the tools. **Control layer only** —
calls the existing scripts/data stores as-is, no reimplementation. Flask backend + a single
polished vanilla-JS page (no build step). Bind: `0.0.0.0:8787` (LAN-reachable, e.g.
`http://192.168.1.66:8787`); Chiron itself stays host-local.

**What it exposes:**
- **Chiron process control** — start/stop/restart the **API backend** (Django :8000) and **UI
  frontend** (Vite :3000), each with a live status badge (running/starting/stopped/crashed),
  uptime, who-started-it, and a per-component stdout/stderr log tail. (Backend: `ProcessManager`
  in `dashboard/processes.py` — spawns tracked subprocesses, decides status by port probe that
  resolves both IPv4+IPv6.)
- **Tool launcher** — Run per tool. Validator + Benchmark run the real CLIs
  (`chiron-validator run --include-v1`, `chiron-bench`) as tracked subprocesses; Vulnerability +
  Inefficiency scans are **report-backed** (Claude-audit output) and "Load latest" from
  `data/findings.json`. (`dashboard/jobs.py`.)
- **Live shared status** — page polls `GET /api/state` every 2s; badges + elapsed update for
  everyone. Push not needed.
- **Inline results** — `dashboard/results.py` parses each tool's existing JSON/report store into
  stat tiles + a findings/results table rendered on the page (validator failing endpoints,
  benchmark control misses, security/efficiency findings with severity pills).
- **Shared history** — SQLite `data/dashboard.db` activity log, name-tagged, seeded from the
  existing `integration/history/trend.log`.
- **Accountability** — name asked once per browser (localStorage), attached to every action.
- **Concurrency safety** — an in-flight target's control is disabled + shows who; backend also
  returns `409 already running (started by <name>)`.

**Verified end-to-end** in-browser: name gate; both components controllable (start UI → running);
validator run → inline pass/fail table (2 failing 500s shown); vuln scan → 39 findings inline;
two simultaneous validator runs → second got HTTP 409 "already running (started by Alice)";
history name-tagged. Deliverables: `chiron-dashboard/` code + `chiron-dashboard/README.md`
(host/port, keep-running via gunicorn+systemd/launchd, security posture, and a guide to add
another control).

**Security posture (important):** no auth by design (name-tagging is accountability, not access
control) → **internal network only, never public**. All data synthetic (no PHI).

**How to add a control later** (also in the dashboard README): add a dict entry to
`dashboard/config.py` — `COMPONENTS` for a new Chiron process (label/cwd/cmd/port/probe_url;
card+status+logs+controls auto-generate) or `TOOLS` for a new tool (`kind:"subprocess"` with
cwd/cmd/env/result, or `kind:"report"`), then add a parser branch in `dashboard/results.py::parse`
returning `{outcome, headline, stats, columns, rows}`. No frontend edits needed.

---

## Dashboard — fix & polish pass  (DONE)

### Root cause of "every run is failing"
It was **not** an invocation bug — the tools were invoked correctly (right cwd, env, venv paths)
and all run standalone with exit 0 (confirmed: validator exit 0, benchmark exit 0). The bug was
**status semantics in the wrapper**: `JobRunner` set the job's *run status* directly from the
tool's *findings outcome*. So a validator that completed successfully but *found* 2 problem
endpoints was labelled `failing`, benchmark `warning`, and the vuln/inefficiency scans `failing`
(they contain high-severity findings) — every successful run rendered red as "failed."

**Fix:** split the two concepts in `jobs.py`:
- `status` = did the run work? `running | finished | failed`.
- `findings_outcome` = what a *finished* run found: `clean | issues`.
A run is `failed` **only** on a genuine error (exception, timeout, non-zero exit, or no parseable
output); then the real error + a tail of the log are captured in `job.error`. Verified end-to-end:
a normal validator run now shows **Finished** (green) with "issues found" noted separately; an
induced crash (temporarily wrong admin password so the benchmark's login raises) shows **Failed**
(red) with the full `RuntimeError: login failed` traceback in a "What went wrong" panel + Run log.

### What changed
- **Bugs:** (1) run-status vs findings split above; (2) every run now surfaces its real output —
  a per-tool "Run log" block, and on failure a red "What went wrong" panel with the actual
  error/stack/log (not a generic "failed").
- **Removed:** the name/actor prompt (+ all actor plumbing), the shared activity history table
  (+ `store.py`, `data/dashboard.db`), the header logo/mark and subtitle (header is now plain
  text "Chiron Dashboard"), and placeholder/empty-value "—" throughout (legitimate prose
  em-dashes kept).
- **Layout → tabs:** replaced the single page with 5 tabs — Chiron + one per tool. Each tab leads
  with a big, unmistakable status badge (Idle / Running… / Finished / Failed for tools; Running /
  Starting… / Stopped / Crashed for Chiron), and each tab's results load inside that tab.
- **Typography:** base font up to 16.5px with an Inter/system stack applied app-wide (tabs,
  labels, tables, results — not just headers).
- **Per-tool info:** an "i" affordance (hover title + click popover) explaining each tool. The
  **Validator** info reads exactly as specified ("a rules-based check of Chiron's API … verifies
  data/concepts against a defined set of validation rules … lists every rule that failed"), and
  its results now **list every failed rule in full** — columns Endpoint / Concept·field (rule
  path) / Rule / Actual / Why it failed — so a broken concept/field is visible individually, not
  as a bare count.
- Also fixed a latent status-probe bug found while testing: the port probe was IPv4-only, so Vite
  (IPv6 `localhost`) showed "starting" forever — now resolves both families.
- No rewrite: same Flask app + same reused tools/data stores; edits in place.

### Task 4/5 — review DONE
Workflow finished: 80 candidate findings → **64 kept** after adversarial verification
(16 rejected as false positives), split **39 security / 25 efficiency**.
- `VULNERABILITIES.md` (39): 3 high, 11 medium, 14 low, 11 info. Top: (H) v1 ReportViewSet
  edit/delete/share/flag bypass object-level auth; (H) stored XSS via `dangerouslySetInnerHTML`
  on concept description (query.tsx:211); (H) ETL log/data-issue views expose raw subject
  identifiers + source values. Medium: snapshot IDOR, cross-dataset user enumeration,
  unrestricted `view_as_other_user`, CSRF disabled on state-changing API, hardcoded SECRET_KEY
  (also the de-id salt), CSV formula injection, DDL/identifier injection in ETL, broken HSTS.
- `INEFFICIENCIES.md` (25): 5 high, 9 medium, 11 low. Top: (H) **stats cache-hit path skips
  small-cell suppression → serves un-suppressed counts** (privacy + perf cross-cut); (H)
  ConceptSerializer N+1; (H) CSV export buffers whole dataset in memory; (H) reports list
  default page_size=1000; (H) concept-list permission loop scans full queryset every request
  (matches the benchmark's ~3.4 req/s concepts-list throughput miss).
- Method note: used a full-codebase find→verify workflow (not the diff-based /security-review
  skill). Nothing fixed during the review (per brief).

### Task 6 — fixes designed (pending review completion, then implement on a branch)
Confirmed exact code for the 3 fixes: `QueryToolsViewSet.list` missing `*args,**kwargs`
(chiron/api/viewsets/query_tools.py:34); `ReportToolsViewSetV2.retrieve` missing `*args,**kwargs`
(chiron/api_v2/viewsets/report_tools.py:43); `MeViewSet.list` uses `ChironUser.objects.get(user=...)`
which raises MultipleObjectsReturned for multi-dataset users (chiron/api/viewsets/chiron_user.py:56).
Repos are NOT git — will `git init` backend + branch for Task 6.

### Task 6 — DONE
`git init` backend, baseline commit `6cf8412`, branch **`fix/api-500-robustness`** (commit `e9a35b5`).
Implemented the 3 fixes + regression tests. **Before/after:**
- Integration (validator): run #11 BEFORE = 60 pass / **5 fail** → run #12 AFTER = 63 pass / **2 fail**.
  The 3 fixed endpoints (me, query_tools list, report_tools retrieve) went 500 → 200; query_tools
  v2 URLs now correctly v2-namespaced.
- Unit: 3 new regression tests **fail on baseline** (me one raises the exact
  `MultipleObjectsReturned … returned 2!`), **pass on the fix**.
- No new regressions: the 5 `test_report.py` failures in the full suite are **pre-existing
  test-ordering pollution** (pass in isolation, fail in full-suite on baseline too) — flagged as a
  separate follow-up. Remaining 2 validator fails = `analysis_tools/export_csv` pandas guard
  (documented as follow-up, out of low-risk scope). → `IMPROVEMENTS.md`.
