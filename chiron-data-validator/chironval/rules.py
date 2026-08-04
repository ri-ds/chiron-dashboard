"""Configurable rule settings for the data-quality checks.

Backward-compatible by design: `RuleConfig()` with no arguments reproduces the
historical hardcoded defaults exactly, so any code path that does not pass a
config (including all existing tests and the plain CLI) behaves identically to
before. The dashboard supplies a config file via `--rules-config` to override
thresholds and enable/disable individual checks.

RULE_CATALOG is metadata describing each rule and its editable parameters; it is
the single source of truth the dashboard renders its "Rules" editor from
(exposed via `chiron_validator.py --dump-rules`).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class RuleConfig:
    # Check 1 — missing-value rate
    missing_rate_enabled: bool = True
    missing_threshold: float = 0.30
    # Check 2 — numeric outliers
    numeric_outlier_enabled: bool = True
    isolation_ratio: float = 0.10
    skew_ratio: float = 0.80
    # Check 3 — label consistency / typos
    label_consistency_enabled: bool = True
    flag_singletons: bool = True
    # Check 4 — category type-plausibility (metadata mismatch)
    type_plausibility_enabled: bool = True
    category_abs_threshold: int = 50
    category_pct_threshold: float = 0.20
    category_pct_min_subjects: int = 20
    category_singleton_fraction: float = 0.50

    @classmethod
    def from_dict(cls, d: dict | None) -> "RuleConfig":
        """Build from a (possibly partial / stringly-typed) dict. Unknown keys
        are ignored; missing keys keep their default; bad values fall back to
        the default rather than raising — so a malformed config never crashes a
        run, it just runs with defaults for the offending field."""
        d = d or {}
        defaults = asdict(cls())
        out = {}
        for key, default in defaults.items():
            if key not in d or d[key] is None:
                out[key] = default
                continue
            val = d[key]
            try:
                if isinstance(default, bool):
                    out[key] = (val if isinstance(val, bool)
                                else str(val).strip().lower() in ("1", "true", "yes", "on"))
                elif isinstance(default, int):
                    out[key] = int(val)
                elif isinstance(default, float):
                    out[key] = float(val)
                else:
                    out[key] = val
            except (TypeError, ValueError):
                out[key] = default
        return cls(**out)

    @classmethod
    def from_json_file(cls, path: str) -> "RuleConfig":
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (OSError, ValueError):
            return cls()  # tolerant: missing/unreadable/invalid -> defaults

    def to_dict(self) -> dict:
        return asdict(self)


# Metadata for the dashboard's rule editor. One entry per check; `enabled_key`
# and each param `key` map directly onto RuleConfig fields above.
RULE_CATALOG = [
    {
        "id": "missing_rate",
        "label": "High missing-value rate",
        "kinds": ["high_missingness"],
        "description": "Flag a concept when count_missing_values / total_subjects exceeds the "
                       "threshold. NOTE: cannot distinguish genuinely-absent data from values "
                       "silently nulled by Chiron's ETL type-cast.",
        "enabled_key": "missing_rate_enabled",
        "params": [
            {"key": "missing_threshold", "label": "Missing-rate threshold (fraction of subjects)",
             "type": "float", "min": 0.0, "max": 5.0, "step": 0.05},
        ],
    },
    {
        "id": "numeric_outlier",
        "label": "Numeric outliers",
        "kinds": ["numeric_outlier", "possible_skewed_distribution"],
        "description": "Flag an isolated extreme histogram bin (edge bin small and separated by a "
                       "gap), or, with no histogram, a min/max/avg skew. Symptom, not proof.",
        "enabled_key": "numeric_outlier_enabled",
        "params": [
            {"key": "isolation_ratio", "label": "Isolation ratio (edge bin ≤ this × nearest neighbor)",
             "type": "float", "min": 0.0, "max": 1.0, "step": 0.05},
            {"key": "skew_ratio", "label": "Skew ratio (no-histogram fallback)",
             "type": "float", "min": 0.0, "max": 1.0, "step": 0.05},
        ],
    },
    {
        "id": "label_consistency",
        "label": "Label typos / inconsistency",
        "kinds": ["label_inconsistency", "possible_typo_or_rare_value"],
        "description": "Flag distinct labels that normalize to the same string (e.g. Male/male). "
                       "Optionally also flag singleton categories (count = 1).",
        "enabled_key": "label_consistency_enabled",
        "params": [
            {"key": "flag_singletons", "label": "Also flag singleton (count = 1) categories",
             "type": "bool"},
        ],
    },
    {
        "id": "type_plausibility",
        "label": "Category cardinality / metadata mismatch",
        "kinds": ["possible_metadata_mismatch"],
        "description": "Flag a 'category' concept that looks like free text: too many distinct "
                       "values, most of them singletons.",
        "enabled_key": "type_plausibility_enabled",
        "params": [
            {"key": "category_abs_threshold", "label": "Max distinct values (absolute)",
             "type": "int", "min": 1, "max": 5000, "step": 1},
            {"key": "category_pct_threshold", "label": "Max distinct as fraction of subjects",
             "type": "float", "min": 0.0, "max": 1.0, "step": 0.05},
            {"key": "category_pct_min_subjects", "label": "Min subjects before the fraction rule applies",
             "type": "int", "min": 1, "max": 100000, "step": 1},
            {"key": "category_singleton_fraction", "label": "Only flag if this fraction of values are singletons",
             "type": "float", "min": 0.0, "max": 1.0, "step": 0.05},
        ],
    },
]
