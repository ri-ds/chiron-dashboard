"""Self-contained HTML report - single file, zero external resources (no CDN
scripts/fonts/styles), so it opens correctly straight from disk (file://)
with no network access needed. Plain/vanilla JS only, no build step.

`render_report_html(..., standalone=True)` returns a full HTML document
(doctype/html/head/body) meant to be written straight to disk via
`write_html_report`. `standalone=False` returns just a <title> + <style> +
body-content fragment, useful for embedding elsewhere.
"""

from __future__ import annotations

import html as html_lib
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import DatasetRunResult

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
SEVERITY_LABEL = {"high": "High", "medium": "Medium", "low": "Low", "info": "Info"}

LIMITATION_NOTICE = (
    "'high_missingness' is a SYMPTOM, not a diagnosis. Chiron's ETL layer casts "
    "incoming values to their declared type and silently nulls anything that fails "
    "that cast, before storage. This API cannot tell genuinely-absent-in-source data "
    "apart from malformed-then-silently-nulled data - both look identical as "
    "'missing' here. The record of which is which (ConceptIssueEtlLog) is internal "
    "to Chiron and is not exposed by any current API endpoint. See README.md "
    "'Limitations' for detail."
)

STYLE = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --border: #e5e7eb;
  --card-bg: #f9fafb; --header-bg: #f3f4f6;
  --high: #b91c1c; --high-bg: #fef2f2; --high-border: #fecaca;
  --medium: #b45309; --medium-bg: #fffbeb; --medium-border: #fde68a;
  --low: #1d4ed8; --low-bg: #eff6ff; --low-border: #bfdbfe;
  --accent: #4f46e5; --limitation-bg: #fefce8; --limitation-border: #ca8a04;
  --chip-bg: #eef2ff; --chip-fg: #3730a3;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --border: #2d2d33;
    --card-bg: #18181b; --header-bg: #1c1c21;
    --high: #fca5a5; --high-bg: #2a1417; --high-border: #4a2024;
    --medium: #fcd34d; --medium-bg: #2a2313; --medium-border: #4a3a17;
    --low: #93c5fd; --low-bg: #12203a; --low-border: #1f3a5f;
    --accent: #a5b4fc; --limitation-bg: #2a2610; --limitation-border: #92720c;
    --chip-bg: #24243f; --chip-fg: #c7d2fe;
  }
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--fg); margin: 0; padding: 1.5rem 2rem 3rem;
  line-height: 1.5; max-width: 1100px; margin-left: auto; margin-right: auto;
}
h1 { font-size: 1.5rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.15rem; margin: 0; }
h3 { font-size: 1rem; margin: 0 0 0.5rem; }
.meta { color: var(--muted); font-size: 0.9rem; margin-bottom: 1rem; }
.meta span { margin-right: 1.25rem; }
.limitation {
  background: var(--limitation-bg); border: 1px solid var(--limitation-border);
  border-radius: 8px; padding: 0.75rem 1rem; font-size: 0.9rem; margin-bottom: 1.5rem;
}
.limitation strong { color: var(--limitation-border); }
.stats { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1.5rem; }
.stat-tile {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.75rem 1rem; min-width: 120px; flex: 1;
}
.stat-tile .n { font-size: 1.6rem; font-weight: 700; display: block; }
.stat-tile .l { color: var(--muted); font-size: 0.8rem; }
.stat-tile.high .n { color: var(--high); }
.stat-tile.medium .n { color: var(--medium); }
.stat-tile.low .n { color: var(--low); }
.filters {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.9rem 1rem; margin-bottom: 1.5rem; display: flex; flex-wrap: wrap;
  gap: 1rem 1.75rem; align-items: flex-start; font-size: 0.85rem;
}
.filters input[type=search] {
  padding: 0.4rem 0.6rem; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--fg); font-size: 0.85rem; min-width: 220px;
}
.filter-group { display: flex; flex-direction: column; gap: 0.3rem; }
.filter-group .fg-title { color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.03em; }
.filter-group label { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; white-space: nowrap; }
#visible-count { margin-left: auto; align-self: center; color: var(--muted); font-size: 0.85rem; }
.dataset-section {
  border: 1px solid var(--border); border-radius: 10px; margin-bottom: 1.25rem; overflow: hidden;
}
.dataset-header {
  background: var(--header-bg); padding: 0.75rem 1rem; display: flex;
  justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 0.5rem;
}
.dataset-header .ds-meta { color: var(--muted); font-size: 0.85rem; }
.dataset-body { padding: 0.9rem 1rem; }
.dataset-error { color: var(--high); font-weight: 600; }
.no-issues, .no-match-message { color: var(--muted); font-style: italic; }
.concept-group { border-top: 1px solid var(--border); padding: 0.75rem 0; }
.concept-group:first-child { border-top: none; padding-top: 0; }
.concept-title { font-weight: 600; }
.concept-title .ctype { color: var(--muted); font-weight: 400; font-size: 0.85rem; }
.issue {
  display: flex; gap: 0.6rem; align-items: flex-start; margin: 0.4rem 0 0.4rem 0.25rem;
  padding: 0.5rem 0.65rem; border-radius: 6px; font-size: 0.9rem;
}
.issue.high { background: var(--high-bg); border: 1px solid var(--high-border); }
.issue.medium { background: var(--medium-bg); border: 1px solid var(--medium-border); }
.issue.low { background: var(--low-bg); border: 1px solid var(--low-border); }
.badge {
  flex-shrink: 0; font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  padding: 0.15rem 0.45rem; border-radius: 4px; letter-spacing: 0.02em;
}
.badge.high { background: var(--high); color: white; }
.badge.medium { background: var(--medium); color: white; }
.badge.low { background: var(--low); color: white; }
.kind-chip {
  background: var(--chip-bg); color: var(--chip-fg); font-size: 0.75rem;
  padding: 0.1rem 0.4rem; border-radius: 4px; margin-right: 0.4rem; white-space: nowrap;
}
.skipped-details { margin-top: 0.75rem; font-size: 0.85rem; color: var(--muted); }
.skipped-details summary { cursor: pointer; }
footer { color: var(--muted); font-size: 0.8rem; margin-top: 2rem; text-align: center; }
"""

SCRIPT = """
function applyFilters() {
  var q = document.getElementById('search').value.trim().toLowerCase();
  var activeSeverities = Array.prototype.map.call(document.querySelectorAll('.sev-filter:checked'), function(el) { return el.value; });
  var activeKinds = Array.prototype.map.call(document.querySelectorAll('.kind-filter:checked'), function(el) { return el.value; });
  var activeDatasets = Array.prototype.map.call(document.querySelectorAll('.dataset-filter:checked'), function(el) { return el.value; });

  var visibleCount = 0, totalCount = 0;
  document.querySelectorAll('.issue').forEach(function(issue) {
    totalCount++;
    var sev = issue.getAttribute('data-severity');
    var kind = issue.getAttribute('data-kind');
    var ds = issue.getAttribute('data-dataset');
    var text = issue.getAttribute('data-search') || '';
    var match = activeSeverities.indexOf(sev) !== -1
      && activeKinds.indexOf(kind) !== -1
      && activeDatasets.indexOf(ds) !== -1
      && (!q || text.indexOf(q) !== -1);
    issue.style.display = match ? '' : 'none';
    if (match) visibleCount++;
  });

  document.querySelectorAll('.concept-group').forEach(function(group) {
    var visible = Array.prototype.some.call(group.querySelectorAll('.issue'), function(i) { return i.style.display !== 'none'; });
    group.style.display = visible ? '' : 'none';
  });

  document.querySelectorAll('.dataset-section').forEach(function(section) {
    var issueEls = section.querySelectorAll('.issue');
    var existingMsg = section.querySelector('.no-match-message');
    if (existingMsg) existingMsg.remove();
    if (issueEls.length === 0) return; // "no issues" / error sections: leave untouched
    var anyGroupVisible = Array.prototype.some.call(section.querySelectorAll('.concept-group'), function(g) { return g.style.display !== 'none'; });
    var datasetOk = activeDatasets.indexOf(section.getAttribute('data-dataset')) !== -1;
    if (datasetOk && !anyGroupVisible) {
      var msg = document.createElement('p');
      msg.className = 'no-match-message';
      msg.textContent = 'No issues in this dataset match the current filters.';
      section.querySelector('.dataset-body').appendChild(msg);
    }
    section.style.display = datasetOk ? '' : 'none';
  });

  document.getElementById('visible-count').textContent = 'Showing ' + visibleCount + ' of ' + totalCount + ' issue(s)';
}

document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.filters input').forEach(function(el) {
    el.addEventListener('input', applyFilters);
    el.addEventListener('change', applyFilters);
  });
  applyFilters();
});
"""


def _esc(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


def _humanize(kind: str) -> str:
    return kind.replace("_", " ").title()


def _severity_rank(sev: str) -> int:
    return SEVERITY_ORDER.get(sev, 99)


def _render_issue(issue: Any, dataset: str) -> str:
    sev = issue.severity if issue.severity in SEVERITY_LABEL else "info"
    # Search matches against data-search rather than the issue's own
    # textContent, because the concept id/name is rendered once in the
    # parent .concept-group header, not repeated inside every .issue div -
    # without this, searching by concept name (e.g. "provider") finds
    # nothing even though that's the most natural thing to search for.
    search_blob = " ".join([issue.concept_id, issue.concept_name, issue.kind, issue.message])
    return (
        f'<div class="issue {sev}" data-severity="{_esc(sev)}" '
        f'data-kind="{_esc(issue.kind)}" data-dataset="{_esc(dataset)}" '
        f'data-search="{_esc(search_blob.lower())}">'
        f'<span class="badge {sev}">{_esc(SEVERITY_LABEL.get(sev, sev))}</span>'
        f'<span><span class="kind-chip">{_esc(_humanize(issue.kind))}</span>{_esc(issue.message)}</span>'
        f"</div>"
    )


def _render_dataset(dr: DatasetRunResult) -> str:
    parts = [
        f'<div class="dataset-section" data-dataset="{_esc(dr.dataset)}">',
        '<div class="dataset-header">',
        f"<h2>{_esc(dr.dataset)}</h2>",
    ]
    if dr.error:
        parts.append(f'<span class="ds-meta dataset-error">could not process this dataset</span>')
        parts.append("</div>")
        parts.append(f'<div class="dataset-body"><p class="dataset-error">{_esc(dr.error)}</p></div>')
        parts.append("</div>")
        return "".join(parts)

    parts.append(
        f'<span class="ds-meta">subjects={_esc(dr.total_subjects)} &middot; '
        f"concepts_scanned={_esc(dr.concept_count)} &middot; "
        f"concepts_skipped={_esc(len(dr.skipped))} &middot; "
        f"issues={_esc(len(dr.issues))}</span>"
    )
    parts.append("</div>")
    parts.append('<div class="dataset-body">')

    if not dr.issues:
        parts.append('<p class="no-issues">No issues found.</p>')
    else:
        by_concept: Dict[str, List[Any]] = {}
        for issue in dr.issues:
            by_concept.setdefault(issue.concept_id, []).append(issue)
        for cid, issues in by_concept.items():
            issues_sorted = sorted(issues, key=lambda i: _severity_rank(i.severity))
            cname = issues_sorted[0].concept_name
            ctype = issues_sorted[0].concept_type
            parts.append('<div class="concept-group">')
            parts.append(
                f'<div class="concept-title">{_esc(cid)} '
                f"({_esc(cname)}) <span class=\"ctype\">[{_esc(ctype)}]</span></div>"
            )
            for issue in issues_sorted:
                parts.append(_render_issue(issue, dr.dataset))
            parts.append("</div>")

    if dr.skipped:
        reasons = Counter(s.reason_kind for s in dr.skipped)
        reasons_str = ", ".join(f"{k}: {v}" for k, v in reasons.items())
        parts.append('<details class="skipped-details"><summary>')
        parts.append(f"{_esc(len(dr.skipped))} concept(s) skipped ({_esc(reasons_str)})</summary>")
        parts.append("<ul>")
        for s in dr.skipped:
            parts.append(f"<li>{_esc(s.concept_id)} ({_esc(s.concept_name)}): {_esc(s.reason)}</li>")
        parts.append("</ul></details>")

    parts.append("</div></div>")
    return "".join(parts)


def render_report_html(
    results: List[DatasetRunResult],
    missing_threshold: float,
    base_url: str,
    standalone: bool = True,
) -> str:
    """Build the HTML report. `standalone=True` returns a full document
    (doctype/html/head/body); `standalone=False` returns just a <title> +
    <style> + body-content fragment (e.g. for embedding elsewhere)."""

    total_issues = 0
    kind_counter: Counter = Counter()
    severity_counter: Counter = Counter()
    all_kinds = set()
    total_skipped = 0
    for dr in results:
        for issue in dr.issues:
            total_issues += 1
            kind_counter[issue.kind] += 1
            severity_counter[issue.severity] += 1
            all_kinds.add(issue.kind)
        total_skipped += len(dr.skipped)

    generated_at = datetime.now(timezone.utc).isoformat()

    body_parts: List[str] = []
    body_parts.append("<h1>Chiron Data Validator Report</h1>")
    body_parts.append(
        '<div class="meta">'
        f"<span>Server: {_esc(base_url)}</span>"
        f"<span>Generated: {_esc(generated_at)}</span>"
        f"<span>Missing-value threshold: {missing_threshold:.0%}</span>"
        "</div>"
    )
    body_parts.append(f'<div class="limitation"><strong>Limitation:</strong> {_esc(LIMITATION_NOTICE)}</div>')

    body_parts.append('<div class="stats">')
    body_parts.append(f'<div class="stat-tile"><span class="n">{total_issues}</span><span class="l">Total issues</span></div>')
    body_parts.append(f'<div class="stat-tile"><span class="n">{len(results)}</span><span class="l">Datasets scanned</span></div>')
    body_parts.append(f'<div class="stat-tile"><span class="n">{sum(dr.concept_count for dr in results)}</span><span class="l">Concepts scanned</span></div>')
    body_parts.append(f'<div class="stat-tile"><span class="n">{total_skipped}</span><span class="l">Concepts skipped</span></div>')
    for sev in ("high", "medium", "low"):
        body_parts.append(
            f'<div class="stat-tile {sev}"><span class="n">{severity_counter.get(sev, 0)}</span>'
            f'<span class="l">{SEVERITY_LABEL[sev]} severity</span></div>'
        )
    body_parts.append("</div>")

    # --- filter bar ---
    body_parts.append('<div class="filters">')
    body_parts.append(
        '<div class="filter-group"><span class="fg-title">Search</span>'
        '<input type="search" id="search" placeholder="Filter by concept, message..."></div>'
    )
    body_parts.append('<div class="filter-group"><span class="fg-title">Severity</span>')
    for sev in ("high", "medium", "low", "info"):
        if sev == "info" and severity_counter.get("info", 0) == 0:
            continue
        body_parts.append(
            f'<label><input type="checkbox" class="sev-filter" value="{sev}" checked> '
            f"{SEVERITY_LABEL.get(sev, sev)} ({severity_counter.get(sev, 0)})</label>"
        )
    body_parts.append("</div>")
    body_parts.append('<div class="filter-group"><span class="fg-title">Issue kind</span>')
    for kind in sorted(all_kinds):
        body_parts.append(
            f'<label><input type="checkbox" class="kind-filter" value="{_esc(kind)}" checked> '
            f"{_esc(_humanize(kind))} ({kind_counter[kind]})</label>"
        )
    body_parts.append("</div>")
    body_parts.append('<div class="filter-group"><span class="fg-title">Dataset</span>')
    for dr in results:
        body_parts.append(
            f'<label><input type="checkbox" class="dataset-filter" value="{_esc(dr.dataset)}" checked> '
            f"{_esc(dr.dataset)} ({len(dr.issues)})</label>"
        )
    body_parts.append("</div>")
    body_parts.append('<span id="visible-count"></span>')
    body_parts.append("</div>")

    for dr in results:
        body_parts.append(_render_dataset(dr))

    body_parts.append(
        "<footer>Generated by chiron_validator - see HOW_IT_WORKS.md for what each check means and its limitations.</footer>"
    )

    body_html = "".join(body_parts)

    if not standalone:
        return f"<title>Chiron Data Validator Report</title><style>{STYLE}</style>{body_html}<script>{SCRIPT}</script>"

    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Chiron Data Validator Report</title>\n"
        f"<style>{STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{body_html}\n"
        f"<script>{SCRIPT}</script>\n"
        "</body>\n</html>\n"
    )


def write_html_report(path: str, html_str: str) -> None:
    """Write `html_str` to `path`. Raises OSError (with the path folded into
    the message) on failure - callers must catch this the same way as
    write_json_report (see report.py), rather than letting a raw traceback
    escape after an otherwise-successful console report."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_str)
    except OSError as exc:
        raise OSError(f"could not write HTML report to {path!r}: {exc}") from exc
