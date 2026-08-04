# Chiron — one-command stack (docker-compose)

Stand up the whole thing with a single command. The **control dashboard is the
front door**, and from it you can start/stop Chiron and run all the tools.

## Prerequisite

**Docker Desktop must be installed and running.** Check with:

```bash
docker ps
```

If that errors with "Cannot connect to the Docker daemon", start Docker Desktop
first and wait for it to finish booting.

## Run it

From the repo root (`new_chiron/`):

```bash
docker compose up --build
```

First run builds the images (a few minutes: it installs the backend's Python
deps and builds the React UI). After that, startup is quick. Add `-d` to run in
the background.

Then open the **dashboard**: http://localhost:8787

| Service            | URL                              | Notes                          |
|--------------------|----------------------------------|--------------------------------|
| Dashboard (front door) | http://localhost:8787        | Control + run the tools        |
| Chiron UI          | http://localhost:3000            | The React app (via nginx)      |
| Chiron API         | http://localhost:8000            | Django + DRF                   |
| Postgres warehouse | `localhost:5433` (`chiron` db)   | user/pass `postgres`/`postgres` (host 5432 left for your local PG)|

Log in with the demo account **`admin` / `demo1234`**.

## What the dashboard controls now

In this stack the dashboard drives **containers**, not local processes. On the
Chiron tab you get Start / Stop / Restart / Logs for each service:

- **db** (Postgres), **api** (backend), **ui** (frontend).

The tools (validator, data quality, vulnerability scan, inefficiency scan,
benchmark) run inside the dashboard container and target the `api` service
automatically.

> Stopping **db** or **api** will make the app error until you start it again —
> that is expected; just Restart from the same panel.

## Data: using your existing host warehouse

By default this stack points the backend at your **existing host Postgres**
(`host.docker.internal:5432`, the `chiron` database), which already holds
dataset1/2/3 — so the data-dependent tools (data quality, validator, benchmark)
work out of the box. Nothing is seeded, imported, or ETL'd; the containers just
read what is already on your machine.

The stack also ships its own Postgres (service `db`, published on
`localhost:5433`). In this mode it is **unused and empty**. To run fully
self-contained on it instead, change `host.docker.internal` back to `db` in the
api service's `CHIRON_SQL_ALCHEMY_CONNECTION_STRING` in `docker-compose.yml`
(that warehouse then starts empty until you load it yourself).

Login and project structure come from a snapshot of the existing SQLite metadata
baked into the backend image.

## Everyday commands

```bash
docker compose up -d --build     # build + start in the background
docker compose ps                # what's running
docker compose logs -f api       # follow the backend logs (or db / ui / dashboard)
docker compose stop              # stop everything (keeps data + images)
docker compose down              # stop + remove containers (named volumes persist)
docker compose down -v           # also delete the Postgres + dashboard volumes
docker compose build ui          # rebuild a single image after changes
```

## Resuming after Docker restarts / sleep

If Docker Desktop quits or the machine sleeps, the containers stop. Bring the
whole stack back with one command (no rebuild needed):

```bash
docker compose up -d
```

## Dev / demo only — do not deploy as-is

This stack is built for **local development and demos**. The dashboard header
shows a `local · dev only` pill as a reminder. Before it goes anywhere beyond
your machine, it needs hardening:

- **`DEBUG=True`** in the backend leaks internals on errors — turn it off.
- **Hardcoded `SECRET_KEY`** and **`ALLOWED_HOSTS=['*']`** (the docker block in
  `settings_custom.py`) — supply a real secret via env and scope the hosts.
- **Demo credentials** (`admin` / `demo1234`, and `postgres`/`postgres`) —
  replace with real, secret-managed credentials.
- **`runserver`** serves the backend — use gunicorn/uWSGI + proper static serving.
- **Docker socket** is mounted into the dashboard — never expose the dashboard
  publicly while that is true.

## Notes

- **Host-local mode is unchanged.** All container-specific behavior is gated on
  environment variables (`CHIRON_IN_DOCKER`, `CHIRON_DASHBOARD_DOCKER`), so
  running the backend with `manage.py runserver` or the dashboard with
  `python run.py` on your machine works exactly as before.
- **Docker socket.** The dashboard mounts `/var/run/docker.sock` so it can
  start/stop the sibling containers. That is broad access; it is fine for this
  internal, local/dev tool and should not be exposed publicly.
- **MUI license key (optional).** The UI build accepts a `VITE_MUI_KEY`. Set it
  in your shell before building if you have one; it is not required:
  ```bash
  VITE_MUI_KEY=your-key docker compose up --build
  ```
- **Files.** Everything for this stack lives in `deploy/` plus the root
  `docker-compose.yml` and `.dockerignore`. The only change inside the Chiron
  repos is the env-gated block in
  `is4r-chiron-develop/test_project/project/settings_custom.py`.
