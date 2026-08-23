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


def parse_validator(data: dict | None = None) -> dict:
    """The validator is a rules-based check: every field on every endpoint has an
    expected type/shape (a rule). We show EVERY endpoint that was checked — both
    the ones that PASSED and the ones that FAILED (with the failing rule + why) —
    plus a per-run timestamp and average response time so a fresh run is visible.

    `data` lets a caller supply an already-loaded report — that is how the live
    RDCRN run reuses this exact rendering instead of duplicating it."""
    d = data if data is not None else _load(config.VALIDATOR / "reports" / "latest_run.json")
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
            {"label": "Not tested", "value": len(skipped), "tone": "idle"},
        ],
        "columns": ["Status", "Endpoint", "HTTP", "Result"],
        "rows": rows,
        "empty_ok": "Every validation rule passed — no concept or field violated its rule.",
        "note": "",
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


def _live_host() -> str:
    """Host the live results actually came from, per the saved session.

    Read at render time rather than baked in: the target is whatever was signed
    into on the Login tab, so any fixed deployment name here would eventually be a
    lie -- as "Live RDCRN" was, while every run went to a different site.
    """
    try:
        raw = json.loads((config.RDCRN / ".session" / "site.json").read_text())
        return (raw.get("site") or "").replace("https://", "").replace("http://", "")
    except Exception:
        return ""


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
        # Not "from a fresh scan": this reads whatever file is on disk, which may be
        # months old. The rendered "Data from <timestamp>" is the only freshness
        # claim that is actually true.
        "headline": f"{len(findings)} {label} findings",
        "generated": d.get("generated"),
        "stats": stats or [{"label": "Findings", "value": 0, "tone": "good"}],
        "columns": ["Severity", "Area", "Finding", "Location"],
        "rows": rows,
        "empty_ok": "Clean scan — no findings.",
        "note": "",
    }


def parse_dataquality(data: dict | None = None) -> dict:
    """Parse the pre-existing data-validator's --json-out (data-QUALITY checks on
    concept statistics). Returns the rich shape the Data quality tab renders:
    a per-dataset summary, a by-rule rollup, EVERY concept with its status, and
    the detailed issues. `kind` == "dataquality" tells the UI to use the custom
    renderer."""
    d = data if data is not None else _load(config.DATA / "dataquality.json")
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
        # Rules carry their catalogue entry so the UI can expand one into what it
        # actually checks, rather than showing a bare internal kind string.
        "by_rule": [{"kind": k, "count": v, **_rule_meta(k)}
                    for k, v in sorted(by_rule.items(), key=lambda kv: -kv[1])],
        "concepts": concepts,
        # `details` is the evidence each check recorded — the offending category and
        # its count, the min/max/avg behind an outlier. Without it an issue is just
        # an assertion; with it you can judge the finding yourself.
        "issues": [{"severity": i.get("severity"), "dataset": i.get("dataset"),
                    "concept": i.get("concept_name") or i.get("concept_id"),
                    "concept_id": i.get("concept_id"),
                    "concept_type": i.get("concept_type"),
                    "kind": i.get("kind"), "message": (i.get("message") or ""),
                    "details": i.get("details") or {}} for i in issues],
        "projects": sorted({i.get("dataset") for i in issues if i.get("dataset")}),
        "sev_counts": sev_counts,
    }


_RULE_META_CACHE = None


def _rule_meta(kind: str) -> dict:
    """Catalogue entry for an issue kind: label, description, tunable parameters.

    Sourced from the data-validator's own rule catalogue rather than restated here,
    so the explanation shown in the UI cannot drift from the rule that produced the
    finding.
    """
    global _RULE_META_CACHE
    if _RULE_META_CACHE is None:
        _RULE_META_CACHE = {}
        try:
            from . import dqrules
            for rule in (dqrules.catalog_and_defaults().get("catalog") or []):
                for k in rule.get("kinds") or []:
                    _RULE_META_CACHE[k] = {
                        "rule_id": rule.get("id"),
                        "label": rule.get("label") or k,
                        "description": rule.get("description") or "",
                        "params": rule.get("params") or [],
                    }
        except Exception:
            pass
    return _RULE_META_CACHE.get(kind, {"label": kind, "description": "", "params": []})


def parse_rdcrn_pages() -> dict:
    """Live page checks against the real RDCRN deployment (no credentials)."""
    d = _load(config.RDCRN / "results" / "ui_check.json")
    if not d:
        return _empty("No page checks yet — press Run.")

    results = d.get("results", [])
    passed, failed = d.get("passed", 0), d.get("failed", 0)
    rows = []
    for r in results:
        steps = r.get("steps") or []
        ok_steps = sum(1 for s in steps if s.get("ok"))
        # On failure the reason replaces the rationale — that is what you need at a
        # glance. On success the rationale explains what the check is defending.
        if r.get("passed"):
            detail = r.get("why") or ""
        else:
            detail = "; ".join(r.get("failures") or []) or "failed"
        rows.append([
            "Pass" if r.get("passed") else "Fail",
            r.get("name"),
            r.get("status"),
            f"{r.get('load_ms')} ms" if r.get("load_ms") is not None else "",
            f"{ok_steps}/{len(steps)}" if steps else "—",
            detail,
        ])

    return {
        "outcome": "passing" if not failed else "failing",
        "headline": (f"{passed} of {len(results)} live page checks passing"
                     if not failed else
                     f"{failed} of {len(results)} live page checks FAILING"),
        "generated": d.get("started"),
        "stats": [
            {"label": "Passing", "value": passed, "tone": "good" if passed else "idle"},
            {"label": "Failing", "value": failed, "tone": "bad" if failed else "good"},
        ],
        "columns": ["Status", "Check", "HTTP", "Load", "Steps", "Detail"],
        "rows": rows,
        "empty_ok": "No checks ran.",
        "note": "",
    }


def parse_rdcrn_api() -> dict:
    """Authenticated checks against the live RDCRN catalog."""
    d = _load(config.RDCRN / "results" / "api_check.json")
    if not d:
        return _empty("No API check yet — press Run.")

    session = d.get("session")
    checks = d.get("checks", [])
    datasets = d.get("datasets", [])

    if session != "live":
        # Be precise: an expired session is not the account losing access.
        return {
            "outcome": "warning",
            "headline": "Signed-out — the saved SSO session has expired",
            "generated": d.get("generated"),
            "stats": [{"label": "Session", "value": "expired", "tone": "warn"}],
            "columns": ["Status", "Check", "Detail"],
            "rows": [["Fail", c.get("name"), c.get("detail")] for c in checks],
            "empty_ok": "",
            "note": "Sign in again on the Login tab.",
        }

    bad = [c for c in checks if c.get("status") != "pass"]
    rows = [[c.get("name"), c.get("status", "").title(), c.get("detail")] for c in checks]
    rows = [[r[1], r[0], r[2]] for r in rows]  # Status first, matching the other tabs
    for ds in datasets:
        rows.append([
            ds.get("status", "").title(),
            f"{ds.get('name')} ({ds.get('unique_id')})",
            f"{ds.get('subjectCount')} subjects · imported {ds.get('lastImport')} "
            f"· access {ds.get('accessLevel')}",
        ])

    return {
        "outcome": "passing" if not bad else "warning",
        "headline": (f"Chiron {d.get('chiron_version')} — "
                     f"{len(datasets)} dataset(s) visible"),
        "generated": d.get("generated"),
        "stats": [
            {"label": "Session", "value": "live", "tone": "good"},
            {"label": "Chiron", "value": d.get("chiron_version") or "?", "tone": "idle"},
            {"label": "Datasets", "value": len(datasets), "tone": "idle"},
            {"label": "Failed checks", "value": len(bad),
             "tone": "bad" if bad else "good"},
        ],
        "columns": ["Status", "Check", "Detail"],
        "rows": rows,
        "empty_ok": "No checks ran.",
        "note": f"Signed in as {d.get('user')}. Read-only.",
    }


def _no_session(what: str) -> dict:
    """Shown when a live tool ran but found no session.

    Worth distinguishing loudly from a failure: the account has not lost access,
    the saved session has simply expired.
    """
    return {"outcome": "warning",
            "headline": "Not signed in — no live session",
            "generated": None,
            "stats": [{"label": "Session", "value": "none", "tone": "warn"}],
            "columns": ["Status", "What"],
            "rows": [["Fail", f"{what} needs a session. Sign in on the Login tab."]],
            "empty_ok": "",
            "note": "Sign in on the Login tab, then run this again."}


def parse_dataquality_live() -> dict:
    """Same rendering as the local tab, reading the live run's output.

    With one addition that matters: if every dataset errored, the underlying report
    still says "0 issues", because it found none — it never got to look. Reporting
    that as a clean result would be a false green, so a run that could not read
    anything is stated as blocked instead.
    """
    d = _load(config.RDCRN / "results" / "dataquality_live.json")
    if not d:
        return _no_session("Data quality")

    datasets = d.get("datasets") or []
    errored = [ds for ds in datasets if ds.get("error")]
    if datasets and len(errored) == len(datasets):
        forbidden = any("403" in (ds.get("error") or "") for ds in errored)
        return {
            "outcome": "failing",
            # Do not conclude "this account cannot read concept data" from a 403. The
            # same 403 appeared when the run was aimed at the wrong site entirely.
            "headline": ("Blocked — every dataset refused (HTTP 403)"
                         if forbidden else "Blocked — no dataset could be read"),
            "generated": d.get("generated_at"),
            "stats": [
                {"label": "Datasets", "value": len(datasets), "tone": "idle"},
                {"label": "Readable", "value": 0, "tone": "bad"},
            ],
            "columns": ["Status", "Dataset", "Why"],
            "rows": [["Fail", ds.get("dataset"),
                      (ds.get("error") or "")[:160]] for ds in errored],
            "empty_ok": "",
            "note": ("Nothing was readable, so this does not mean the data is clean. "
                     "Check the target site and dataset the run reported before "
                     "concluding it is a permissions limit."),
        }
    return parse_dataquality(d)


def parse_validator_live() -> dict:
    d = _load(config.RDCRN / "results" / "validator_live.json")
    if not d:
        return _no_session("Validator")
    res = parse_validator(d)

    # A 403 here is the account's access level, not a broken endpoint. Scoring it
    # as a failure inflates the count and buries the genuine ones — with an
    # aggregate-level account that is 14 rows of noise hiding a real HTTP 500.
    refused, failed = 0, 0
    for row in res.get("rows") or []:
        if row[0] == "Fail" and str(row[2]) == "403":
            row[0] = "Refused"
            refused += 1
        elif row[0] == "Fail":
            failed += 1
    # Refusals last: they are the expected, uninteresting rows.
    order = {"Fail": 0, "Unreached": 1, "Pass": 2, "Refused": 3}
    res["rows"] = sorted(res.get("rows") or [], key=lambda r: order.get(r[0], 4))

    passed = next((s["value"] for s in res["stats"] if s["label"] == "Passed"), 0)
    res["outcome"] = "failing" if failed else ("warning" if refused else "passing")
    # "(no access)" stated a cause the data does not carry. All this counts is how
    # many endpoints answered 403.
    res["headline"] = (f"{failed} real failure(s) · {passed} passed · "
                       f"{refused} refused (HTTP 403)")
    res["stats"] = [
        {"label": "Passed", "value": passed, "tone": "good"},
        {"label": "Failed", "value": failed, "tone": "bad" if failed else "good"},
        {"label": "Refused", "value": refused, "tone": "idle"},
        *[s for s in res["stats"] if s["label"] in ("Unreached", "Avg response")],
    ]
    # The old note read: "Live RDCRN. Refused means your account lacks access, not a
    # defect." Three things wrong with it. It named a deployment that was not
    # necessarily the target. It asserted a cause this tool cannot establish -- a 403
    # is equally consistent with a permissions bug or a misconfigured run. And it was
    # attached unconditionally, so it explained refusals on runs that had none.
    host = _live_host()
    bits = [f"Live target: {host}." if host else "Live run against the signed-in site."]
    if refused:
        bits.append(f"{refused} endpoint(s) answered 403. That is often an access-level "
                    f"limit, but a 403 can equally be a permissions defect or a run "
                    f"pointed at the wrong dataset {EM} confirm before dismissing it.")
    res["note"] = " ".join(bits)
    return res


def parse(result_key: str) -> dict:
    if result_key == "rdcrn_pages":
        return parse_rdcrn_pages()
    if result_key == "rdcrn_api":
        return parse_rdcrn_api()
    if result_key == "dataquality_live":
        return parse_dataquality_live()
    if result_key == "validator_live":
        return parse_validator_live()
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
