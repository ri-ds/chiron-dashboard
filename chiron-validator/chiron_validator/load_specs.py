"""Load endpoint specs into the validator DB.

Source of truth (in precedence order):
  1. ``specs/inventory.json``  — the field-level inventory built in Task 1.
  2. ``specs/overrides.json``  — hand-written, high-precision contracts for the
     key v2 endpoints the runner exercises, based on the actual serializer field
     lists (DatasetSerializer, AuthSerializer, ConceptSerializer, …). Overrides
     replace the auto-derived contract for a matching endpoint key.

Each endpoint gets a ``testable`` flag + ``test_note`` describing how/whether the
runner can safely exercise it (GETs are safe; DELETEs are skipped; creates need
synthetic bodies; server-rendered views are out of the JSON-API scope).
"""

from __future__ import annotations

import json
from pathlib import Path

from .normalize import build_request_contract, build_response_contract

SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"


def _methods(method: str) -> list[str]:
    return [m.strip().upper() for m in method.replace("/", ",").split(",") if m.strip()]


def testability(version: str, method: str, action: str, resource: str) -> tuple[bool, str]:
    if version == "non-api":
        return False, "server-rendered HTML / redirect — outside JSON-API validator scope"
    ms = _methods(method)
    if "DELETE" in ms or action == "destroy":
        return False, "destructive (destroy) — skipped unless --include-destructive"
    if action == "create":
        return True, "POST create — runner sends a synthetic body"
    if action in ("update", "partial_update"):
        if resource == "concepts":
            return True, "PUT is non-mutating (long-param passthrough) — safe"
        return True, "mutating write — synthetic body; runs only with --include-writes"
    if action in ("load_as_active", "flag", "share", "share_form"):
        return True, "state-changing action — runs only with --include-writes"
    return True, ""  # plain GET list/retrieve/custom-read


def dedupe_endpoints(inventory: dict) -> list[dict]:
    seen, out = set(), []
    for agent in inventory["agents"]:
        for e in agent["endpoints"]:
            key = (e.get("version"), e.get("method"), e.get("path"), e.get("action"))
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
    return out


def build_spec(e: dict) -> dict:
    version = e.get("version", "?")
    method = e.get("method", "GET")
    path = e.get("path", "")
    action = e.get("action", "")
    resource = e.get("resource", "")
    testable, note = testability(version, method, action, resource)
    return {
        "key": f"{version}|{method}|{path}|{action}",
        "version": version, "resource": resource, "method": method,
        "path": path, "action": action,
        "purpose": e.get("purpose", ""), "permissions": e.get("permissions", ""),
        "response_contract": build_response_contract(e),
        "request_contract": build_request_contract(e),
        "testable": testable, "test_note": note,
        "source_refs": e.get("source_refs", []),
    }


def load(db, inventory_path: Path | None = None, overrides_path: Path | None = None) -> dict:
    inventory_path = inventory_path or (SPECS_DIR / "inventory.json")
    overrides_path = overrides_path or (SPECS_DIR / "overrides.json")

    inventory = json.loads(Path(inventory_path).read_text())
    endpoints = dedupe_endpoints(inventory)
    specs = {}
    for e in endpoints:
        s = build_spec(e)
        specs[s["key"]] = s

    n_override = 0
    if Path(overrides_path).exists():
        overrides = json.loads(Path(overrides_path).read_text())
        for ov in overrides.get("endpoints", []):
            key = ov["key"]
            base = specs.get(key)
            if base is None:
                # Override pins an endpoint whose key didn't match any auto-derived
                # one. Parse version|method|path|action from the key itself so we
                # never create a malformed ("empty path") phantom endpoint.
                parts = key.split("|")
                kver, kmethod, kpath, kaction = (parts + ["", "", "", ""])[:4]
                resource = ov.get("resource") or (kpath.split("/")[3] if kpath.count("/") >= 3 else "")
                base = {"key": key, "version": ov.get("version", kver),
                        "resource": resource, "method": ov.get("method", kmethod),
                        "path": ov.get("path", kpath), "action": ov.get("action", kaction),
                        "purpose": ov.get("purpose", ""), "permissions": ov.get("permissions", ""),
                        "request_contract": {"body": [], "query": []},
                        "testable": True, "test_note": "", "source_refs": []}
                specs[key] = base
            if "response_contract" in ov:
                base["response_contract"] = ov["response_contract"]
            if "request_contract" in ov:
                base["request_contract"] = ov["request_contract"]
            if "purpose" in ov:
                base["purpose"] = ov["purpose"]
            base["overridden"] = True
            n_override += 1

    db.clear_specs()
    for s in specs.values():
        db.upsert_endpoint(s)

    n_testable = sum(1 for s in specs.values() if s["testable"])
    return {"total": len(specs), "testable": n_testable, "overrides_applied": n_override}
