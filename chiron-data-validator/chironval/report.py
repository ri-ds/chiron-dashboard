"""Human-readable console report + structured JSON report."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import DatasetRunResult

LIMITATION_NOTICE = (
    "LIMITATION: 'high_missingness' below is a SYMPTOM, not a diagnosis. Chiron's "
    "ETL layer casts incoming values to their declared type and silently nulls "
    "anything that fails that cast, before storage. This API cannot tell "
    "genuinely-absent-in-source data apart from malformed-then-silently-nulled "
    "data - both look identical as 'missing' here. The record of which is which "
    "(ConceptIssueEtlLog) is internal to Chiron and is not exposed by any current "
    "API endpoint. See README.md 'Limitations' for detail."
)

SEVERITY_MARKER = {"high": "[HIGH]", "medium": "[MED] ", "low": "[LOW] ", "info": "[INFO]"}


def print_console_report(
    results: List[DatasetRunResult],
    missing_threshold: float,
    base_url: str,
    verbose: bool = False,
) -> None:
    print("=" * 78)
    print("Chiron Data Validator - report")
    print(f"Server: {base_url}")
    print(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    print(f"Missing-value threshold: {missing_threshold:.0%}")
    print("-" * 78)
    print(LIMITATION_NOTICE)
    print("=" * 78)

    total_issues = 0
    kind_counter: Counter = Counter()
    datasets_with_issues = 0

    for dr in results:
        print()
        print(f"Dataset: {dr.dataset}")
        if dr.error:
            print(f"  ERROR - could not process this dataset: {dr.error}")
            continue

        print(f"  subjects={dr.total_subjects}  concepts_scanned={dr.concept_count}  "
              f"concepts_skipped={len(dr.skipped)}  issues={len(dr.issues)}")

        if dr.skipped and verbose:
            reasons = Counter(s.reason_kind for s in dr.skipped)
            print(f"  Skipped concepts: {dict(reasons)}")
            for s in dr.skipped:
                print(f"    - {s.concept_id} ({s.concept_name}): {s.reason}")
        elif dr.skipped:
            reasons = Counter(s.reason_kind for s in dr.skipped)
            print(f"  Skipped concepts (use --verbose for details): {dict(reasons)}")

        if not dr.issues:
            print("  No issues found.")
            continue

        datasets_with_issues += 1
        # group by concept, in insertion order, for readability
        by_concept: Dict[str, list] = {}
        for issue in dr.issues:
            by_concept.setdefault(issue.concept_id, []).append(issue)

        for concept_id, issues in by_concept.items():
            issues_sorted = sorted(issues, key=lambda i: i.severity_rank())
            cname = issues_sorted[0].concept_name
            ctype = issues_sorted[0].concept_type
            print(f"  Concept: {concept_id} ({cname}) [{ctype}]")
            for issue in issues_sorted:
                marker = SEVERITY_MARKER.get(issue.severity, issue.severity.upper())
                print(f"    {marker} {issue.kind}: {issue.message}")
                total_issues += 1
                kind_counter[issue.kind] += 1

    print()
    print("-" * 78)
    total_datasets = len(results)
    if total_issues == 0:
        print(f"0 issues across {total_datasets} dataset(s) scanned.")
    else:
        parts = ", ".join(f"{count} {kind}" for kind, count in kind_counter.most_common())
        print(f"{total_issues} issues across {total_datasets} dataset(s) scanned: {parts}")
    print("=" * 78)


def build_json_report(
    results: List[DatasetRunResult],
    missing_threshold: float,
    base_url: str,
) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "server": base_url,
        "missing_threshold": missing_threshold,
        "limitation_notice": LIMITATION_NOTICE,
        "datasets": [dr.to_dict() for dr in results],
        "summary": _summarize(results),
    }


def _summarize(results: List[DatasetRunResult]) -> Dict[str, Any]:
    kind_counter: Counter = Counter()
    total_issues = 0
    for dr in results:
        for issue in dr.issues:
            kind_counter[issue.kind] += 1
            total_issues += 1
    return {
        "total_issues": total_issues,
        "total_datasets": len(results),
        "issues_by_kind": dict(kind_counter),
    }


def write_json_report(path: str, report: Dict[str, Any]) -> None:
    """Write `report` as JSON to `path`.

    Raises OSError (e.g. FileNotFoundError for a missing parent directory,
    PermissionError for an unwritable path) with a message that names the
    path, on top of the original error. Callers (see cli.py) are expected to
    catch OSError here and turn it into a clean, non-traceback CLI error with
    the "could not complete the run" exit code, rather than letting it
    escape as an uncaught exception after an otherwise-successful console
    report - which would be indistinguishable from a normal "ran cleanly,
    found issues" exit.
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
    except OSError as exc:
        raise OSError(f"could not write JSON report to {path!r}: {exc}") from exc
