# Chiron Dashboard

A control dashboard plus five quality tools for Chiron, packaged so the whole stack
stands up with **one command**. Everything here is read-only against Chiron and runs on
**synthetic/local data**.

## What's in here

| Folder | What it is |
|---|---|
| `chiron-dashboard/` | Web dashboard — the front door. Start/stop Chiron's containers, run every tool, read results. |
| `chiron-validator/` | Checks Chiron's API returns the right **types/shapes** on every endpoint (finds crashes and contract breaks). |
| `chiron-data-validator/` | **Data quality** — missing values, category typos, numeric outliers, cardinality. |
| `chiron-scanners/` | **Security** scan (secrets, DEBUG, XSS, deps, live probes) + **inefficiency** scan (N+1 queries, pagination, dead code). |
| `chiron-benchmark/` | **Performance** suite — latency p50/p95/p99, throughput, UI flow timings, graded against pass/fail controls. |
| `rdcrn-catalog-checker/` | Standalone read-only checker for the live RDCRN data catalog (SSO-gated; you supply the session). Not part of the compose stack. |
| `deploy/` | Dockerfiles, nginx config, container settings, and the deployment guide. |
| `integration/` | CI check + nightly scheduled run. |
| `docs/` | All write-ups (overview, findings, benchmarks, meeting notes). |

## Layout (important)

The compose stack **builds Chiron from source**, and Chiron's own two repos are
deliberately *not* included here (they're a separate project, and one is ~700 MB of
`node_modules`). Put them alongside, inside this folder:

```
chiron-dashboard/              <- this repo
├── is4r-chiron-develop/       <- Chiron backend  (you provide)
├── is4r-chiron-ui-develop/    <- Chiron UI       (you provide)
├── chiron-dashboard/          <- the dashboard app itself
├── docker-compose.yml
├── deploy/
└── ...
```

Both are gitignored, so they'll never get committed by accident.

## Run it

Requires **Docker Desktop running**.

```bash
docker compose up --build
```

Then open the dashboard: **http://localhost:8787**

| Service | URL |
|---|---|
| Dashboard (front door) | http://localhost:8787 |
| Chiron UI | http://localhost:3000 |
| Chiron API | http://localhost:8000 |
| Postgres (container) | `localhost:5433` |

Demo login: `admin` / `demo1234`.

If Docker restarts or the machine sleeps, bring it back with `docker compose up -d`.

## Data

Nothing is seeded, imported, or ETL'd by this stack. By default the backend points at
an **existing host Postgres** (`host.docker.internal:5432`, database `chiron`) so the
data-dependent tools have something to read. To run fully self-contained on the
container's own Postgres instead, change `host.docker.internal` → `db` in the `api`
service's `CHIRON_SQL_ALCHEMY_CONNECTION_STRING` (that warehouse starts empty).

See [`deploy/README.md`](deploy/README.md) for the full deployment guide.

## Dev / demo only

This stack is **not hardened for production** — `DEBUG` is on, credentials are demo
values, the backend runs on `runserver`, and the dashboard mounts the Docker socket to
control containers. The dashboard shows a `local · dev only` marker as a reminder.
`deploy/README.md` lists exactly what to change before it goes anywhere else.
