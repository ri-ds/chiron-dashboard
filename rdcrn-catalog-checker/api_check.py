#!/usr/bin/env python3
"""Authenticated RDCRN API check, shaped for the dashboard.

monitor.py is the CLI/cron entry point and prints for humans. This is the same idea
with a machine-readable result: it refreshes the SSO session, reads the catalog's
real endpoints, and writes results/api_check.json for the dashboard to render.

No credentials are involved. It reuses the saved session (.session/state.json) and
completes the SAML chain silently; if that session is dead it says so and exits 2
rather than pretending the account lost access.

Exit codes match the rest of the toolchain:
    0  authenticated, endpoints answered as expected
    2  no usable session — a human must run `sso_session.py cli-login` once
    3  authenticated but an endpoint answered wrong (the interesting failure)
    1  usage/internal error
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import requests

import sso_session

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = sso_session.BASE
OUT = os.environ.get("API_CHECK_JSON", os.path.join(HERE, "results", "api_check.json"))
TIMEOUT = 30

# Endpoint -> what it tells us. Kept explicit so a change in the catalog's API
# surface shows up as a failed check rather than a silently skipped one.
ENDPOINTS = [
    ("/api/version/", "Chiron version"),
    ("/api/v2/auth/", "Signed-in user"),
    ("/api/v2/dataset/", "Dataset list"),
]


def _write(payload: dict) -> None:
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"JSON: {OUT}")
    except OSError as e:
        print(f"! could not write {OUT}: {e}", file=sys.stderr)


def main() -> int:
    started = datetime.now(timezone.utc)
    payload = {
        "tool": "rdcrn_api",
        "generated": started.isoformat(timespec="seconds"),
        "target": BASE,
        "session": "absent",
        "chiron_version": None,
        "user": None,
        "checks": [],
        "datasets": [],
        "exit": 1,
    }

    print(f"Target: {BASE}")
    code, cookie = sso_session.refresh(verbose=True)
    if code != 0:
        payload["session"] = "expired"
        payload["exit"] = 2
        payload["checks"] = [{
            "name": "SSO session", "status": "fail",
            "detail": "No usable session. Run: sso_session.py cli-login",
        }]
        _write(payload)
        print("\nNOT AUTHENTICATED — a one-time interactive login is required.")
        return 2

    payload["session"] = "live"
    s = requests.Session()
    s.headers["Cookie"] = cookie
    s.headers["User-Agent"] = "rdcrn-catalog-checker/api_check"

    worst = 0
    data_by_path = {}
    for path, label in ENDPOINTS:
        try:
            r = s.get(BASE + path, timeout=TIMEOUT)
        except Exception as e:
            payload["checks"].append({"name": label, "status": "fail",
                                      "detail": f"{type(e).__name__}"})
            worst = max(worst, 3)
            continue
        if r.status_code != 200:
            payload["checks"].append({"name": label, "status": "fail",
                                      "detail": f"HTTP {r.status_code}"})
            worst = max(worst, 3)
            continue
        try:
            body = r.json()
        except ValueError:
            payload["checks"].append({"name": label, "status": "fail",
                                      "detail": "response was not JSON"})
            worst = max(worst, 3)
            continue
        data_by_path[path] = body
        payload["checks"].append({"name": label, "status": "pass",
                                  "detail": f"HTTP 200 · {path}"})

    version = (data_by_path.get("/api/version/") or {}).get("chiron")
    payload["chiron_version"] = version
    auth = (data_by_path.get("/api/v2/auth/") or {}).get("user") or {}
    payload["user"] = auth.get("username") or auth.get("name")

    # Per-dataset detail: subject counts and last import are the numbers worth
    # watching, because a broken import shows up here before anywhere else.
    datasets = (data_by_path.get("/api/v2/dataset/") or {}).get("datasets") or []
    for ds in datasets:
        slug = ds.get("unique_id")
        row = {"name": ds.get("name"), "unique_id": slug,
               "subjectCount": None, "lastImport": None, "accessLevel": None,
               "status": "pass", "detail": ""}
        if slug:
            try:
                d = s.get(f"{BASE}/api/v2/dataset/{slug}/", timeout=TIMEOUT)
                if d.status_code == 200:
                    j = d.json()
                    row.update(subjectCount=j.get("subjectCount"),
                               lastImport=j.get("lastImport"),
                               accessLevel=j.get("accessLevel"))
                    if not j.get("subjectCount"):
                        row["status"] = "warn"
                        row["detail"] = "no subject count reported"
                        worst = max(worst, 3)
                else:
                    row["status"] = "fail"
                    row["detail"] = f"HTTP {d.status_code}"
                    worst = max(worst, 3)
            except Exception as e:
                row["status"] = "fail"
                row["detail"] = type(e).__name__
                worst = max(worst, 3)
        payload["datasets"].append(row)
        payload["checks"].append({
            "name": f"Dataset {row['name']}",
            "status": row["status"],
            "detail": row["detail"] or
                      f"{row['subjectCount']} subjects · imported {row['lastImport']}",
        })

    payload["exit"] = worst
    _write(payload)

    print(f"\nAUTHENTICATED as {payload['user']}  ·  Chiron {version}")
    print(f"{len(payload['datasets'])} dataset(s) visible")
    for d in payload["datasets"]:
        print(f"  {d['unique_id']}: {d['subjectCount']} subjects, "
              f"imported {d['lastImport']}, access {d['accessLevel']}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
