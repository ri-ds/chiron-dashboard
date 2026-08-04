"""CLI for the Chiron benchmark suite.

    chiron-bench run [--base-url ... --username ... --password ... --iterations N]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .report import build_markdown, write
from .runner import BenchmarkRunner

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MD = ROOT.parent / "chiron-benchmark" / "PERFORMANCE_REPORT.md"
DEFAULT_JSON = ROOT / "results" / "latest.json"


def main(argv=None):
    p = argparse.ArgumentParser(prog="chiron-bench",
                                description="Benchmark Chiron's API + UI flows against performance controls.")
    p.add_argument("--base-url", default=os.environ.get("CHIRON_BASE_URL", "http://127.0.0.1:8000"))
    p.add_argument("--username", default=os.environ.get("CHIRON_USER", "admin"))
    p.add_argument("--password", default=os.environ.get("CHIRON_PASSWORD", "demo1234"))
    p.add_argument("--iterations", type=int, default=30, help="latency samples per endpoint")
    p.add_argument("--burst-total", type=int, default=60, help="requests per throughput burst")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--flow-reps", type=int, default=15)
    p.add_argument("--md", default=str(DEFAULT_MD))
    p.add_argument("--json", default=str(DEFAULT_JSON))
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--fail-on-miss", action="store_true", help="exit 1 if any control fails (CI)")
    args = p.parse_args(argv)

    runner = BenchmarkRunner(args.base_url, args.username, args.password,
                             iterations=args.iterations, burst_total=args.burst_total,
                             concurrency=args.concurrency, flow_reps=args.flow_reps,
                             verbose=args.verbose)
    run = runner.run()
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    write(run, args.md, args.json)
    print(f"\nControls: {run['n_pass']} pass / {run['n_fail']} fail / {run['n_na']} n/a "
          f"(of {run['n_controls']})")
    print(f"Report: {args.md}")
    if args.fail_on_miss and run["n_fail"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
