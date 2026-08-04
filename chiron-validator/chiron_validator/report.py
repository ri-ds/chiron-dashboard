"""Render a validation run (from the DB) to Markdown + JSON."""

from __future__ import annotations

import json
from pathlib import Path


def _md_escape(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ") if s is not None else ""


def build_markdown(db, run_id: int | None = None) -> str:
    run = db.conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone() if run_id \
        else db.latest_run()
    if run is None:
        return "# Validator Report\n\nNo runs recorded yet.\n"
    run_id = run["id"]
    results = db.results_for_run(run_id)

    # A "type verdict" only exists when the endpoint returned 2xx (passed is 0/1).
    # passed IS NULL => reached a non-2xx stateful/edge response (unreached).
    skipped = [r for r in results if r["skipped"]]
    unreached = [r for r in results if not r["skipped"] and r["passed"] is None]
    tested = [r for r in results if not r["skipped"] and r["passed"] is not None]
    passed = [r for r in tested if r["passed"]]
    failed = [r for r in tested if not r["passed"]]

    L = []
    A = L.append
    A("# Chiron Validator — Report\n")
    A(f"_Database of type validations run against the **live Chiron API** "
      f"(public endpoints only)._\n")

    # ---- headline findings (real 500s / server errors on this run) ----
    server_bugs = []
    for r in tested + unreached:
        if r["http_status"] and r["http_status"] >= 500:
            for i in db.issues_for_result(r["id"]):
                if i["code"] == "server_error":
                    server_bugs.append((r, i))
                    break
    if server_bugs:
        A("## ⚠️ Headline findings — endpoints that return HTTP 500\n")
        A("The validator drives only the *public* API with synthetic reads, yet these "
          "endpoints crash (server error) instead of returning data or a clean 4xx. "
          "Each is a concrete correctness bug:\n")
        for r, i in server_bugs:
            A(f"- **`{r['method']} {_md_escape(r['path'])}`** ({r['version']}) → HTTP {r['http_status']}: "
              f"{_md_escape(i['message'])}")
        A("")

    A("## Run summary\n")
    A("| | |")
    A("|---|---|")
    A(f"| Run id | {run_id} |")
    A(f"| Started | {run['started_at']} |")
    A(f"| Finished | {run['finished_at']} |")
    A(f"| Base URL | `{run['base_url']}` |")
    A(f"| Dataset | `{run['dataset']}` |")
    A(f"| Chiron version | `{run['chiron_version']}` |")
    A(f"| Endpoints in scope | {run['n_endpoints']} |")
    A(f"| **Type-checked (got 2xx)** | **{len(tested)}** |")
    A(f"| ✅ Passed | {len(passed)} |")
    A(f"| ❌ Failed (type/contract mismatch) | {len(failed)} |")
    A(f"| ◻️ Unreached (auth/404/stateful 4xx) | {len(unreached)} |")
    A(f"| ⏭️ Skipped (writes/destructive/non-JSON) | {len(skipped)} |")
    rate = (100.0 * len(passed) / len(tested)) if tested else 0.0
    A(f"| **Pass rate (of type-checked)** | **{rate:.1f}%** |")
    A("")
    A("## How this was checked (methodology)\n")
    A("- **Black-box, public API only.** The validator speaks HTTP the way any "
      "external consumer would — no import of Chiron, no DB access, no internals.\n"
      "- **Expected types come from Chiron's own contract.** Field types are derived "
      "from Chiron's DRF serializers + Django models (captured in `specs/inventory.json`). "
      "Key v2/v1 endpoints have hand-verified, serializer-accurate contracts in "
      "`specs/overrides.json` (strict); the rest use auto-derived contracts that "
      "type-check *present* fields and container shape (lenient — so a failure is real).\n"
      "- **Synthetic data only.** Warehouse subjects are Synthea-style synthetic records; "
      "request payloads are synthetic query definitions built from live concept metadata. "
      "No real PHI is used or generated.\n"
      "- **Read-only by default.** GET/HEAD + the non-mutating concept `PUT` run by "
      "default; create/update/delete require `--include-writes` / `--include-destructive`.\n"
      "- **Verdict semantics.** A *type verdict* (pass/fail) is only formed on a 2xx "
      "response. `401/403/5xx` = hard fail (should be reachable & healthy); "
      "`404`/stateful-`4xx` = *unreached* (needs prior state / not applicable here), "
      "reported separately so the pass rate reflects genuine type correctness.\n")

    # ---- failures with concrete examples ----
    A("## Mismatches found\n")
    if not failed:
        A("No type/contract mismatches on tested endpoints. 🎉\n")
    else:
        A(f"{len(failed)} tested endpoint(s) failed. Each lists the concrete issues "
          "(field path, expected vs. actual).\n")
        for r in failed:
            A(f"### ❌ `{r['method']} {r['path']}` — {r['action']} ({r['version']})")
            A(f"- Request: `{_md_escape(r['request_url'])}`")
            A(f"- HTTP {r['http_status']} · {r['duration_ms']:.0f} ms · "
              f"{r['n_error']} error / {r['n_warning']} warning / {r['n_info']} info")
            issues = db.issues_for_result(r["id"])
            errs = [i for i in issues if i["severity"] in ("error", "warning")][:15]
            A("")
            A("| Severity | Code | Path | Expected | Actual | Detail |")
            A("|----------|------|------|----------|--------|--------|")
            for i in errs:
                A(f"| {i['severity']} | {i['code']} | `{_md_escape(i['path']) or '(root)'}` "
                  f"| `{_md_escape(i['expected'])}` | `{_md_escape(i['actual'])}` "
                  f"| {_md_escape(i['message'])} |")
            A("")

    # ---- unreached (non-2xx: auth / not-found / stateful precondition) ----
    A("## Unreached endpoints (non-2xx — no type verdict)\n")
    if not unreached:
        A("None — every exercised endpoint returned a 2xx response.\n")
    else:
        A("These returned a non-2xx status, so no type verdict was formed. Auth/5xx "
          "are genuine problems; 404 / stateful-4xx usually mean the call needs prior "
          "state (an active cohort/snapshot) or a resource that does not exist here.\n")
        A("| Ver | Method | Path | Action | HTTP | Detail |")
        A("|-----|--------|------|--------|------|--------|")
        for r in sorted(unreached, key=lambda r: (r["http_status"] or 0, r["version"], r["path"])):
            A(f"| {r['version']} | {r['method']} | `{_md_escape(r['path'])}` | {r['action']} "
              f"| {r['http_status']} | {_md_escape(r['skip_reason'])} |")
        A("")

    # ---- full per-endpoint table ----
    A("## Per-endpoint results (type-checked)\n")
    A("| Result | Ver | Method | Path | Action | HTTP | ms | E/W/I | Kind |")
    A("|--------|-----|--------|------|--------|------|----|-------|------|")
    for r in sorted(tested, key=lambda r: (0 if not r["passed"] else 1, r["version"], r["path"])):
        icon = "✅" if r["passed"] else "❌"
        A(f"| {icon} | {r['version']} | {r['method']} | `{_md_escape(r['path'])}` | {r['action']} "
          f"| {r['http_status']} | {r['duration_ms']:.0f} | "
          f"{r['n_error']}/{r['n_warning']}/{r['n_info']} | {r['response_kind']} |")
    A("")

    # ---- skipped with reasons ----
    A("## Skipped endpoints (with reasons)\n")
    A("| Ver | Method | Path | Action | Reason |")
    A("|-----|--------|------|--------|--------|")
    for r in sorted(skipped, key=lambda r: (r["version"], r["path"])):
        A(f"| {r['version']} | {r['method']} | `{_md_escape(r['path'])}` | {r['action']} "
          f"| {_md_escape(r['skip_reason'])} |")
    A("")

    # ---- info-level notes (extra fields etc.) ----
    info_rows = [r for r in tested if r["n_info"] > 0]
    if info_rows:
        A("## Informational notes (extra/undocumented fields)\n")
        A("Fields present in live responses but not in the expected schema — "
          "candidates for updating the spec or trimming the payload.\n")
        A("| Path | Field | Actual type |")
        A("|------|-------|-------------|")
        seen = set()
        for r in info_rows:
            for i in db.issues_for_result(r["id"]):
                if i["code"] == "extra_field":
                    kkey = (r["path"], i["path"])
                    if kkey in seen:
                        continue
                    seen.add(kkey)
                    A(f"| `{_md_escape(r['path'])}` | `{_md_escape(i['path'])}` | `{_md_escape(i['actual'])}` |")
        A("")

    return "\n".join(L)


def build_json(db, run_id: int | None = None) -> dict:
    run = db.conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone() if run_id \
        else db.latest_run()
    if run is None:
        return {}
    run_id = run["id"]
    out = {"run": dict(run), "results": []}
    for r in db.results_for_run(run_id):
        rd = dict(r)
        rd["issues"] = [dict(i) for i in db.issues_for_result(r["id"])]
        out["results"].append(rd)
    return out


def write_report(db, md_path: str | Path, json_path: str | Path | None = None,
                 run_id: int | None = None) -> str:
    md = build_markdown(db, run_id)
    Path(md_path).write_text(md)
    if json_path:
        Path(json_path).write_text(json.dumps(build_json(db, run_id), indent=2, default=str))
    return md
