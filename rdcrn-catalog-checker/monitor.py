#!/usr/bin/env python3
"""Unattended monitor: refresh the SSO session, then run the read-only checks.

This is the piece you point a scheduler at. It glues the two halves together:

    sso_session.refresh()   silent re-SSO -> a live Cookie header, in memory
    checker.py              read-only GETs against the catalog API

The credential is handed to checker.py through its environment (CATALOG_COOKIE) and
never touches disk or the command line, so it stays out of cookie files, shell
history, and `ps` output.

Exit codes, chosen so a scheduler can alert on them directly:
    0  checks ran and passed
    2  needs a human — the saved session expired and silent re-SSO could not
       recover it, so someone must run `sso_session.py login` once
    3  authenticated but the API answered unexpectedly (the interesting failure:
       this is the app actually being broken, rather than an auth problem)
    1  usage or internal error

Usage:
    ./.venv/bin/python monitor.py
    ./.venv/bin/python monitor.py --log monitor.log
    ./.venv/bin/python monitor.py --no-refresh      # use CATALOG_* already in env
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "checker.py")

EXIT_MEANING = {
    0: "OK — authenticated and checks passed",
    1: "ERROR — usage or internal failure",
    2: "AUTH — interactive login required",
    3: "DEGRADED — authenticated but unexpected API response",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _emit(line: str, log_path: str | None) -> None:
    print(line, flush=True)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            print(f"! could not write {log_path}: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", metavar="PATH",
                    help="append a timestamped one-line result here as well as stdout")
    ap.add_argument("--no-refresh", action="store_true",
                    help="skip the SSO refresh; rely on CATALOG_* already in the environment")
    ap.add_argument("--dataset", metavar="SLUG",
                    help="also spot-check one dataset (sets CATALOG_DATASET)")
    args = ap.parse_args()

    if not os.path.isfile(CHECKER):
        print(f"! checker.py not found next to this script ({CHECKER})", file=sys.stderr)
        return 1

    env = os.environ.copy()
    if args.dataset:
        env["CATALOG_DATASET"] = args.dataset

    started = _stamp()

    if not args.no_refresh:
        # Imported lazily so --no-refresh works without Playwright installed.
        try:
            import sso_session
        except Exception as e:  # pragma: no cover - import guard
            print(f"! cannot import sso_session: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

        code, cookie = sso_session.refresh(verbose=True)
        if code != 0:
            _emit(f"{started}  exit={code}  {EXIT_MEANING.get(code, 'unknown')}"
                  f"  (session refresh failed)", args.log)
            return code
        # In-memory handoff: never written to disk, never in argv.
        env["CATALOG_COOKIE"] = cookie
        # Make sure a stale cookie file cannot silently win over the fresh session.
        env.pop("CATALOG_COOKIES_FILE", None)
        print()

    proc = subprocess.run([sys.executable, CHECKER], env=env)
    code = proc.returncode

    _emit(f"{started}  exit={code}  {EXIT_MEANING.get(code, f'unknown ({code})')}", args.log)
    return code


if __name__ == "__main__":
    sys.exit(main())
