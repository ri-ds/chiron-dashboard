"""CLIs for the Chiron scanners. Each RUNS a fresh scan and writes a results JSON.

    chiron-vulnscan   [--base-url ...] [--json PATH] [--fail-on high]
    chiron-ineffscan  [--json PATH] [--fail-on medium]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import ineff, vuln
from .common import SEVERITY_ORDER, write_results

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VULN_JSON = ROOT / "results" / "vuln.json"
DEFAULT_INEFF_JSON = ROOT / "results" / "ineff.json"


def _run(tool, findings, out_path, fail_on):
    payload = write_results(tool, findings, out_path)
    counts = payload["summary"]
    print(f"{tool}: {payload['n_findings']} findings " +
          " ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: SEVERITY_ORDER.get(kv[0], 9))))
    print(f"wrote {out_path}")
    if fail_on:
        thresh = SEVERITY_ORDER.get(fail_on, 99)
        if any(SEVERITY_ORDER.get(f.severity, 9) <= thresh for f in findings):
            sys.exit(1)


def vuln_main(argv=None):
    p = argparse.ArgumentParser(prog="chiron-vulnscan", description="Live security scan of Chiron.")
    p.add_argument("--base-url", default=os.environ.get("CHIRON_BASE_URL", "http://127.0.0.1:8000"))
    p.add_argument("--json", default=str(DEFAULT_VULN_JSON))
    p.add_argument("--fail-on", choices=list(SEVERITY_ORDER), default=None,
                   help="exit 1 if a finding at or above this severity exists (CI)")
    a = p.parse_args(argv)
    _run("vulnscan", vuln.run(a.base_url), a.json, a.fail_on)


def ineff_main(argv=None):
    p = argparse.ArgumentParser(prog="chiron-ineffscan", description="Live inefficiency/quality scan of Chiron.")
    p.add_argument("--base-url", default=os.environ.get("CHIRON_BASE_URL", "http://127.0.0.1:8000"))
    p.add_argument("--json", default=str(DEFAULT_INEFF_JSON))
    p.add_argument("--fail-on", choices=list(SEVERITY_ORDER), default=None)
    a = p.parse_args(argv)
    _run("ineffscan", ineff.run(a.base_url), a.json, a.fail_on)


if __name__ == "__main__":
    vuln_main()
