"""argparse CLI for chironval."""

from __future__ import annotations

import argparse
import sys

import requests

from .client import ChironAuthError, ChironClient
from .html_report import render_report_html, write_html_report
from .report import build_json_report, print_console_report, write_json_report
from .rules import RULE_CATALOG, RuleConfig
from .runner import run_all

DESCRIPTION = """\
Chiron Data Validator - detects data-quality issues in a Chiron research-data
platform using ONLY Chiron's existing REST API (no direct database access).

Checks performed (v1):
  1. missing/null-rate            -> issue kind: high_missingness
  2. numeric outliers (histogram) -> issue kinds: numeric_outlier,
                                      possible_skewed_distribution (fallback)
  3. category/text label consistency -> issue kinds: label_inconsistency,
                                      possible_typo_or_rare_value
  4. category type-plausibility   -> issue kind: possible_metadata_mismatch

IMPORTANT LIMITATION - missing/null-rate check:
Chiron's ETL layer casts every incoming value to its declared concept_type and
SILENTLY NULLS anything that fails that cast, BEFORE the value is stored. This
means "missing" as reported by high_missingness can mean EITHER "genuinely
absent in the source data" OR "arrived malformed and was silently nulled at
ETL time" - the /api/v2 statistics endpoints used by this tool cannot tell
these two cases apart. The only record of which occurred is Chiron's internal
ConceptIssueEtlLog table, which is NOT exposed by any current API endpoint, so
this tool cannot read it. Treat high_missingness as a symptom worth a human
look, not a diagnosis of root cause. See README.md for more detail.
"""

EPILOG = """\
Examples:
  # Validate every dataset on the local dev server using the default admin account
  python chiron_validator.py

  # Same, but explicit about it, and against a different deployment
  python chiron_validator.py validate --base-url https://heartsmart.example.org \\
      --username myuser --password 'hunter2' --dataset patients_stored

  # Only check two datasets, use a stricter missing-value threshold, and also
  # write a machine-readable report
  python chiron_validator.py --dataset dataset1_stored --dataset dataset2_stored \\
      --missing-threshold 0.15 --json-out report.json

  # Generate a filterable HTML report and open it in a browser
  python chiron_validator.py --html-out report.html

Exit codes:
  0  ran cleanly and found no issues
  1  ran cleanly but found one or more data-quality issues
  2  could not run at all (auth failure, unreachable server, bad --dataset, etc.)
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chiron_validator",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="validate",
        choices=["validate"],
        help="Action to run (currently only 'validate'; this is also the default "
        "if omitted, so `chiron_validator.py` with no command is equivalent to "
        "`chiron_validator.py validate`).",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Chiron base URL (default: %(default)s)")
    parser.add_argument("--username", default="admin", help="Login username (default: %(default)s)")
    parser.add_argument("--password", default="demo1234", help="Login password (default: %(default)s)")
    parser.add_argument(
        "--dataset",
        dest="datasets",
        action="append",
        default=None,
        metavar="DATASET_STRING",
        help="Limit validation to this dataset's unique_id (e.g. dataset1_stored). "
        "Repeatable. Default: all datasets visible to this user.",
    )
    parser.add_argument(
        "--missing-threshold",
        type=float,
        default=0.3,
        help="Flag a concept as high_missingness when "
        "count_missing_values / total_subjects exceeds this fraction (default: %(default)s).",
    )
    parser.add_argument("--json-out", default=None, metavar="PATH", help="Also write a structured JSON report to this path.")
    parser.add_argument(
        "--html-out",
        default=None,
        metavar="PATH",
        help="Also write a self-contained, filterable HTML report to this path (open it in any browser).",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-request and per-skip detail.")
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Concepts-list page size to request (DRF max is 1000; default: %(default)s).",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request HTTP timeout in seconds (default: %(default)s).")
    parser.add_argument(
        "--rules-config",
        default=None,
        metavar="PATH",
        help="JSON file of rule settings (enable/disable each check + its thresholds) to apply. "
        "Overrides --missing-threshold when it sets missing_threshold. See --dump-rules for the schema.",
    )
    parser.add_argument(
        "--dump-rules",
        action="store_true",
        help="Print the rule catalog + default settings as JSON and exit (no server contact). "
        "Used by the dashboard to render its rule editor.",
    )
    return parser


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.dump_rules:
        import json
        print(json.dumps({"catalog": RULE_CATALOG, "defaults": RuleConfig().to_dict()}, indent=2))
        return 0

    rules = RuleConfig.from_json_file(args.rules_config) if args.rules_config else None
    # effective missing threshold (config wins when present) — keeps report headers accurate
    effective_missing = rules.missing_threshold if rules else args.missing_threshold

    def log(msg: str) -> None:
        if args.verbose:
            print(f"[verbose] {msg}")

    client = ChironClient(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    try:
        client.login()
    except ChironAuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except requests.exceptions.RequestException as exc:
        print(f"ERROR: could not reach Chiron server at {args.base_url}: {exc}", file=sys.stderr)
        return 2

    try:
        all_datasets = client.get_datasets()
    except requests.exceptions.RequestException as exc:
        print(f"ERROR: could not list datasets: {exc}", file=sys.stderr)
        return 2

    available = {d.get("unique_id"): d for d in all_datasets}
    if args.datasets:
        missing = [d for d in args.datasets if d not in available]
        if missing:
            print(
                f"ERROR: unknown --dataset value(s): {missing}. "
                f"Available: {sorted(available.keys())}",
                file=sys.stderr,
            )
            return 2
        dataset_strings = list(args.datasets)
    else:
        dataset_strings = sorted(available.keys())

    if not dataset_strings:
        print("ERROR: no datasets available to this user.", file=sys.stderr)
        return 2

    log(f"Validating datasets: {dataset_strings}")
    results = run_all(client, dataset_strings, effective_missing, log=log, page_size=args.page_size, rules=rules)

    print_console_report(results, effective_missing, args.base_url, verbose=args.verbose)

    if args.json_out:
        report = build_json_report(results, effective_missing, args.base_url)
        try:
            write_json_report(args.json_out, report)
        except OSError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"\nJSON report written to {args.json_out}")

    if args.html_out:
        html_str = render_report_html(results, effective_missing, args.base_url)
        try:
            write_html_report(args.html_out, html_str)
        except OSError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"HTML report written to {args.html_out}")

    total_issues = sum(len(dr.issues) for dr in results)
    any_dataset_errors = any(dr.error for dr in results)
    if any_dataset_errors:
        return 2
    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
