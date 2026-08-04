"""Command-line interface for the Chiron validator.

    chiron-validator load                      # (re)build the expectations DB from specs
    chiron-validator run  [options]            # run validations against a live Chiron
    chiron-validator report [--run N]          # (re)render a report from the DB
    chiron-validator query "SQL"               # ad-hoc query the validation DB

Everything talks to Chiron over its public HTTP API only.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .client import ChironClient
from .db import ValidatorDB
from . import load_specs
from .report import write_report, build_markdown
from .runner import Runner

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "validator.db"
DEFAULT_REPORT = ROOT.parent / "VALIDATOR_REPORT.md"
DEFAULT_JSON = ROOT / "reports" / "latest_run.json"


def cmd_load(args):
    db = ValidatorDB(args.db)
    stats = load_specs.load(db)
    print(f"Loaded specs: {stats['total']} endpoints "
          f"({stats['testable']} testable, {stats['overrides_applied']} overrides applied)")
    db.close()


def cmd_run(args):
    db = ValidatorDB(args.db)
    # ensure specs are loaded
    if not db.endpoints():
        load_specs.load(db)
    client = ChironClient(args.base_url, args.username, args.password,
                          auth_mode=args.auth, timeout=args.timeout)
    runner = Runner(db, client, dataset=args.dataset,
                    include_writes=args.include_writes,
                    include_destructive=args.include_destructive,
                    include_v1=args.include_v1, verbose=args.verbose)
    stats = runner.run(notes=args.notes or "")
    print(f"\nRun #{stats['run_id']}: {stats['passed']} passed, {stats['failed']} failed, "
          f"{stats.get('unreached', 0)} unreached, {stats['skipped']} skipped "
          f"(of {stats['endpoints']} endpoints)")
    print(f"Discovery: {stats['discovery']}")
    report_path = args.report or DEFAULT_REPORT
    DEFAULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    write_report(db, report_path, DEFAULT_JSON, stats["run_id"])
    print(f"Report written to {report_path}")
    db.close()
    # non-zero exit if failures (useful for CI)
    if args.fail_on_error and stats["failed"] > 0:
        sys.exit(1)


def cmd_report(args):
    db = ValidatorDB(args.db)
    path = args.report or DEFAULT_REPORT
    write_report(db, path, DEFAULT_JSON, args.run)
    print(build_markdown(db, args.run).split("\n## Mismatches")[0])
    print(f"(full report at {path})")
    db.close()


def cmd_query(args):
    db = ValidatorDB(args.db)
    rows = db.conn.execute(args.sql).fetchall()
    if rows:
        cols = rows[0].keys()
        print(" | ".join(cols))
        print("-" * 60)
        for r in rows:
            print(" | ".join(str(r[c]) for c in cols))
    print(f"\n{len(rows)} row(s)")
    db.close()


def build_parser():
    p = argparse.ArgumentParser(prog="chiron-validator",
                                description="Type-validate Chiron's live API against expected schemas.")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite validation DB path")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("load", help="(re)build the expectations DB from specs/")
    s.set_defaults(func=cmd_load)

    s = sub.add_parser("run", help="run validations against a live Chiron")
    s.add_argument("--base-url", default=os.environ.get("CHIRON_BASE_URL", "http://127.0.0.1:8000"))
    s.add_argument("--username", default=os.environ.get("CHIRON_USER", "admin"))
    s.add_argument("--password", default=os.environ.get("CHIRON_PASSWORD", "demo1234"))
    s.add_argument("--dataset", default=os.environ.get("CHIRON_DATASET", "dataset1_stored"))
    s.add_argument("--auth", choices=["basic", "session"], default="session",
                   help="session (default, like the UI; required by some v2 viewsets) or basic")
    s.add_argument("--timeout", type=float, default=30.0)
    s.add_argument("--include-writes", action="store_true", help="also exercise create/update endpoints")
    s.add_argument("--include-destructive", action="store_true", help="also exercise DELETE endpoints")
    s.add_argument("--include-v1", action="store_true", help="also test the v1 API (session dataset)")
    s.add_argument("--report", default=None, help="Markdown report output path")
    s.add_argument("--notes", default="")
    s.add_argument("--fail-on-error", action="store_true", help="exit 1 if any endpoint fails (CI)")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("report", help="(re)render a report from the DB")
    s.add_argument("--run", type=int, default=None, help="run id (default: latest)")
    s.add_argument("--report", default=None)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("query", help="ad-hoc SQL against the validation DB")
    s.add_argument("sql")
    s.set_defaults(func=cmd_query)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
