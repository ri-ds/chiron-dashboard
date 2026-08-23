"""Static configuration for the Chiron control dashboard.

Everything here points at the *existing* repos/tools/data stores — the dashboard
is a control layer, it does not reimplement anything. Paths are resolved from the
workspace root so the dashboard can run from anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

# workspace root = parent of chiron-dashboard/
ROOT = Path(__file__).resolve().parents[2]

BACKEND = ROOT / "is4r-chiron-develop"
UI = ROOT / "is4r-chiron-ui-develop"
VALIDATOR = ROOT / "chiron-validator"
BENCHMARK = ROOT / "chiron-benchmark"
SCANNERS = ROOT / "chiron-scanners"
DATA_VALIDATOR = ROOT / "chiron-data-validator"   # pre-existing data-quality tool (unmodified)
INTEGRATION = ROOT / "integration"
# Checks a LIVE remote deployment rather than the local stack, so its tools never
# point at CHIRON_BASE_URL. Which deployment is decided by the Login tab and stored
# beside the session (sso_session.set_site); the directory name is historical.
RDCRN = ROOT / "rdcrn-catalog-checker"

DATA = Path(__file__).resolve().parent.parent / "data"
LOG_DIR = DATA / "logs"
DB_PATH = DATA / "dashboard.db"
FINDINGS_STORE = DATA / "findings.json"  # persisted security+efficiency scan results
DATAQUALITY_RULES = DATA / "dataquality_rules.json"  # editable data-quality rule settings

# Credentials the tools use to reach Chiron's public API (local dev only).
# Read from the environment so the same config works host-local (default
# 127.0.0.1:8000) and inside docker-compose (compose sets CHIRON_BASE_URL to the
# `api` service). Defaults preserve the original host-local behavior.
CHIRON_ENV = {
    "CHIRON_BASE_URL": os.environ.get("CHIRON_BASE_URL", "http://127.0.0.1:8000"),
    "CHIRON_USER": os.environ.get("CHIRON_USER", "admin"),
    "CHIRON_PASSWORD": os.environ.get("CHIRON_PASSWORD", "demo1234"),
    "CHIRON_DATASET": os.environ.get("CHIRON_DATASET", "dataset1_stored"),
}

# When the dashboard runs inside the docker-compose stack, it controls Chiron's
# services as CONTAINERS (see dockerctl.py) instead of spawning local subprocesses.
IN_DOCKER = bool(os.environ.get("CHIRON_DASHBOARD_DOCKER"))

# ---- Chiron components the dashboard can start/stop/restart ----
# Chiron itself stays host-local (127.0.0.1); the *dashboard* is what the team
# shares. `probe_url` is polled to decide running/stopped.
COMPONENTS = {
    "api": {
        "label": "API backend",
        "detail": "Django + DRF (test_project)",
        "cwd": str(BACKEND / "test_project"),
        "cmd": [str(BACKEND / ".venv" / "bin" / "python"), "manage.py",
                "runserver", "127.0.0.1:8000", "--noreload"],
        "port": 8000,
        "probe_url": "http://127.0.0.1:8000/api/version/",
        "ready_timeout": 30,
    },
    "ui": {
        "label": "UI frontend",
        "detail": "React + Vite dev server",
        "cwd": str(UI),
        "cmd": [str(UI / "node_modules" / ".bin" / "vite"), "--port", "3000"],
        "port": 3000,
        "probe_url": "http://localhost:3000/",
        "ready_timeout": 40,
    },
}

# ---- Chiron components as CONTAINERS (docker-compose mode) ----
# Used only when IN_DOCKER. status/logs/start/stop/restart are done via the Docker
# socket by container name (see dockerctl.py). `url` is the browser-facing address
# shown in the UI; `port` is the published host port.
DOCKER_COMPONENTS = {
    "db": {
        "label": "Database", "detail": "Postgres 16 (warehouse)",
        "container": "chiron-db", "port": 5433,
        "url": "postgresql://localhost:5433/chiron",
    },
    "api": {
        "label": "API backend", "detail": "Django + DRF (test_project)",
        "container": "chiron-api", "port": 8000, "url": "http://localhost:8000/",
    },
    "ui": {
        "label": "UI frontend", "detail": "React build served by nginx",
        "container": "chiron-ui", "port": 3000, "url": "http://localhost:3000/",
    },
}

# ---- Tools the dashboard can launch ----
# kind "subprocess" runs a real CLI; kind "report" re-loads a persisted data store
# (the vuln/inefficiency scans are produced by a Claude multi-agent audit, not a
# standalone script — the dashboard surfaces their results and refreshes from the
# store; see README).
TOOLS = {
    "validator": {
        "label": "Validator",
        "detail": "Rules-based check of Chiron's API",
        "info": "A rules-based check of Chiron's API. It verifies Chiron's data and "
                "concepts against a defined set of validation rules (the expected "
                "type/shape of every field on every endpoint). The results list every "
                "rule that failed — each concept or field found to be wrong, and why.",
        "kind": "subprocess",
        "cwd": str(VALIDATOR),
        "cmd": [str(VALIDATOR / ".venv" / "bin" / "chiron-validator"), "run", "--include-v1"],
        "env": CHIRON_ENV,
        "result": "validator",
        "requires_chiron": True,
        "selectable_dataset": True,
    },
    "benchmark": {
        "label": "Benchmark suite",
        "detail": "API + UI performance vs. controls",
        "info": "Drives the live API (latency p50/p95/p99, throughput, error rate) and "
                "the key UI flows with synthetic data, then checks every measurement "
                "against a set of performance controls (pass/fail thresholds).",
        "kind": "subprocess",
        "cwd": str(BENCHMARK),
        "cmd": [str(BENCHMARK / ".venv" / "bin" / "chiron-bench")],
        "env": CHIRON_ENV,
        "result": "benchmark",
        "requires_chiron": True,
    },
    "vulnscan": {
        "label": "Vulnerability scan",
        "detail": "Live security scan",
        "info": "Runs a fresh security scan every time you press Run: static pattern "
                "checks over the backend + UI source (hardcoded secrets, DEBUG, XSS, "
                "SQL-injection patterns, unsafe deserialization), dependency version-floor "
                "checks, and live probes of the running API (security headers, DEBUG "
                "leakage, anonymous access). Results reflect the code + API right now.",
        "kind": "subprocess",
        "cwd": str(SCANNERS),
        "cmd": [str(SCANNERS / ".venv" / "bin" / "chiron-vulnscan")],
        "env": CHIRON_ENV,
        "result": "vulnscan",
        "requires_chiron": False,
    },
    "ineffscan": {
        "label": "Inefficiency scan",
        "detail": "Live performance / quality scan",
        "info": "Runs a fresh code-quality scan every time you press Run: N+1 ORM queries "
                "on request paths, oversized pagination defaults, dead/duplicated code, "
                "disabled caching, and front-end bundle bloat. Results reflect the source "
                "as it is right now.",
        "kind": "subprocess",
        "cwd": str(SCANNERS),
        "cmd": [str(SCANNERS / ".venv" / "bin" / "chiron-ineffscan")],
        "env": CHIRON_ENV,
        "result": "ineffscan",
        "requires_chiron": False,
    },
    # Pre-existing standalone data-quality validator, wired in UNMODIFIED — the
    # dashboard just drives its CLI and reads its --json-out. It exits 1 when it
    # finds issues (0=clean, 1=issues, 2=couldn't run), so 0 and 1 are both
    # "ran successfully" — see success_exit_codes.
    "dataquality": {
        "label": "Data quality",
        "detail": "Live data-quality checks on concept statistics",
        "info": "Checks the actual DATA (not the API shape): it logs into Chiron, pulls "
                "every concept's statistics, and flags high missing-value rates, category "
                "typos/rare values, numeric outliers, and implausible category cardinality. "
                "NOTE: 'high missingness' is a symptom, not proof — Chiron's ETL silently "
                "nulls values that fail their type cast, and that record isn't exposed by "
                "the API. Runs fresh every time.",
        "kind": "subprocess",
        "cwd": str(DATA_VALIDATOR),
        "cmd": [str(DATA_VALIDATOR / "venv" / "bin" / "python"), "chiron_validator.py", "validate",
                "--base-url", CHIRON_ENV["CHIRON_BASE_URL"],
                "--username", CHIRON_ENV["CHIRON_USER"],
                "--password", CHIRON_ENV["CHIRON_PASSWORD"],
                "--rules-config", str(DATAQUALITY_RULES),
                "--json-out", str(DATA / "dataquality.json")],
        "env": CHIRON_ENV,
        "result": "dataquality",
        "requires_chiron": True,
        "success_exit_codes": [0, 1],
        "selectable_dataset": True,
        # Without this flag it scans every project; with it, just the one.
        "dataset_flag": "--dataset",
    },
    # ---- The same two tools, against the SIGNED-IN LIVE site ----------------
    # Which site that is comes from the Login tab, not from here (sso_session records
    # it). These strings therefore must not name a specific deployment.
    # They run unmodified. live_runner.py puts a session-injecting proxy in front
    # so their normal auth path still works behind Shibboleth (see that script).
    # requires_chiron is False: the target is remote, so the local stack being
    # down is irrelevant.
    "dataquality_live": {
        "label": "Data quality · live",
        "detail": "Data-quality checks against the signed-in live site",
        "info": "The same data-quality tool, run unmodified against whichever site "
                "you signed into on the Login tab. It reads concept statistics and "
                "flags missingness, category typos, outliers and odd cardinality. "
                "Sign in first; without a session it stops and says so. The dataset "
                "comes from the picker — the run names it in its output, so check "
                "that it is the one you meant.",
        "kind": "subprocess",
        "cwd": str(RDCRN),
        "cmd": [str(RDCRN / ".venv" / "bin" / "python"), "live_runner.py",
                "--tool", "dataquality"],
        "result": "dataquality_live",
        # The live site's own dataset list drives this (see /api/live/datasets), so a
        # live run can be aimed at one dataset instead of whatever the API happens to
        # return first.
        "selectable_dataset": True,
        "dataset_flag": "--dataset",
        "requires_chiron": False,
        # Needs a live session from the Login tab; without one the run can only
        # fail, so the launcher refuses it up front instead of burning a job.
        "requires_session": True,
        # 1 = issues found, 2 = no session. Both are results, not crashes.
        "success_exit_codes": [0, 1, 2],
    },
    "validator_live": {
        "label": "Validator · live",
        "detail": "API shape checks against the signed-in live site",
        "info": "The API validator run against whichever site you signed into on the "
                "Login tab. v1 endpoints are skipped deliberately: they need a Django "
                "session login that does not exist behind Shibboleth.\n\n"
                "Some endpoints may be refused. Do NOT read that as proof your account "
                "lacks access: a refusal looks identical whether it is a permission "
                "limit (an aggregate-level account genuinely cannot see subject-level "
                "data), a real defect, or a misconfigured run — the wrong target "
                "site, a dataset that does not exist there, or a timeout too short for "
                "the endpoint all surface as refusals too. Check the target and dataset "
                "the run reports before drawing any conclusion from a refusal.",
        "kind": "subprocess",
        "cwd": str(RDCRN),
        "cmd": [str(RDCRN / ".venv" / "bin" / "python"), "live_runner.py",
                "--tool", "validator"],
        "result": "validator_live",
        # The live site's own dataset list drives this (see /api/live/datasets), so a
        # live run can be aimed at one dataset instead of whatever the API happens to
        # return first.
        "selectable_dataset": True,
        "dataset_flag": "--dataset",
        "requires_chiron": False,
        # Needs a live session from the Login tab; without one the run can only
        # fail, so the launcher refuses it up front instead of burning a job.
        "requires_session": True,
        "success_exit_codes": [0, 1, 2],
    },
}

HOST = os.environ.get("CHIRON_DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("CHIRON_DASHBOARD_PORT", "8787"))
