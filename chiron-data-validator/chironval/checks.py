"""The four v1 data-quality checks.

Every function here is a pure function: (concept metadata, statistics dict,
...) -> list[Issue]. None of them make HTTP calls, which is what makes them
straightforward to unit test with constructed synthetic payloads (see
tests/test_checks.py) - the live demo data is small and clean, so it does not
exercise most of this logic; the unit tests are what actually prove the
checks fire correctly.

`statistics` here is always the ALREADY-UNWRAPPED statistics dict, i.e.
concept_detail_json["statistics"], and is assumed not to be an in-band
{"error": ...} payload - callers (see runner.py) are responsible for
detecting and skipping those before calling into this module.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .models import Issue

# --------------------------------------------------------------------------
# Check 1: missing / null rate
# --------------------------------------------------------------------------


def check_missing_rate(
    concept_meta: Dict[str, Any],
    statistics: Dict[str, Any],
    total_subjects: Optional[int],
    threshold: float,
    dataset: str = "",
) -> List[Issue]:
    """Flag concepts whose missing-value rate exceeds `threshold`.

    percent_missing = count_missing_values / total_subjects, exactly as
    specified: this mixes a value-level numerator with a subject-level
    denominator on purpose (a subject can contribute multiple records to one
    concept, e.g. repeated encounters), so the ratio can exceed 1.0 for
    "many rows per subject" concepts - that is expected and is not itself a
    bug in this check. `count_subjects_with_missing_values` (also returned by
    the API) is included in `details` as the subject-normalized alternative
    for context.

    LIMITATION (documented here, in --help, in the report header, and in
    README.md): Chiron's ETL layer casts incoming values to their declared
    concept_type and silently NULLS anything that fails that cast, before
    storing it. This API cannot distinguish "genuinely absent in source" from
    "arrived malformed and was silently nulled at ETL time" - both look like
    plain missingness here. The per-record cast-failure log
    (ConceptIssueEtlLog) is not exposed by any current Chiron API endpoint.
    This check can only surface elevated missingness as a *symptom*.
    """
    issues: List[Issue] = []
    count_missing = statistics.get("count_missing_values")
    if count_missing is None or not total_subjects:
        return issues

    rate = count_missing / total_subjects
    if rate > threshold:
        count_subjects_missing = statistics.get("count_subjects_with_missing_values")
        issues.append(
            Issue(
                dataset=dataset,
                concept_id=concept_meta.get("permanent_id", ""),
                concept_name=concept_meta.get("name", concept_meta.get("permanent_id", "")),
                concept_type=concept_meta.get("concept_type", ""),
                kind="high_missingness",
                severity="medium",
                message=(
                    f"{count_missing} missing value(s) vs {total_subjects} subject(s) "
                    f"in the dataset ({rate:.0%}, threshold {threshold:.0%}). "
                    "Cannot distinguish genuinely-absent source data from "
                    "malformed-then-silently-nulled-at-ETL data via this API - "
                    "see README Limitations."
                ),
                details={
                    "count_missing_values": count_missing,
                    "total_subjects": total_subjects,
                    "rate": rate,
                    "threshold": threshold,
                    "count_subjects_with_missing_values": count_subjects_missing,
                },
            )
        )
    return issues


# --------------------------------------------------------------------------
# Check 2: numeric outliers
# --------------------------------------------------------------------------

# --- Heuristic, documented here for auditability -------------------------
#
# `histogram_data` (when present) is an ordered list of [bin_label, count]
# pairs, ordered from the lowest-value bin to the highest-value bin -
# confirmed empirically against a live Chiron dev server for `number`,
# `age`, and `date` concepts on 2026-07-15. Bin labels are opaque display
# strings ("[1 - 2)", "11y - 12y", "May 2019") that are not reliably
# parseable back into numbers across concept types, so this heuristic
# deliberately works ONLY on bin POSITION and COUNT, never on label text -
# which also means it applies uniformly to number/age/date histograms alike.
#
# A concept is flagged `numeric_outlier` when, for either the first bin
# (the global minimum) or the last bin (the global maximum):
#   1. that extreme bin's count is > 0 (there really is at least one value
#      out there), AND
#   2. walking inward from that extreme bin, there is at least one bin with
#      count == 0 before reaching the next non-zero bin - i.e. there is a
#      real gap separating the extreme value(s) from the rest of the
#      distribution ("isolated"), AND
#   3. extreme_bin_count <= ISOLATION_RATIO * nearest_nonzero_neighbor_count
#      (default ISOLATION_RATIO = 0.10: the isolated extreme bin holds at
#      most 10% as many values as the nearest populated bin on the bulk
#      side).
#
# This is a cheap, explainable signal for a human reviewer - not a rigorous
# statistical test. It intentionally will NOT catch outliers sitting right
# next to the bulk of the distribution (by design: those are not "isolated"),
# and says nothing about gaps in the interior of the histogram.
#
# KNOWN FALSE-POSITIVE CLASS, called out explicitly here because it is
# foreseeable and systematic rather than a rare edge case: an isolated
# extreme bin can just as easily be a small but genuinely real clinical
# subpopulation (e.g. a handful of extremely-preterm births at the low edge
# of a gestational-age histogram, with a real gap before the term-birth
# bulk) as it can be a data error. This heuristic cannot and does not try to
# tell those two cases apart from bin counts alone - flagging `numeric_outlier`
# means "isolated at the edge", not "wrong". Treat it as a symptom worth a
# human look (same posture as `high_missingness`), never as a verdict that
# the data is invalid - this caveat is echoed in the issue message itself.
#
# Fallback (used only when histogram_data is absent/empty - e.g. very few
# data points, or a concept_type whose statistics never include a
# histogram): the API only exposes count_non_null/min/max/avg here, with no
# true standard deviation, so a real z-score/3-stddev test is not possible
# from this endpoint alone. Instead this flags `possible_skewed_distribution`
# (severity: low, i.e. weaker signal) when the mean sits far closer to one
# bound than the other:
#     abs((max - avg) - (avg - min)) / (max - min) > SKEW_RATIO
# with default SKEW_RATIO = 0.8. This fallback only fires for stats shapes
# with a plain numeric `avg` (i.e. concept_type in {number,
# number_with_categories}) - `age` (avg_year/avg_day) and `date`
# (string min/max, no avg) do not have a directly comparable "avg" and are
# left alone in the fallback path, which is a deliberate and documented
# scope limit rather than an oversight.

ISOLATION_RATIO = 0.10
SKEW_RATIO = 0.8
MIN_BINS_FOR_HISTOGRAM_CHECK = 2


def check_numeric_outliers(
    concept_meta: Dict[str, Any],
    statistics: Dict[str, Any],
    dataset: str = "",
    isolation_ratio: float = ISOLATION_RATIO,
    skew_ratio: float = SKEW_RATIO,
) -> List[Issue]:
    issues: List[Issue] = []
    cid = concept_meta.get("permanent_id", "")
    name = concept_meta.get("name", cid)
    ctype = concept_meta.get("concept_type", "")

    histogram = statistics.get("histogram_data") or []
    counts: List[Any] = []
    labels: List[Any] = []
    for entry in histogram:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            labels.append(entry[0])
            counts.append(entry[1])

    if len(counts) >= MIN_BINS_FOR_HISTOGRAM_CHECK:
        edges = [("minimum", 0, 1), ("maximum", len(counts) - 1, -1)]
        for edge_name, idx, step in edges:
            c = counts[idx]
            if not c:
                continue  # empty edge bin - nothing there, not an outlier
            j = idx + step
            gap = 0
            neighbor_count = None
            while 0 <= j < len(counts):
                if counts[j]:
                    neighbor_count = counts[j]
                    break
                gap += 1
                j += step
            if neighbor_count is None:
                continue  # only one non-zero bin total; nothing to compare against
            if gap >= 1 and c <= isolation_ratio * neighbor_count:
                issues.append(
                    Issue(
                        dataset=dataset,
                        concept_id=cid,
                        concept_name=name,
                        concept_type=ctype,
                        kind="numeric_outlier",
                        severity="medium",
                        message=(
                            f"Isolated bin at the {edge_name} of the distribution: "
                            f"bin '{labels[idx]}' has count={c}, separated from the "
                            f"nearest populated bin (count={neighbor_count}) by "
                            f"{gap} empty bin(s). This is a symptom, not a "
                            "diagnosis: it may be a data error, or it may be a "
                            "small but genuinely real subpopulation (e.g. a rare "
                            "clinical extreme) - this heuristic cannot tell those "
                            "apart from bin counts alone."
                        ),
                        details={
                            "edge": edge_name,
                            "bin_label": labels[idx],
                            "bin_count": c,
                            "gap_bins": gap,
                            "neighbor_count": neighbor_count,
                            "isolation_ratio_threshold": isolation_ratio,
                        },
                    )
                )
        return issues

    # Fallback path: no usable histogram.
    stats_block = statistics.get("stats") or {}
    mn, mx, avg = stats_block.get("min"), stats_block.get("max"), stats_block.get("avg")
    if mn is None or mx is None or avg is None:
        return issues
    try:
        mn, mx, avg = float(mn), float(mx), float(avg)
    except (TypeError, ValueError):
        return issues
    if mx - mn <= 0:
        return issues
    skew = abs((mx - avg) - (avg - mn)) / (mx - mn)
    if skew > skew_ratio:
        issues.append(
            Issue(
                dataset=dataset,
                concept_id=cid,
                concept_name=name,
                concept_type=ctype,
                kind="possible_skewed_distribution",
                severity="low",
                message=(
                    f"No histogram available; mean ({avg:g}) sits far closer to one "
                    f"bound of [{mn:g}, {mx:g}] than the other (skew ratio "
                    f"{skew:.2f} > {skew_ratio}). Weak signal only, not a rigorous "
                    "outlier test - there is no standard deviation available from "
                    "this endpoint."
                ),
                details={"min": mn, "max": mx, "avg": avg, "skew_ratio": skew},
            )
        )
    return issues


# --------------------------------------------------------------------------
# Check 3: category / text label consistency
# --------------------------------------------------------------------------


def _normalize_label(label: Any) -> str:
    """lowercase, strip, collapse internal whitespace."""
    return re.sub(r"\s+", " ", str(label).strip().lower())


def check_label_consistency(
    concept_meta: Dict[str, Any],
    statistics: Dict[str, Any],
    dataset: str = "",
    flag_singletons: bool = True,
) -> List[Issue]:
    """Two shapes are observed for statistics["values"] on a live Chiron
    server:
      - category / boolean / number_with_categories:
            [{"category": "Male", "count": 3, "uniquePatientCount": 2}, ...]
      - text:
            ["A1", "A10", ...]  (a flat list of DISTINCT raw values only -
            no per-value counts are exposed for text concepts)

    Both shapes get the normalization-collision check (flag when >=2
    DISTINCT raw labels normalize to the same string). Only the
    dict-with-counts shape can also get the singleton check (count == 1),
    since flat text values carry no count information at all.
    """
    issues: List[Issue] = []
    values = statistics.get("values")
    if not values:
        return issues

    cid = concept_meta.get("permanent_id", "")
    name = concept_meta.get("name", cid)
    ctype = concept_meta.get("concept_type", "")

    if isinstance(values[0], dict):
        groups: Dict[str, List[dict]] = {}
        for v in values:
            raw = v.get("category")
            if raw is None:
                continue
            groups.setdefault(_normalize_label(raw), []).append(v)

        for norm, group in groups.items():
            distinct_raw = sorted({v.get("category") for v in group})
            if len(distinct_raw) > 1:
                total_count = sum(v.get("count") or 0 for v in group)
                issues.append(
                    Issue(
                        dataset=dataset,
                        concept_id=cid,
                        concept_name=name,
                        concept_type=ctype,
                        kind="label_inconsistency",
                        severity="high",
                        message=(
                            f'{len(distinct_raw)} distinct raw labels normalize to '
                            f'"{norm}": {distinct_raw} (combined count {total_count}). '
                            "Likely the same real-world value entered inconsistently."
                        ),
                        details={
                            "normalized": norm,
                            "raw_labels": distinct_raw,
                            "combined_count": total_count,
                        },
                    )
                )

        if flag_singletons:
            for v in values:
                if v.get("count") == 1:
                    issues.append(
                        Issue(
                            dataset=dataset,
                            concept_id=cid,
                            concept_name=name,
                            concept_type=ctype,
                            kind="possible_typo_or_rare_value",
                            severity="low",
                            message=(
                                f'Category "{v.get("category")}" occurs exactly once '
                                "across the dataset - possible typo or a genuinely rare "
                                "value."
                            ),
                            details={
                                "category": v.get("category"),
                                "count": 1,
                                "unique_patient_count": v.get("uniquePatientCount"),
                            },
                        )
                    )
    else:
        groups: Dict[str, set] = {}
        for raw in values:
            if raw is None:
                continue
            try:
                groups.setdefault(_normalize_label(raw), set()).add(raw)
            except TypeError:
                # Unhashable raw value (e.g. a list/dict) - an unfamiliar
                # concept-type shape this tool has not observed (see README
                # "Other known scope limits", e.g. ontology/undefined). Skip
                # just this value rather than letting the whole dataset scan
                # crash - shape-based dispatch elsewhere in this module
                # (check_numeric_outliers) already degrades the same way.
                continue
        for norm, raws in groups.items():
            if len(raws) > 1:
                distinct_raw = sorted(raws)
                issues.append(
                    Issue(
                        dataset=dataset,
                        concept_id=cid,
                        concept_name=name,
                        concept_type=ctype,
                        kind="label_inconsistency",
                        severity="high",
                        message=(
                            f'{len(distinct_raw)} distinct raw text values normalize '
                            f'to "{norm}": {distinct_raw}. Likely the same '
                            "real-world value entered inconsistently. (Text "
                            "statistics carry no per-value counts, so "
                            "singleton/rare-value detection is not available for "
                            "this concept.)"
                        ),
                        details={"normalized": norm, "raw_labels": distinct_raw},
                    )
                )
    return issues


# --------------------------------------------------------------------------
# Check 4: type plausibility (category concepts only)
# --------------------------------------------------------------------------

# Thresholds, documented here: a "category" concept is flagged as a possible
# metadata mismatch (i.e. it might really be free text, not a true bounded
# categorical field) when either:
#   - it has more than CATEGORY_DISTINCT_ABS_THRESHOLD distinct values, OR
#   - it has more than CATEGORY_DISTINCT_PCT_THRESHOLD * total_subjects
#     distinct values - but ONLY when total_subjects is at least
#     CATEGORY_PCT_MIN_SUBJECTS. Without that floor, a 20%-of-subjects rule
#     fires on almost any category in a small demo dataset (e.g. 2 distinct
#     values out of 6 subjects is already 33%) and is not a meaningful
#     signal at that scale.
#
# Distinct-value count alone cannot tell a genuinely high-cardinality but
# legitimate controlled vocabulary (ICD-10 codes, medication names, site
# codes, ...) apart from free text miscoded as "category": a real controlled
# vocabulary recurs - the same handful of dozens/hundreds of values each get
# used by many records/subjects - while free text is close to unique per
# record. The per-value `count`/`uniquePatientCount` fields already present
# in this same statistics payload (see check_label_consistency's singleton
# check) tell the two apart directly, so the high-cardinality thresholds
# above are only treated as a free-text signal when a real majority of the
# distinct values are themselves singletons (CATEGORY_SINGLETON_FRACTION_
# THRESHOLD, default 0.5) - i.e. the recurrence pattern actually looks like
# free text, not just "many labels".
CATEGORY_DISTINCT_ABS_THRESHOLD = 50
CATEGORY_DISTINCT_PCT_THRESHOLD = 0.20
CATEGORY_PCT_MIN_SUBJECTS = 20
CATEGORY_SINGLETON_FRACTION_THRESHOLD = 0.5


def check_type_plausibility(
    concept_meta: Dict[str, Any],
    statistics: Dict[str, Any],
    total_subjects: Optional[int],
    dataset: str = "",
    abs_threshold: int = CATEGORY_DISTINCT_ABS_THRESHOLD,
    pct_threshold: float = CATEGORY_DISTINCT_PCT_THRESHOLD,
    pct_min_subjects: int = CATEGORY_PCT_MIN_SUBJECTS,
    singleton_fraction_threshold: float = CATEGORY_SINGLETON_FRACTION_THRESHOLD,
) -> List[Issue]:
    issues: List[Issue] = []
    if concept_meta.get("concept_type") != "category":
        return issues

    values = statistics.get("values") or []
    singleton_fraction: Optional[float] = None
    if values and isinstance(values[0], dict):
        distinct = len({v.get("category") for v in values})
        if distinct:
            singleton_count = sum(1 for v in values if (v.get("count") or 0) <= 1)
            singleton_fraction = singleton_count / distinct
    else:
        distinct = len(values)

    # High cardinality that does NOT look like free text (most distinct
    # values recur, i.e. low singleton_fraction) is a real controlled
    # vocabulary, not a metadata mismatch - do not flag it. `values` shapes
    # with no counts at all (singleton_fraction stays None) fall through to
    # the distinct-count-only thresholds below, unchanged from before.
    if singleton_fraction is not None and singleton_fraction < singleton_fraction_threshold:
        return issues

    reasons = []
    if distinct > abs_threshold:
        reasons.append(f"{distinct} distinct values > {abs_threshold} (absolute threshold)")
    if total_subjects and total_subjects >= pct_min_subjects:
        pct = distinct / total_subjects
        if pct > pct_threshold:
            reasons.append(
                f"{distinct}/{total_subjects} subjects = {pct:.0%} > "
                f"{pct_threshold:.0%} (relative threshold)"
            )

    if reasons:
        cid = concept_meta.get("permanent_id", "")
        issues.append(
            Issue(
                dataset=dataset,
                concept_id=cid,
                concept_name=concept_meta.get("name", cid),
                concept_type=concept_meta.get("concept_type", ""),
                kind="possible_metadata_mismatch",
                severity="low",
                message=(
                    "Category concept has an unusually high number of distinct "
                    f"values ({'; '.join(reasons)}); this may actually be free "
                    "text rather than a true bounded categorical field."
                ),
                details={
                    "distinct_values": distinct,
                    "total_subjects": total_subjects,
                    "singleton_fraction": singleton_fraction,
                },
            )
        )
    return issues


# --------------------------------------------------------------------------
# Convenience: run all four checks for one concept
# --------------------------------------------------------------------------


def run_all_checks(
    concept_meta: Dict[str, Any],
    statistics: Dict[str, Any],
    total_subjects: Optional[int],
    missing_threshold: float,
    dataset: str = "",
    rules=None,
) -> List[Issue]:
    """Run the checks for one concept.

    When `rules` is None (the historical default), all four checks run with the
    documented default constants and the supplied `missing_threshold` — behaves
    exactly as before. When a RuleConfig is passed, each check runs only if
    enabled and uses that config's thresholds (missing_threshold is then taken
    from the config)."""
    if rules is None:
        issues: List[Issue] = []
        issues += check_missing_rate(concept_meta, statistics, total_subjects, missing_threshold, dataset)
        issues += check_numeric_outliers(concept_meta, statistics, dataset)
        issues += check_label_consistency(concept_meta, statistics, dataset)
        issues += check_type_plausibility(concept_meta, statistics, total_subjects, dataset)
        return issues

    issues = []
    if rules.missing_rate_enabled:
        issues += check_missing_rate(concept_meta, statistics, total_subjects,
                                     rules.missing_threshold, dataset)
    if rules.numeric_outlier_enabled:
        issues += check_numeric_outliers(concept_meta, statistics, dataset,
                                         isolation_ratio=rules.isolation_ratio,
                                         skew_ratio=rules.skew_ratio)
    if rules.label_consistency_enabled:
        issues += check_label_consistency(concept_meta, statistics, dataset,
                                          flag_singletons=rules.flag_singletons)
    if rules.type_plausibility_enabled:
        issues += check_type_plausibility(concept_meta, statistics, total_subjects, dataset,
                                          abs_threshold=rules.category_abs_threshold,
                                          pct_threshold=rules.category_pct_threshold,
                                          pct_min_subjects=rules.category_pct_min_subjects,
                                          singleton_fraction_threshold=rules.category_singleton_fraction)
    return issues
