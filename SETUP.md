# SETUP — Chiron Dashboard

Control dashboard + 5 quality tools for Chiron. Monorepo of Python subprojects; no
single package manifest at the root. Two supported run modes: **Docker Compose**
(recommended) and **host-local**.

---

## For AI Agents

1. Execute the **Quick Start** commands **in the order given**. Order matters — see
   *Order dependencies* in Full Setup Steps.
2. Run the verification check printed with each step **before** moving to the next.
3. If a step fails, **stop and report the exact command, exit code, and stderr**. Do
   not improvise around it, do not skip it, do not substitute a different command.
4. **Never invent environment variable values.** Every var is listed in *Environment
   Variables* with its source. If a value is not obtainable, stop and ask.
5. **Step 0 is a hard blocker.** `is4r-chiron-develop/` and `is4r-chiron-ui-develop/`
   are gitignored and ship **empty**. The Compose build cannot proceed without them.
   Do not attempt to clone them from a guessed URL — no remote is configured.
6. Do not run `docker compose down -v` (destroys the Postgres + dashboard volumes).
7. The stack is **dev/demo only**: `DEBUG=True`, demo credentials, Docker socket
   mounted into the dashboard. Never expose it beyond localhost.

---

## Quick Start

```bash
# 0. HARD BLOCKER — place the two Chiron source repos here first (see Prerequisites)
cd /path/to/chiron-dashboard
ls is4r-chiron-develop/test_project is4r-chiron-ui-develop/package.json   # must both exist

# 1. Docker Desktop must be running
docker ps

# 2. Build + start the whole stack (first build ~10-15 min)
docker compose up --build -d

# 3. Wait for the API to report healthy
docker compose ps

# 4. Verify
curl -s http://localhost:8000/api/version/   # {"chiron":"Unknown"}
curl -so /dev/null -w '%{http_code}\n' http://localhost:8787/   # 200
```

Open **http://localhost:8787**. Log in to Chiron with `admin` / `demo1234`.

---

## Prerequisites

| Tool | Exact requirement | Verified on this machine |
|---|---|---|
| **Docker Desktop** | Engine 24+, Compose v2 | Engine 28.0.0, Compose v2.32.4 ✅ |
| **Python** | 3.12 (tools declare `>=3.10`; both Dockerfiles pin `python:3.12-slim`) | 3.12.5 ✅ |
| **git** | any 2.x | 2.39.3 ✅ |
| **Node** | 20+ — **host-local UI dev only**. The Docker UI build uses `node:24-slim` + pnpm 8 internally, so Docker mode needs no host Node. | 20.17.0 ✅ |
| **Host PostgreSQL** | Listening on `localhost:5432` with a database named `chiron` containing the `dataset*_stored` schemas. This is the **default** warehouse target (see Order dependencies #2). | listening on 127.0.0.1:5432 ✅ |
| **Disk** | ~4 GB of images (`chiron-dashboard` alone is **2.53 GB** — it installs Playwright + Chromium) | ✅ |

**Ports that must be free:** `8787` (dashboard), `8000` (API), `3000` (UI),
`5433` (container Postgres). Host `5432` is left to your own Postgres on purpose.

### Step 0 — the two Chiron source repos (blocker)

`docker-compose.yml` **builds Chiron from source**. Those repos are a separate
project, are gitignored here, and are **not** included:

```
chiron-dashboard/
├── is4r-chiron-develop/       <- Chiron backend  (Django + DRF)  — YOU PROVIDE
├── is4r-chiron-ui-develop/    <- Chiron UI       (React + Vite)  — YOU PROVIDE
```

There is **no configured git remote** for either (the backend copy on this machine has
no `origin`; the UI copy is not a git repo at all). Obtain them from the Chiron / IS4R
project owners. On this machine, working copies already exist at
`/Users/pot95a/2026/new_chiron/is4r-chiron-develop` and `.../is4r-chiron-ui-develop`.

Required contents: backend must have `requirements/`, `chiron/`, `test_project/`; UI
must have `Dockerfile`, `package.json`, `pnpm-lock.yaml`.

---

## Environment Variables

No `.env` file is read by the core stack — Compose sets everything inline. Nothing
below is secret except the RDCRN session values.

### Core stack (set in `docker-compose.yml`; override for host-local runs)

| Name | Purpose | Where to get it |
|---|---|---|
| `CHIRON_BASE_URL` | Chiron API root every tool targets. | Compose sets `http://api:8000`. Host-local default `http://127.0.0.1:8000`. |
| `CHIRON_USER` | Chiron login for the tools. | Demo value `admin`. Real deployments: your Chiron account. |
| `CHIRON_PASSWORD` | Password for `CHIRON_USER`. | Demo value `demo1234` (set on the seeded SQLite users). Never commit a real one. |
| `CHIRON_DATASET` | Default dataset the tools query. | `dataset1_stored`. Live list: `GET /api/v2/dataset/` → `unique_id`. |
| `CHIRON_SQL_ALCHEMY_CONNECTION_STRING` | Warehouse (Postgres) DSN used by the backend. | Compose default `postgresql://postgres:postgres@host.docker.internal:5432/chiron` (your **host** Postgres). Change host to `db` for the container's own empty Postgres. |
| `CHIRON_IN_DOCKER` | Gate in `deploy/settings_custom.docker.py` enabling `ALLOWED_HOSTS=["*"]` + the container DSN. | Compose sets `"1"`. Leave unset host-local. |
| `CSRF_TRUSTED_ORIGINS` | Extra comma-separated origins appended to Django's CSRF allowlist. | Compose sets the UI/API origins. Add yours if you serve on a different host/port. |
| `CHIRON_DASHBOARD_DOCKER` | Switches the dashboard from spawning local subprocesses to controlling **containers** via the Docker socket. | Compose sets `"1"`. **Leave unset host-local**, or Start/Stop breaks. |
| `CHIRON_DASHBOARD_HOST` | Dashboard bind address. | Default `0.0.0.0`. Set `127.0.0.1` to keep it off the LAN. |
| `CHIRON_DASHBOARD_PORT` | Dashboard port. | Default `8787`. |
| `VITE_MUI_KEY` | MUI X Pro licence key baked into the UI build. **Optional** — build works without it. | Your organisation's MUI subscription. Pass as `VITE_MUI_KEY=… docker compose up --build`. |

### RDCRN catalog checker (optional subproject, not in the Compose stack)

| Name | Purpose | Where to get it |
|---|---|---|
| `CATALOG_BASE_URL` | Live catalog root to check. | Default `https://publicdatacatalog.rarediseasesnetwork.org`. Staging: `shibstage.rarediseasesnetwork.org`. |
| `CATALOG_COOKIE` | **Secret.** Raw `Cookie:` header containing `_shibsession_…`. | Your own browser: DevTools → Network → any catalog request → Request Headers → copy `Cookie`. `monitor.py` sets it automatically from the saved session. See `.env.example`. |
| `CATALOG_AUTH_HEADER` | **Secret.** e.g. `Bearer <token>`, if RDCRN ever issues a service token. | RDCRN / DMCC / NCATS admins. None exists today. |
| `CATALOG_COOKIES_FILE` | **Secret.** Path to a Mozilla/Netscape or LWP cookie file, as an alternative to `CATALOG_COOKIE`. | Exported from your browser. |
| `CATALOG_DATASET` | Dataset slug to spot-check. | The catalog UI's dataset URL. |
| `CATALOG_VERIFY_URL` | Page `sso_session.py` lands on to confirm login. | Any authenticated catalog URL. |
| `CATALOG_LOGIN_PATH` | Login path for `web_login.py`. | Default `/login/`. |
| `CATALOG_HTTP_TIMEOUT` | Per-request timeout for live runs (seconds). | Default `120`. |
| `SSO_STATE_FILE` | **Secret path.** Saved cookie jar — equivalent to a logged-in browser. | Default `rdcrn-catalog-checker/.session/state.json`, written `0600`. Created by `sso_session.py cli-login`. |
| `SSO_SITE_FILE` | Records which site you signed into. | Default `.session/site.json`, written by the dashboard's Login tab. |
| `SSO_LOGIN_TIMEOUT` / `SSO_NAV_TIMEOUT_MS` | Interactive-login and navigation timeouts. | Defaults `600` s / `45000` ms. |
| `UI_NAV_TIMEOUT_MS` / `UI_STEP_TIMEOUT_MS` | `ui_check.py` timeouts. | Defaults `45000` / `25000` ms. |
| `API_CHECK_JSON` | Output path for `api_check.py`. | Defaults to `results/api_check.json`. |

`IMPORT_ARGS` and `BUILD_ARGS` are set internally by the dashboard when it execs
`deploy/chiron_import.py` / `deploy/chiron_build_synthea.py` inside `chiron-api`. Do
not set them by hand.

---

## Full Setup Steps

### Order dependencies (read before running anything)

1. **Chiron source repos before any build.** They are the build *contexts* for `api`
   and `ui`. Empty dirs → build fails at `COPY` (see Common Issues #1).
2. **Host Postgres before `api` starts.** Default DSN is `host.docker.internal:5432/chiron`.
   The API still boots and login still works without it (metadata comes from a baked
   SQLite snapshot), but every warehouse query 500s. Change to `db` for a
   self-contained-but-empty warehouse.
3. **`chiron-validator load` before `chiron-validator run`.** `load` builds
   `validator.db` from `specs/`; `run` reads it and fails without it.
4. **Tool venvs must sit at the exact relative paths `config.py` hardcodes:**
   `chiron-validator/.venv`, `chiron-benchmark/.venv`, `chiron-scanners/.venv`,
   `rdcrn-catalog-checker/.venv`, and — note the difference —
   `chiron-data-validator/venv` (no dot). Wrong path → the dashboard's Run buttons
   fail with "no such file".
5. **`playwright install chromium` after `pip install`** for the RDCRN checker.
6. **`sso_session.py cli-login` before the `*_live` tools.** Without a session they
   exit 2 and the dashboard refuses to launch them.
7. `docker compose` handles `db → api → ui → dashboard` ordering itself (`db` gates on
   a healthcheck).

---

### Path A — Docker Compose (recommended)

**A1. Place the Chiron source repos.**
```bash
cd /path/to/chiron-dashboard
# copy or clone the two repos in (see Prerequisites → Step 0)
```
*Verify:* `ls is4r-chiron-develop/test_project is4r-chiron-ui-develop/package.json` — both resolve.

**A2. Confirm the Docker daemon is up.**
```bash
docker ps
```
*Verify:* prints a table (even if empty), not "Cannot connect to the Docker daemon".

**A3. Validate the Compose file.**
```bash
docker compose config --quiet
```
*Verify:* exit code 0, no output. ✅ verified

**A4. Confirm the host warehouse exists** (skip only if you switched the DSN to `db`).
```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d chiron -c '\dn'
```
*Verify:* lists schemas including `dataset1_stored`.

**A5. Build and start.**
```bash
docker compose up --build -d          # add VITE_MUI_KEY=… in front if you have one
```
*Verify:* `docker compose ps` shows `chiron-db`, `chiron-api`, `chiron-ui`,
`chiron-dashboard` all `Up`, with `api` and `db` `(healthy)`. First build is ~10-15 min.

**A6. Smoke-test every service.**
```bash
curl -s  http://localhost:8000/api/version/                      # {"chiron":"Unknown"}
curl -so /dev/null -w 'ui %{http_code}\n'   http://localhost:3000/     # ui 200
curl -so /dev/null -w 'dash %{http_code}\n' http://localhost:8787/     # dash 200
docker exec chiron-db pg_isready -U postgres -d chiron           # accepting connections
```
*Verify:* all four as annotated. ✅ verified against the already-running stack

**A7. Confirm the demo login.**
```bash
curl -s http://localhost:8787/api/state | head -c 200
```
*Verify:* JSON with `"chiron":{"api":{... "state":"running"`. In the browser at
:8787 → Chiron tab, all three components show green. ✅ verified

**Everyday commands**
```bash
docker compose up -d          # restart after a Docker/machine restart (no rebuild)
docker compose logs -f api    # follow one service (db | api | ui | dashboard)
docker compose stop           # stop, keep data + images
docker compose build ui       # rebuild one image
```

---

### Path B — Host-local (no Docker; needed to develop the tools)

Each subproject is its own venv. Paths are load-bearing (Order dependency #4).

**B1. Install the four tool venvs.**
```bash
cd /path/to/chiron-dashboard
for t in chiron-validator chiron-benchmark chiron-scanners; do
  python3 -m venv "$t/.venv" && "$t/.venv/bin/pip" install -e "$t"
done
python3 -m venv chiron-data-validator/venv
chiron-data-validator/venv/bin/pip install -r chiron-data-validator/requirements.txt
```
*Verify:* `ls chiron-*/.venv/bin/chiron-* chiron-data-validator/venv/bin/python` lists
`chiron-validator`, `chiron-bench`, `chiron-vulnscan`, `chiron-ineffscan`. ✅ verified

**B2. Install the dashboard venv — plus `requests`, which `requirements.txt` omits.**
```bash
python3 -m venv chiron-dashboard/.venv
chiron-dashboard/.venv/bin/pip install -r chiron-dashboard/requirements.txt requests
```
*Verify:* `chiron-dashboard/.venv/bin/python -c "import flask, requests; print('ok')"` → `ok`. ✅ verified
(See Common Issues #2 — without `requests` the app will not import.)

**B3. Start Chiron itself** (in the source repos, not this one).
```bash
cd is4r-chiron-develop && python3 -m venv .venv && .venv/bin/pip install -r requirements/dev.txt
cd test_project && ../.venv/bin/python manage.py migrate --noinput
../.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
```
*Verify:* `curl -s http://127.0.0.1:8000/api/version/` → `{"chiron":"Unknown"}`.
⚠️ **Not verified here** — the source repos are empty in this checkout. Commands are
taken from `docs/CHIRON_OVERVIEW.md` §8, which records them as verified on this OS.

**B4. Start the Chiron UI** (optional; only for UI work).
```bash
cd is4r-chiron-ui-develop && pnpm install && node_modules/.bin/vite --port 3000
```
*Verify:* `curl -so /dev/null -w '%{http_code}\n' http://localhost:3000/` → `200`. ⚠️ not verified here.

**B5. Export the tool credentials.**
```bash
export CHIRON_BASE_URL=http://127.0.0.1:8000 CHIRON_USER=admin \
       CHIRON_PASSWORD=demo1234 CHIRON_DATASET=dataset1_stored
```
*Verify:* `echo $CHIRON_BASE_URL` → `http://127.0.0.1:8000`.

**B6. Build the validator expectations DB — required before any validator run.**
```bash
cd chiron-validator && .venv/bin/chiron-validator load
```
*Verify:* prints `Loaded specs: 127 endpoints (105 testable, 17 overrides applied)`
and creates `validator.db`. ✅ verified

**B7. Start the dashboard.**
```bash
cd chiron-dashboard && .venv/bin/python run.py          # dev
# or: .venv/bin/gunicorn -w 1 --threads 8 -b 0.0.0.0:8787 'dashboard:create_app()'
```
*Verify:* `curl -so /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/` → `200`.
Keep `-w 1` — the process/job state is in-memory and must be single-source. ✅ verified (app factory + HTTP 200)

---

### Running the tools

| Tool | Command (from repo root) | Verify |
|---|---|---|
| API validator | `cd chiron-validator && .venv/bin/chiron-validator run --include-v1` | `Run #N: 63 passed, 2 failed, 3 unreached, 40 skipped` + `VALIDATOR_REPORT.md` written ✅ |
| Benchmark | `cd chiron-benchmark && .venv/bin/chiron-bench --iterations 30 --burst-total 60 --concurrency 8` | `Controls: 57 pass / 3 fail / 0 n/a (of 60)` + `PERFORMANCE_REPORT.md` ✅ |
| Security scan | `cd chiron-scanners && .venv/bin/chiron-vulnscan` | `vulnscan: N findings …` + `results/vuln.json` ✅ |
| Inefficiency scan | `cd chiron-scanners && .venv/bin/chiron-ineffscan` | `ineffscan: N findings` + `results/ineff.json` ✅ |
| Data quality | `cd chiron-data-validator && venv/bin/python chiron_validator.py validate --dataset dataset1_stored` | `N issues across 1 dataset(s) scanned`. Exit `0`=clean, `1`=issues, `2`=couldn't run ✅ |

`--fail-on-error` (validator) / `--fail-on-miss` (benchmark) turn these into CI gates.

### Tests

```bash
cd chiron-validator      && .venv/bin/pip install -e ".[dev]" && .venv/bin/python -m pytest -q   # 24 passed ✅
cd chiron-benchmark      && .venv/bin/pip install pytest && .venv/bin/python -m pytest -q        # 5 passed  ✅
cd chiron-data-validator && venv/bin/python -m unittest discover -q                              # 70 tests OK ✅
```
`chiron-scanners/tests/` is **empty** — there is no test suite for the scanners.

### Lint

**This repo has no linter configured** — no ruff/flake8/eslint/pre-commit config, and
the dashboard front-end is plain JS with no build step. Linting lives in the Chiron
source repos: `ruff` (backend, `requirements/dev.txt`) and `eslint` (UI,
`pnpm run lint`).

### CI

`integration/ci-chiron-quality.yml` is a **template to drop into the Chiron backend
repo's** `.github/workflows/` — it is not active here (this repo has no `.github/`).
`integration/nightly_quality_run.sh` is a cron/launchd entry point that runs the
validator + benchmark against an already-running Chiron and appends to
`integration/history/trend.log`.

### Optional — RDCRN live catalog checker

```bash
cd rdcrn-catalog-checker
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium          # required; requirements.txt alone is not enough
.venv/bin/python ui_check.py                   # no credentials needed; exit 0 = all passed
.venv/bin/python sso_session.py cli-login      # interactive; prompts for your own credentials
.venv/bin/python sso_session.py status         # is the saved session still good?
```
⚠️ **Not verified here** — requires interactive SSO against a live production
deployment. `.session/state.json` is a live login session; treat it as a password.

---

## Common Issues

**1. Build fails immediately — the Chiron source repos are missing.** Two distinct errors:
- `api`: `failed to compute cache key … "/requirements": not found` (also `/chiron`,
  `/test_project`) — `is4r-chiron-develop/` is empty.
- `ui`: `failed to read dockerfile: open Dockerfile: no such file or directory` —
  `is4r-chiron-ui-develop/` is empty (its Dockerfile lives inside that repo).

Fix: complete Step 0 before building. ✅ both reproduced

**2. `ModuleNotFoundError: No module named 'requests'` when starting the dashboard host-local.**
`chiron-dashboard/requirements.txt` lists only `flask` and `gunicorn`, but
`dashboard/rdcrnlogin.py` imports `requests` at module scope. The Docker image gets it
by accident (a transitive dep of `docker>=7,<8`); a host-local install does not.
Fix: `chiron-dashboard/.venv/bin/pip install requests`. Permanent fix: add
`requests>=2.28` to `chiron-dashboard/requirements.txt`. ✅ reproduced

**3. Scanners report ~0 findings, and the validator's data-dependent checks look clean.**
Not a clean bill of health — the scanners statically analyse
`is4r-chiron-develop/` + `is4r-chiron-ui-develop/`, and **silently find nothing when
those trees are empty** rather than erroring. With empty trees this checkout produced
`vulnscan: 2 findings` / `ineffscan: 0 findings`. Fix: Step 0, then re-run. ✅ reproduced

**4. Every warehouse query returns 500 but login works.**
The backend reads metadata from a baked SQLite snapshot (so auth and project structure
work) while concept data comes from Postgres. Either the host Postgres on `:5432` is
down / has no `chiron` database, or you pointed the DSN at the container's `db`, which
starts **empty and is never seeded**. Fix: start your host Postgres, or edit
`CHIRON_SQL_ALCHEMY_CONNECTION_STRING` in `docker-compose.yml` and load the `db`
warehouse yourself (published on `localhost:5433`).

**5. First build is very slow / `port is already allocated`.**
The backend build context is the entire `is4r-chiron-develop/` tree, which has **no
`.dockerignore`** — its 253 MB `.venv` and `.git` are uploaded to the daemon on every
build. Adding a `.dockerignore` with `.venv/` and `.git/` cuts this sharply. For port
conflicts, `lsof -nP -iTCP:8787 -sTCP:LISTEN` (repeat for 8000/3000/5433) finds the
holder — often an older copy of this same stack still running.

**6. `docker compose down -v` wiped the data.**
`-v` deletes the `chiron_chiron-pgdata` and `chiron_chiron-dashboard-data` volumes
(warehouse + dashboard history/results). Use plain `down` or `stop`.

---

<sub>**Verification status.** Every command marked ✅ was executed on this machine
(macOS 24.6.0, Python 3.12.5, Docker 28.0.0) against the already-running Compose stack.
Not verified: the full `docker compose up --build` from cold (blocked by the empty
Chiron source repos), host-local Chiron backend/UI startup (same blocker), and the
RDCRN SSO login flow (needs interactive credentials against production). Generated
report files touched during verification were restored to their committed state; the
`.venv` directories created by Path B were left in place (all gitignored).</sub>
