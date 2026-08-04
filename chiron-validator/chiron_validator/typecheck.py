"""Field-by-field type checker — the core validation engine.

Given an *expected* type spec and an *actual* JSON value decoded from a live
Chiron response, produce a list of typed issues. The design goal is to catch
**real** contract violations (wrong type, missing field, unexpected null, bad
enum, wrong container) while not drowning the report in false positives on
Chiron's intentionally-dynamic processor payloads (statistics, form options,
callback data), whose inner shape depends on a concept's processor type.

Type language (all types are strings so specs stay JSON-serialisable and
queryable in SQLite):

    scalars     string | integer | number | boolean | null | any
    string subtypes   string:iso8601 | string:url | string:email
    containers  array | array<T> | object
    enum        enum:a|b|c   (values compared as strings)

A field spec is ``{"name", "type", "nullable", "required"}``.
"any" means "present, shape not asserted" — used for dynamic payloads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Severity ordering used for sorting/report rollups.
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"           # date
    r"([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"  # optional time
    r"(Z|[+-]\d{2}:?\d{2})?)?$"     # optional tz
)
URL_RE = re.compile(r"^https?://", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Issue:
    code: str            # missing_field | type_mismatch | unexpected_null | ...
    severity: str        # error | warning | info
    path: str            # JSON path, e.g. results[0].collection
    message: str
    expected: str = ""
    actual: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
        }


def _wire_type(v: Any) -> str:
    """Human name for the actual JSON value's type."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _scalar_ok(expected: str, v: Any) -> bool:
    """Check a scalar/leaf expected type against an actual value.

    Returns True when acceptable. Numeric widening: an integer is an acceptable
    ``number``; JSON has one number type so we do not fail integers where a
    float is expected. Booleans are NOT treated as integers.
    """
    base = expected.split(":", 1)[0]
    if base == "any":
        return True
    if base == "string":
        if not isinstance(v, str):
            return False
        sub = expected.split(":", 1)[1] if ":" in expected else None
        if sub == "iso8601":
            return bool(ISO8601_RE.match(v)) or _try_parse_dt(v)
        if sub == "url":
            return bool(URL_RE.match(v)) or v == ""
        if sub == "email":
            return bool(EMAIL_RE.match(v)) or v == ""
        return True
    if base == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if base == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if base == "boolean":
        return isinstance(v, bool)
    if base == "null":
        return v is None
    if base == "object":
        return isinstance(v, dict)
    if base == "array":
        return isinstance(v, list)
    if base == "enum":
        allowed = expected.split(":", 1)[1].split("|") if ":" in expected else []
        return str(v) in allowed
    # Unknown/opaque type name (e.g. a serializer name) -> presence only.
    return True


def _try_parse_dt(v: str) -> bool:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            datetime.strptime(v, fmt)
            return True
        except (ValueError, TypeError):
            continue
    return False


def check_value(expected_type: str, nullable: bool, value: Any, path: str) -> list[Issue]:
    """Check a single value against an expected type + nullability."""
    issues: list[Issue] = []
    expected_type = (expected_type or "any").strip()

    # array<T> — container with a typed element.
    m = re.match(r"^array<(.+)>$", expected_type)
    if m:
        inner = m.group(1).strip()
        if value is None:
            if not nullable:
                issues.append(Issue("unexpected_null", "error", path,
                                    f"expected array<{inner}> but got null",
                                    f"array<{inner}>", "null"))
            return issues
        if not isinstance(value, list):
            issues.append(Issue("type_mismatch", "error", path,
                                f"expected array<{inner}> but got {_wire_type(value)}",
                                f"array<{inner}>", _wire_type(value)))
            return issues
        # Element type: opaque names (serializer classes) → presence only.
        if inner.lower() in _KNOWN_LEAVES:
            for i, item in enumerate(value):
                issues += check_value(inner, False, item, f"{path}[{i}]")
        return issues

    # null handling for leaves/objects.
    if value is None:
        if nullable or expected_type in ("null", "any"):
            return issues
        issues.append(Issue("unexpected_null", "error", path,
                            f"expected {expected_type} but got null (non-nullable)",
                            expected_type, "null"))
        return issues

    if not _scalar_ok(expected_type, value):
        code = "bad_enum" if expected_type.startswith("enum:") else "type_mismatch"
        issues.append(Issue(code, "error", path,
                            f"expected {expected_type} but got {_wire_type(value)} ({value!r:.60})"
                            if code == "bad_enum" else
                            f"expected {expected_type} but got {_wire_type(value)}",
                            expected_type, _wire_type(value)))
    return issues


_KNOWN_LEAVES = {"string", "integer", "number", "boolean", "null", "any", "object", "array"}


def check_object(fields: list[dict], obj: Any, path: str, strict_extra: bool = True) -> list[Issue]:
    """Check an object against a list of field specs.

    Emits: missing_field (required field absent), type issues per field, and
    extra_field (info) for keys present but not in the spec.
    """
    issues: list[Issue] = []
    if not isinstance(obj, dict):
        issues.append(Issue("type_mismatch", "error", path,
                            f"expected object but got {_wire_type(obj)}", "object", _wire_type(obj)))
        return issues

    spec_names = set()
    for f in fields:
        name = f["name"]
        spec_names.add(name)
        required = f.get("required", True)
        nullable = f.get("nullable", False)
        etype = f.get("type", "any")
        fpath = f"{path}.{name}" if path else name
        if name not in obj:
            if required:
                issues.append(Issue("missing_field", "error", fpath,
                                    f"required field '{name}' ({etype}) missing from response",
                                    etype, "<absent>"))
            continue
        val = obj[name]
        issues += check_value(etype, nullable, val, fpath)
        # Nested structure: a field may carry an object_fields / item_fields spec
        # to validate one level deeper (used by hand-written overrides).
        if val is not None:
            if f.get("object_fields") is not None and isinstance(val, dict):
                issues += check_object(f["object_fields"], val, fpath,
                                       f.get("strict_extra", strict_extra))
            if f.get("item_fields") is not None and isinstance(val, list):
                for i, item in enumerate(val[:25]):
                    issues += check_object(f["item_fields"], item, f"{fpath}[{i}]",
                                           f.get("strict_extra", strict_extra))

    if strict_extra:
        for k in obj:
            if k not in spec_names:
                issues.append(Issue("extra_field", "info", f"{path}.{k}" if path else k,
                                    f"field '{k}' present in response but not in spec",
                                    "<not in spec>", _wire_type(obj[k])))
    return issues


def check_response(contract: dict, body: Any) -> list[Issue]:
    """Check a full response body against a response contract.

    contract = {
      "kind": "object" | "array" | "paginated" | "raw",
      "fields": [ field specs ],          # for object / array-item / paginated-item
      "strict_extra": bool                 # optional, default True
    }
    """
    kind = contract.get("kind", "object")
    fields = contract.get("fields", [])
    strict = contract.get("strict_extra", True)

    if kind == "raw" or kind == "any":
        return []

    if kind == "object":
        return check_object(fields, body, "", strict)

    if kind == "array":
        if not isinstance(body, list):
            return [Issue("wrong_container", "error", "",
                          f"expected a bare array but got {_wire_type(body)}", "array", _wire_type(body))]
        issues = []
        # Only check the first N elements to keep reports readable; homogeneity assumed.
        for i, item in enumerate(body[:25]):
            issues += check_object(fields, item, f"[{i}]", strict)
        return issues

    if kind == "paginated":
        if not isinstance(body, dict):
            return [Issue("wrong_container", "error", "",
                          f"expected paginated wrapper but got {_wire_type(body)}",
                          "object{count,next,previous,results}", _wire_type(body))]
        issues = []
        issues += check_object([
            {"name": "count", "type": "integer", "required": True, "nullable": False},
            {"name": "next", "type": "string:url", "required": True, "nullable": True},
            {"name": "previous", "type": "string:url", "required": True, "nullable": True},
            {"name": "results", "type": "array", "required": True, "nullable": False},
        ], body, "", strict_extra=False)
        results = body.get("results")
        if isinstance(results, list):
            for i, item in enumerate(results[:25]):
                issues += check_object(fields, item, f"results[{i}]", strict)
        return issues

    return [Issue("spec_error", "warning", "", f"unknown contract kind '{kind}'", kind, "")]


def summarize(issues: list[Issue]) -> dict:
    counts = {"error": 0, "warning": 0, "info": 0}
    by_code: dict[str, int] = {}
    for iss in issues:
        counts[iss.severity] = counts.get(iss.severity, 0) + 1
        by_code[iss.code] = by_code.get(iss.code, 0) + 1
    return {"counts": counts, "by_code": by_code,
            "passed": counts["error"] == 0}
