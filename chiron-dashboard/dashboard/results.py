"""Parse the tools' existing output stores into UI-ready result objects.

Each parser returns:
  { "outcome": passing|warning|failing|error,
    "headline": str,
    "stats": [{label, value, tone}],      # the tile row
    "columns": [...], "rows": [[...]],     # the inline findings/results table
    "generated": iso-ish timestamp }
Nothing is recomputed — we read the same JSON/report the tools already produced.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def _mtime(path) -> str:
    """ISO-ish last-modified time of a file (so the UI can show when a stored
    artifact was generated)."""
    try:
        from datetime import datetime, timezone
        ts = Path(path).stat().st_mtime
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return ""


def parse_validator() -> dict:
    """The validator is a rules-based check: every field on every endpoint has an
    expected type/shape (a rule). We show EVERY endpoint that was checked — both
    the ones that PASSED and the ones that FAILED (with the failing rule + why) —
    plus a per-run timestamp and average response time so a fresh run is visible."""
    d = _load(config.VALIDATOR / "reports" / "latest_run.json")
    if not d:
        return _empty("Validator has not been run yet — press Run.")
    run = d.get("run", {})
    results = d.get("results", [])
    tested = [r for r in results if not r.get("skipped") and r.get("passed") is not None]
    passed = [r for r in tested if r.get("passed")]
    failed = [r for r in tested if not r.get("passed")]
    unreached = [r for r in results if not r.get("skipped") and r.get("passed") is None]
    skipped = [r for r in results if r.get("skipped")]

    n_rules_failed = sum(len([i for i in r.get("issues", []) if i.get("severity") in ("error", "warning")])
                         for r in results)
    n_err = sum(len([i for i in r.get("issues", []) if i.get("severity") == "error"])
                for r in results)
    durs = [r.get("duration_ms") for r in tested if r.get("duration_ms") is not None]
    avg_ms = round(sum(durs) / len(durs), 1) if durs else 0
    rate = round(100 * len(passed) / len(tested), 1) if tested else 0.0
    outcome = "failing" if n_err else ("warning" if n_rules_failed else "passing")

    def why(r):
        parts = []
        for i in r.get("issues", []):
            if i.get("severity") in ("error", "warning"):
                rule = i.get("expected") or i.get("code")
                parts.append(f'{i.get("code")}: expected {rule}, got {i.get("actual")} — {i.get("message", "")[:110]}')
        return " | ".join(parts)

    # rows: FAILED first (with the broken rule), then UNREACHED, then every PASSED endpoint
    rows = []
    for r in sorted(failed, key=lambda r: r.get("path", "")):
        rows.append(["Fail", f'{r.get("method")} {r.get("path")}', r.get("http_status"), why(r)])
    for r in sorted(unreached, key=lambda r: r.get("path", "")):
        det = (r.get("issues") or [{}])[0].get("message", "")
        rows.append(["Unreached", f'{r.get("method")} {r.get("path")}', r.get("http_status"), det[:110]])
    for r in sorted(passed, key=lambda r: r.get("path", "")):
        rows.append(["Pass", f'{r.get("method")} {r.get("path")}', r.get("http_status"),
                     "Response matched all validation rules"])

    return {
        "outcome": outcome,
        "headline": (f'{len(passed)} of {len(tested)} endpoints passed all rules · '
                     f'{len(failed)} failed · {len(unreached)} unreached'),
        "generated": run.get("finished_at") or run.get("started_at"),
        "stats": [
            {"label": "Passed", "value": len(passed), "tone": "good"},
            {"label": "Failed", "value": len(failed), "tone": "bad" if failed else "good"},
            {"label": "Unreached", "value": len(unreached), "tone": "warn" if unreached else "idle"},
            {"label": "Pass rate", "value": f"{rate}%", "tone": "good" if rate >= 90 else "warn"},
            {"label": "Avg response", "value": f"{avg_ms} ms", "tone": "idle"},
        ],
        "columns": ["Status", "Endpoint", "HTTP", "Result"],
        "rows": rows,
        "empty_ok": "Every validation rule passed — no concept or field violated its rule.",
        "note": (f'{len(skipped)} endpoints are not tested by default (create/update/delete writes '
                 f'and non-JSON server views).') if skipped else "",
    }


def parse_benchmark() -> dict:
    d = _load(config.BENCHMARK / "results" / "latest.json")
    if not d:
        return _empty("Benchmark has not been run yet.")
    npass, nfail = d.get("n_pass", 0), d.get("n_fail", 0)
    total = d.get("n_controls", 0)
    measured = npass + nfail
    rate = round(100 * npass / measured, 0) if measured else 0
    outcome = "passing" if nfail == 0 else "warning"
    # show ALL controls (passing AND failing), failures first
    rows = []
    for c in sorted(d.get("controls", []), key=lambda c: 0 if c.get("pass") is False else 1):
        ctl = c["control"]
        status = "Pass" if c.get("pass") else ("Fail" if c.get("pass") is False else "n/a")
        rows.append([status, ctl["category"], ctl["name"], c.get("detail", "")])
    return {
        "outcome": outcome,
        "headline": f'{npass}/{measured} controls passing ({rate:.0f}%) · {nfail} failing',
        "generated": d.get("finished"),
        "stats": [
            {"label": "Controls", "value": total, "tone": "idle"},
            {"label": "Passing", "value": npass, "tone": "good"},
            {"label": "Failing", "value": nfail, "tone": "bad" if nfail else "good"},
            {"label": "Dataset", "value": d.get("dataset", "unknown"), "tone": "idle"},
        ],
        "columns": ["Status", "Area", "Control", "Measured vs target"],
        "rows": rows,
        "empty_ok": "All controls passed.",
    }


def parse_findings(kind: str) -> dict:
    """kind = 'security' | 'efficiency'."""
    d = _load(config.FINDINGS_STORE)
    if not d:
        return _empty("No scan results stored yet.")
    findings = d.get(kind, [])

    def sev(f):
        return (f.get("verdict", {}).get("corrected_severity") or f.get("severity") or "info").lower()

    findings = sorted(findings, key=lambda f: SEV_ORDER.get(sev(f), 9))
    counts = {}
    for f in findings:
        counts[sev(f)] = counts.get(sev(f), 0) + 1
    top = min((SEV_ORDER.get(sev(f), 9) for f in findings), default=9)
    outcome = ("failing" if top <= 1 else "warning" if top == 2 else "passing")
    rows = []
    for f in findings:
        loc = (f.get("location", "") or "").split(";")[0][:60]
        rows.append([sev(f), f.get("title", "")[:110], loc])
    stat_tone = {"critical": "bad", "high": "bad", "medium": "warn", "low": "idle", "info": "idle"}
    stats = [{"label": s.title(), "value": counts.get(s, 0),
              "tone": stat_tone[s]} for s in ("critical", "high", "medium", "low", "info")
             if counts.get(s)]
    label = "security" if kind == "security" else "efficiency"
    return {
        "outcome": outcome,
        "headline": f'{len(findings)} verified {label} findings',
        "stats": stats or [{"label": "Findings", "value": 0, "tone": "good"}],
        "columns": ["Severity", "Finding", "Location"],
        "rows": rows,
        "empty_ok": "No findings.",
        "generated": _mtime(config.FINDINGS_STORE),
        "static": True,
        "note": "Stored audit — this panel re-loads the last audit (it does not re-scan on each "
                "click; the audit is a heavier Claude multi-agent job). \"Generated\" below is when "
                "that audit was produced.",
    }


def _empty(msg):
    return {"outcome": "idle", "headline": msg, "stats": [], "columns": [],
            "rows": [], "empty_ok": msg, "generated": None}


def parse_scanner(which: str) -> dict:
    """Parse the LIVE scanner output (chiron-scanners) — which = 'vuln' | 'ineff'.
    Unlike the old stored-audit panel, this reflects a scan that just ran."""
    path = config.SCANNERS / "results" / f"{which}.json"
    d = _load(path)
    if not d:
        return _empty("No scan yet — press Run.")
    findings = d.get("findings", [])
    counts = d.get("summary", {})
    top = min((SEV_ORDER.get(f.get("severity"), 9) for f in findings), default=9)
    outcome = "failing" if top <= 1 else ("warning" if top == 2 else "passing")
    stat_tone = {"critical": "bad", "high": "bad", "medium": "warn", "low": "idle", "info": "idle"}
    stats = [{"label": s.title(), "value": counts.get(s, 0), "tone": stat_tone[s]}
             for s in ("critical", "high", "medium", "low", "info") if counts.get(s)]
    rows = [[f.get("severity"), f.get("category"), f.get("title"), f.get("location")]
            for f in findings]
    label = "security" if which == "vuln" else "code-quality"
    live = " + live API probes" if which == "vuln" else ""
    return {
        "outcome": outcome,
        "headline": f"{len(findings)} {label} findings from a fresh scan",
        "generated": d.get("generated"),
        "stats": stats or [{"label": "Findings", "value": 0, "tone": "good"}],
        "columns": ["Severity", "Area", "Finding", "Location"],
        "rows": rows,
        "empty_ok": "Clean scan — no findings.",
        "note": f"Ran just now against the current source{live}. Re-runs fresh every time.",
    }


def parse_dataquality() -> dict:
    """Parse the pre-existing data-validator's --json-out (data-QUALITY checks on
    concept statistics). Returns the rich shape the Data quality tab renders:
    a per-dataset summary, a by-rule rollup, EVERY concept with its status, and
    the detailed issues. `kind` == "dataquality" tells the UI to use the custom
    renderer."""
    d = _load(config.DATA / "dataquality.json")
    if not d:
        return _empty("No data-quality scan yet — press Run.")

    datasets_raw = d.get("datasets", [])
    ds_rows, concepts, issues, errored = [], [], [], []
    by_rule = {}
    tot_scanned = tot_ok = tot_issues_concepts = tot_skipped = 0

    for ds in datasets_raw:
        name = ds.get("dataset")
        if ds.get("error"):
            errored.append((name, ds["error"]))
        cs = ds.get("concepts", [])
        n_ok = sum(1 for c in cs if c.get("status") == "ok")
        n_iss = sum(1 for c in cs if c.get("status") == "issues")
        n_skip = sum(1 for c in cs if c.get("status") == "skipped")
        scanned = ds.get("concept_count", len(cs))
        ds_rows.append({
            "dataset": name, "subjects": ds.get("total_subjects"),
            "scanned": scanned, "ok": n_ok, "with_issues": n_iss,
            "skipped": n_skip, "issues": len(ds.get("issues", [])),
            "error": ds.get("error"),
        })
        tot_scanned += scanned; tot_ok += n_ok
        tot_issues_concepts += n_iss; tot_skipped += n_skip
        for c in cs:
            concepts.append({
                "dataset": name, "concept": c.get("concept_name") or c.get("concept_id"),
                "type": c.get("concept_type"), "status": c.get("status"),
                "issues": c.get("issue_count", 0),
                "detail": ", ".join(c.get("issue_kinds", [])) or (c.get("skip_reason") or ""),
            })
        for i in ds.get("issues", []):
            issues.append(i)
            by_rule[i.get("kind")] = by_rule.get(i.get("kind"), 0) + 1

    issues.sort(key=lambda i: SEV_ORDER.get((i.get("severity") or "").lower(), 9))
    sev_counts = {}
    for i in issues:
        s = (i.get("severity") or "info").lower()
        sev_counts[s] = sev_counts.get(s, 0) + 1
    top = min((SEV_ORDER.get((i.get("severity") or "").lower(), 9) for i in issues), default=9)
    outcome = "failing" if (top <= 1 or errored) else ("warning" if issues else "passing")
    total_issues = d.get("summary", {}).get("total_issues", len(issues))

    return {
        "kind": "dataquality",
        "outcome": outcome,
        "headline": (f"{total_issues} issue(s) across {len(datasets_raw)} dataset(s) · "
                     f"{tot_issues_concepts} of {tot_scanned} concepts flagged"),
        "generated": d.get("generated_at"),
        "note": "Live run: logs into Chiron and checks every concept's statistics against the "
                "rules below. 'high_missingness' is a symptom, not proof — Chiron's ETL silently "
                "nulls values that fail their type cast, and that record isn't exposed by the API.",
        "stats": [
            {"label": "Datasets", "value": len(datasets_raw), "tone": "idle"},
            {"label": "Concepts", "value": tot_scanned, "tone": "idle"},
            {"label": "Flagged", "value": tot_issues_concepts, "tone": "bad" if tot_issues_concepts else "good"},
            {"label": "Clean", "value": tot_ok, "tone": "good"},
            {"label": "Skipped", "value": tot_skipped, "tone": "warn" if tot_skipped else "idle"},
            {"label": "Issues", "value": total_issues, "tone": "bad" if total_issues else "good"},
        ],
        "datasets": ds_rows,
        "by_rule": [{"kind": k, "count": v} for k, v in sorted(by_rule.items(), key=lambda kv: -kv[1])],
        "concepts": concepts,
        "issues": [{"severity": i.get("severity"), "dataset": i.get("dataset"),
                    "concept": i.get("concept_name") or i.get("concept_id"),
                    "kind": i.get("kind"), "message": (i.get("message") or "")} for i in issues],
        "sev_counts": sev_counts,
    }


def parse(result_key: str) -> dict:
    if result_key == "validator":
        return parse_validator()
    if result_key == "benchmark":
        return parse_benchmark()
    if result_key == "vulnscan":
        return parse_scanner("vuln")
    if result_key == "ineffscan":
        return parse_scanner("ineff")
    if result_key == "dataquality":
        return parse_dataquality()
    return _empty("Unknown result type.")
