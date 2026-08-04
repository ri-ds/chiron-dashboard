"""Shared data types used across chironval."""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


# Severity is a relative signal meant to help a human reviewer triage output,
# not a rigorous/regulatory classification. Ordering below is used for sorting.
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class Issue:
    """A single data-quality finding for one concept in one dataset."""

    dataset: str
    concept_id: str
    concept_name: str
    concept_type: str
    kind: str  # e.g. "high_missingness", "numeric_outlier", "label_inconsistency", ...
    severity: str  # "high" | "medium" | "low" | "info"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def severity_rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 99)


@dataclass
class SkippedConcept:
    """A concept that could not be checked, and why (not a data-quality issue)."""

    dataset: str
    concept_id: str
    concept_name: str
    reason_kind: str  # "prefiltered" | "permission_denied" | "http_error" | "unrecognized_shape"
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConceptResult:
    """Per-concept outcome for a run — recorded for EVERY concept scanned, not
    just the ones with issues, so a report can show the whole picture."""

    dataset: str
    concept_id: str
    concept_name: str
    concept_type: str
    status: str  # "ok" (checked, clean) | "issues" (checked, flagged) | "skipped"
    issue_count: int = 0
    issue_kinds: list = field(default_factory=list)
    skip_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetRunResult:
    """Everything discovered/produced for a single dataset during a run."""

    dataset: str
    total_subjects: Optional[int]
    concept_count: int
    issues: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    error: Optional[str] = None  # set if the dataset itself could not be processed
    concepts: list = field(default_factory=list)  # ConceptResult per concept (all of them)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "total_subjects": self.total_subjects,
            "concept_count": self.concept_count,
            "issues": [i.to_dict() for i in self.issues],
            "skipped": [s.to_dict() for s in self.skipped],
            "error": self.error,
            "concepts": [c.to_dict() for c in self.concepts],
        }
