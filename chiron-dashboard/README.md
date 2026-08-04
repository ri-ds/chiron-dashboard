# Chiron Control — team dashboard

One shared, good-looking web page to **start/stop Chiron** and **run every tool
built around it** (validator, vulnerability scan, inefficiency scan, benchmark
suite) — trigger them, watch them run, and read results inline, without touching
a terminal or opening markdown files.

It is a **control layer**: it calls the existing scripts/data stores as-is
(`chiron-validator/`, `chiron-benchmark/`, the scan reports, the trend log). It
does not reimplement any of them.

![sections: Chiron process control · Tools launcher · Activity history]

## What it does
- **Chiron process control** — start / stop / restart the **API backend** and
  **UI frontend**, with a live status badge (running / starting / stopped /
  crashed), uptime, who started it, and a tail-the-log viewer per component.
- **Tool launcher** — a card per tool with a **Run** button that shells out to
  the real CLI (validator, benchmark) or loads the latest stored scan
  (vuln/inefficiency — those are produced by a Claude multi-agent audit, so the
  panel surfaces the stored results; see *Re-running the scans* below).
- **Live, shared status** — everything polls `/api/state` every 2s, so a status
  badge + elapsed time update for everyone watching, not just whoever clicked.
- **Inline results** — when a tool finishes, its findings/pass-fail tables render
  on the page (validator endpoint failures, benchmark control misses, security /
  efficiency findings with severity), no markdown-hunting.
- **Shared history** — a name-tagged activity table (who ran what, when, outcome)
  seeded from the existing nightly `trend.log` and appended to on every action.
- **Lightweight accountability** — asks for a name once per browser (stored in
  `localStorage`), attached to every start/stop and run. No login.
- **Concurrency safety** — a control that's already running/starting is disabled
  and shows who triggered it; the backend also rejects a colliding run with
  `409 already running (started by <name>)`.

## Run it

```bash
cd chiron-dashboard
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# dev (single process, threaded):
.venv/bin/python run.py                      # binds 0.0.0.0:8787
```

Override host/port with `CHIRON_DASHBOARD_HOST` / `CHIRON_DASHBOARD_PORT`.

### Reaching it (the whole team)
It binds `0.0.0.0:8787`, so anyone on the **internal network** opens
`http://<the-host-machine-ip>:8787` (e.g. `http://192.168.1.66:8787`). Find the
host IP with `ipconfig getifaddr en0` (macOS) / `hostname -I` (Linux).

Chiron itself stays bound to the host's `localhost` (:8000 / :3000) — the *shared*
thing is this dashboard (control/status/logs/results). Making Chiron's own UI
team-reachable is a separate change (Django `ALLOWED_HOSTS`, etc.) and out of scope.

### Keeping it running (so it's there when you're not)
Use a process supervisor with gunicorn (one worker so the in-memory process/job
state is authoritative; threads for concurrent pollers):

```bash
.venv/bin/gunicorn -w 1 --threads 8 -b 0.0.0.0:8787 'dashboard:create_app()'
```

- **Linux (systemd):** a unit running the gunicorn line above with
  `Restart=always`, `WorkingDirectory=…/chiron-dashboard`.
- **macOS:** a `launchd` LaunchAgent plist running the same command with
  `KeepAlive=true`, or `nohup .venv/bin/python run.py &` for a quick shared run.

## ⚠️ Security posture (read this)
This dashboard can **start/stop processes and run tools with no authentication**
(name-tagging is accountability, not access control — by design, per the brief).
Therefore it **must stay on the internal network only** — behind the firewall /
VPN, **never port-forwarded or exposed to the public internet**. Network-level
isolation is the access control.

All data shown is **synthetic** (Synthea-style warehouse data + synthetic query
payloads) — same rule as every Chiron tool. No real PHI passes through it.

## Re-running the scans
The **validator** and **benchmark** are re-runnable CLIs, so their Run buttons
execute a fresh run. The **vulnerability** and **inefficiency** scans are produced
by a Claude multi-agent audit (not a standalone script), so their buttons **load
the latest stored results** from `data/findings.json`. To regenerate a fresh scan,
re-run the Claude audit workflow that writes `findings.json` (documented in
`CHIRON_REVIEW_LOG.md`), then click *Load latest*.

## Architecture
```
run.py ─ Flask app (dashboard/__init__.py)
  ├─ processes.py   ProcessManager  → start/stop/restart Chiron (subprocess + port probe + log tail)
  ├─ jobs.py        JobRunner        → run tool CLIs as tracked subprocesses; concurrency locks
  ├─ results.py     parse validator/benchmark JSON + findings.json into UI tables
  ├─ store.py       SQLite activity/history (data/dashboard.db); seeds from trend.log
  └─ static/        index.html · styles.css · app.js  (single polished page, no build step)
```

## Adding another control later
- **A new Chiron component** (e.g. a worker): add an entry to
  `dashboard/config.py::COMPONENTS` with `label`, `cwd`, `cmd`, `port`,
  `probe_url`. The card, status, logs, and start/stop/restart wiring are generated
  automatically.
- **A new tool with a real CLI:** add to `dashboard/config.py::TOOLS` with
  `kind:"subprocess"`, `cwd`, `cmd`, optional `env`, `requires_chiron`, and a
  `result` key; then add a parser branch in `dashboard/results.py::parse` that
  turns its output store into `{outcome, headline, stats, columns, rows}`.
- **A new report-backed panel:** add to `TOOLS` with `kind:"report"` and a
  `results.py` parser that reads its stored file. The Run button becomes
  *Load latest*.

No frontend changes are needed — the page renders whatever `/api/state` and
`/api/tools/<tool>/result` return.
