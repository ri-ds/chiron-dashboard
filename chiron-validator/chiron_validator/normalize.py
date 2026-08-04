"""Normalise the free-form type strings captured in the endpoint inventory into
the checker's compact type language, and turn inventory endpoint records into
validator specs (request contract + response contract).

The inventory (``specs/inventory.json``) was produced by reading Chiron's DRF
serializers and Django models, so its field lists are authoritative; only the
*spelling* of the type strings is free-form (e.g. "int", "str|null",
"array<ConceptSerializer>", "string(iso8601)"). This module maps those onto
``string | integer | number | boolean | object | array | array<T> |
string:iso8601 | ...`` so the checker can act on them.
"""

from __future__ import annotations

import html
import re

# Names that appear in the inventory but are opaque to a black-box checker
# (serializer classes, dynamic processor payloads). We assert presence, not shape.
_OPAQUE_HINTS = ("serializer", "dynamic", "processor", "option", "payload",
                 "conceptrelated", "category", "eventoption", "extended",
                 "criteria", "dto")


def normalize_type(raw: str) -> tuple[str, bool]:
    """Return (type, nullable_from_type). Nullability may also come from a
    separate flag on the field; callers OR the two together."""
    if raw is None:
        return "any", False
    s = html.unescape(str(raw)).strip()
    nullable = False

    # "X|null", "X | null", "X or null", "(X|null)"
    s = s.strip("() ")
    parts = re.split(r"\s*\|\s*|\s+or\s+", s)
    if len(parts) > 1 and any(p.strip().lower() in ("null", "none") for p in parts):
        nullable = True
        parts = [p for p in parts if p.strip().lower() not in ("null", "none")]
        s = parts[0].strip() if parts else "any"

    low = s.lower()

    # container: array<...> / list[...] / list of ...
    m = (re.match(r"^(?:array|list)\s*[<\[]\s*(.+?)\s*[>\]]$", s, re.I)
         or re.match(r"^(?:array|list)\s+of\s+(.+)$", s, re.I))
    if m:
        inner_raw = m.group(1)
        inner, _ = normalize_type(inner_raw)
        # opaque element -> untyped array element (presence only via array)
        if inner == "any" or _is_opaque(inner_raw):
            return "array", nullable
        return f"array<{inner}>", nullable

    if low in ("array", "list", "tuple"):
        return "array", nullable
    if low in ("int", "integer", "integerfield", "id", "int(id)", "integer(id)", "pk"):
        return "integer", nullable
    if low in ("float", "number", "decimal", "double", "floatfield", "order(float)"):
        return "number", nullable
    if low in ("bool", "boolean", "booleanfield"):
        return "boolean", nullable
    if low in ("object", "dict", "json", "jsonfield", "mapping", "map"):
        return "object", nullable
    if low in ("null", "none"):
        return "null", True

    # string subtypes
    if "iso8601" in low or "datetime" in low or "date-time" in low or low in ("date", "datetimefield"):
        return "string:iso8601", nullable
    if "url" in low or "hyperlink" in low or "uri" in low:
        return "string:url", nullable
    if "email" in low:
        return "string:email", nullable
    if low in ("string", "str", "charfield", "textfield", "slugfield", "text", "string(str)"):
        return "string", nullable
    if low.startswith("string"):
        return "string", nullable

    # enum:  "enum(a,b,c)" or "one of a|b|c"
    m = re.match(r"^enum\s*[:(]\s*(.+?)\s*\)?$", s, re.I)
    if m:
        vals = re.split(r"\s*[,|]\s*", m.group(1))
        return "enum:" + "|".join(v.strip().strip("'\"") for v in vals if v.strip()), nullable

    # opaque -> presence only
    if _is_opaque(s):
        # if it clearly names a nested object, assert object; else 'any'
        return ("object" if "serializer" in low else "any"), nullable

    return "any", nullable


def _is_opaque(raw: str) -> bool:
    low = raw.lower()
    return any(h in low for h in _OPAQUE_HINTS) or bool(re.search(r"[A-Z][a-z]+[A-Z]", raw))


def _is_placeholder(name: str) -> bool:
    """Inventory used '<XxxSerializer fields>' as a spread marker for
    'all fields of that serializer' — not a literal key."""
    n = (name or "").strip()
    return n.startswith("<") or n.startswith("&lt;")


def response_kind(response_type: str) -> str:
    t = (response_type or "object").lower()
    if "paginat" in t:
        return "paginated"
    if t == "array" or "list" in t:
        return "array"
    if t in ("csv", "html", "file", "text", "binary", "stream"):
        return "raw"
    # object, form-json, other -> object
    return "object"


def build_response_contract(endpoint: dict) -> dict:
    """Turn an inventory endpoint into a checker response contract."""
    kind = response_kind(endpoint.get("response_type"))
    if kind == "raw":
        return {"kind": "raw", "fields": []}

    fields = []
    for rf in endpoint.get("response_fields", []):
        name = html.unescape(rf.get("name", "")).strip()
        if _is_placeholder(name):
            continue
        etype, tnull = normalize_type(rf.get("type"))
        nullable = bool(rf.get("nullable")) or tnull
        # AUTO-DERIVED TIER: the inventory field lists come from prose summaries of
        # serializers, so they are trustworthy for *types of fields that appear* but
        # not necessarily complete or exactly-named. We therefore keep every auto
        # field OPTIONAL and disable extra-field strictness — so an auto endpoint can
        # only FAIL on a genuine type mismatch of a present field or a wrong container
        # shape (array vs object vs paginated). Missing/extra become non-failing signal.
        # High-precision, serializer-verified contracts live in specs/overrides.json,
        # which supplies its own contract and bypasses this leniency.
        fields.append({"name": name, "type": etype, "nullable": True, "required": False})

    return {"kind": kind, "fields": fields, "strict_extra": False}


def build_request_contract(endpoint: dict) -> dict:
    req = []
    for rf in endpoint.get("request_fields", []):
        name = html.unescape(rf.get("name", "")).strip()
        if _is_placeholder(name):
            continue
        etype, tnull = normalize_type(rf.get("type"))
        req.append({"name": name, "type": etype,
                    "required": bool(rf.get("required")), "nullable": tnull,
                    "notes": rf.get("notes", "")})
    q = []
    for qp in endpoint.get("query_params", []):
        name = html.unescape(qp.get("name", "")).strip()
        if _is_placeholder(name):
            continue
        etype, _ = normalize_type(qp.get("type"))
        q.append({"name": name, "type": etype,
                  "required": bool(qp.get("required")), "notes": qp.get("notes", "")})
    return {"body": req, "query": q}
