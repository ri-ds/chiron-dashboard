"""Orchestrates: login -> discover datasets -> discover concepts (paginated)
-> fetch statistics per concept -> run checks -> collect results.

Kept separate from cli.py so it can be exercised without argparse, and
separate from checks.py so the checks stay pure/unit-testable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .checks import run_all_checks
from .client import ChironClient
from .models import ConceptResult, DatasetRunResult, SkippedConcept


def _classify_skip_reason(reason: str) -> str:
    lowered = reason.lower()
    if "prefilter" in lowered:
        return "prefiltered"
    if "permission" in lowered or "403" in lowered:
        return "permission_denied"
    if "404" in lowered:
        return "not_found"
    if "network error" in lowered:
        return "network_error"
    return "other"


def _parse_total_subjects(dataset_detail: Dict[str, Any]) -> Optional[int]:
    raw = dataset_detail.get("subjectCount")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def run_dataset(
    client: ChironClient,
    dataset_string: str,
    missing_threshold: float,
    log=lambda msg: None,
    page_size: int = 100,
    rules=None,
) -> DatasetRunResult:
    """Run the full check suite against one dataset. Never raises for
    per-concept problems (those become SkippedConcept entries); may raise
    requests.exceptions.RequestException / ChironAPIError style errors for
    problems fetching the dataset or its concept list, which the caller
    should treat as fatal to THIS dataset (but not necessarily the whole
    run - see cli.py)."""

    detail = client.get_dataset_detail(dataset_string)
    total_subjects = _parse_total_subjects(detail)
    log(f"{dataset_string}: subjectCount={detail.get('subjectCount')!r} accessLevel={detail.get('accessLevel')!r}")

    concepts = client.get_concepts(dataset_string, page_size=page_size)
    log(f"{dataset_string}: discovered {len(concepts)} concept(s)")

    result = DatasetRunResult(dataset=dataset_string, total_subjects=total_subjects, concept_count=len(concepts))

    for concept_meta in concepts:
        cid = concept_meta.get("permanent_id", "<unknown>")
        cname = concept_meta.get("name", cid)
        ctype = concept_meta.get("concept_type", "")
        concept_detail, err = client.get_concept_statistics(dataset_string, cid)
        if err is not None:
            log(f"{dataset_string}/{cid}: skipped - {err}")
            result.skipped.append(
                SkippedConcept(
                    dataset=dataset_string,
                    concept_id=cid,
                    concept_name=cname,
                    reason_kind=_classify_skip_reason(err),
                    reason=err,
                )
            )
            result.concepts.append(
                ConceptResult(
                    dataset=dataset_string, concept_id=cid, concept_name=cname,
                    concept_type=ctype, status="skipped", skip_reason=err,
                )
            )
            continue

        statistics = (concept_detail or {}).get("statistics") or {}
        issues = run_all_checks(
            concept_meta=concept_meta,
            statistics=statistics,
            total_subjects=total_subjects,
            missing_threshold=missing_threshold,
            dataset=dataset_string,
            rules=rules,
        )
        result.issues.extend(issues)
        result.concepts.append(
            ConceptResult(
                dataset=dataset_string, concept_id=cid, concept_name=cname,
                concept_type=ctype, status=("issues" if issues else "ok"),
                issue_count=len(issues),
                issue_kinds=sorted({i.kind for i in issues}),
            )
        )

    return result


def run_all(
    client: ChironClient,
    dataset_strings: List[str],
    missing_threshold: float,
    log=lambda msg: None,
    page_size: int = 100,
    rules=None,
) -> List[DatasetRunResult]:
    results: List[DatasetRunResult] = []
    for ds in dataset_strings:
        try:
            results.append(run_dataset(client, ds, missing_threshold, log, page_size=page_size, rules=rules))
        except Exception as exc:  # noqa: BLE001 - one bad dataset should not kill the run
            log(f"{ds}: FATAL for this dataset - {exc}")
            results.append(
                DatasetRunResult(dataset=ds, total_subjects=None, concept_count=0, error=str(exc))
            )
    return results
