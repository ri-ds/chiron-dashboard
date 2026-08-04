"""Inefficiency / code-quality scanner — runs live every time.

Real static analysis over the actual source on each run: N+1 query heuristic,
oversized pagination defaults, dead/duplicated code, disabled caching, and
front-end bundle bloat. Nothing is read from a prior report.
"""

from __future__ import annotations

import re
from pathlib import Path

from .common import BACKEND, UI, Finding, grep, iter_files, rel

PY = [".py"]
TS = [".ts", ".tsx", ".js", ".jsx"]
# Real Django ORM *reads* only — a Django manager/related-manager query, NOT a
# plain dict .get(). This is the signal that repeats per-iteration in an N+1.
_DB_READ = re.compile(
    r"\.objects\.(filter|get|all|exclude|count|exists|first|last|values|values_list|annotate|aggregate)\b"
    r"|\.\w+\.all\(\)|\.\w+_set\.(all|filter|count)\b")
# only request/response hot paths — exclude tests, one-off ETL/setup/mgmt scripts
_HOTPATH = ("/api/", "/api_v2/", "/views/", "/query_engine/", "/query_definition/",
            "/processors/", "/cache/", "helpers.py", "authorization.py", "paginator.py")
_SKIP = ("/tests/", "/management/", "/etl/", "/data_dictionary/", "deprecated", "test_")


def _hot(path) -> bool:
    p = str(path).replace("\\", "/").lower()
    if any(s in p for s in _SKIP):
        return False
    return any(h in str(path).replace("\\", "/") for h in _HOTPATH)


def _nplus1():
    """Heuristic: a Django ORM read executed inside a for-loop body, on a
    request hot path. Scoped + read-only to keep false positives low."""
    out = []
    for f in iter_files([BACKEND / "chiron"], PY):
        if not _hot(f):
            continue
        try:
            lines = f.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)for\s+.+\sin\s+.+:", line)
            if not m:
                continue
            indent = len(m.group(1))
            for j in range(i + 1, min(i + 15, len(lines))):
                body = lines[j]
                if body.strip() == "":
                    continue
                bindent = len(body) - len(body.lstrip())
                if bindent <= indent:
                    break
                if _DB_READ.search(body) and "objects.none" not in body:
                    out.append(Finding("medium", "n+1-query", "Django ORM read inside a loop (possible N+1)",
                                       f"{rel(f)}:{j + 1}", body.strip()[:150],
                                       "Move the query out of the loop or use select_related/prefetch_related.",
                                       check="n+1"))
                    break
    return out


def _pagination():
    out = []
    for f, ln, line in grep([BACKEND / "chiron"], PY, r'(page_size|PAGE_SIZE|max_page_size)\s*=\s*(\d{3,})'):
        m = re.search(r'=\s*(\d{3,})', line)
        if m and int(m.group(1)) >= 500:
            out.append(Finding("medium", "payload", "Large pagination default",
                               f"{rel(f)}:{ln}", line[:150],
                               "Lower the default/max page size; large pages mean heavy payloads + slow serialization.",
                               check="pagination"))
    return out


def _lodash():
    out = []
    for f, ln, line in grep([UI / "src"], TS, r'''from\s+["']lodash["']|require\(["']lodash["']\)'''):
        out.append(Finding("low", "bundle", "Full lodash imported (bundle bloat)",
                           f"{rel(f)}:{ln}", line[:150],
                           "Import per-method (lodash/get) or use lodash-es so tree-shaking drops the rest.",
                           check="lodash"))
    return out


def _dead_code():
    out = []
    # deprecated / uninvokable files
    for f in iter_files([BACKEND / "chiron"], PY):
        name = f.name
        if "DEPRECATED" in name.upper() or name.startswith("_chiron"):
            out.append(Finding("low", "dead-code", "Dead/uninvokable file shipped",
                               rel(f), name, "Remove or wire it in; dead code is maintenance drag.", check="dead-file"))
    # commented-out url routes
    for f, ln, line in grep([BACKEND / "chiron"], PY, r'^\s*#\s*(path|re_path|url|router\.register)\('):
        if "urls.py" in str(f) or "url" in str(f).lower():
            out.append(Finding("low", "dead-code", "Commented-out URL route",
                               f"{rel(f)}:{ln}", line[:150],
                               "Delete dead route comments; keep routing readable.", check="dead-route"))
    return out


def _duplication():
    out = []
    hits = list(grep([BACKEND / "chiron" / "models"], PY, r'class\s+TimeStampedModel\b'))
    if len(hits) > 1:
        locs = ", ".join(f"{rel(f)}:{ln}" for f, ln, _ in hits)
        out.append(Finding("low", "duplication", f"TimeStampedModel defined {len(hits)} times",
                           locs, "Identical abstract base duplicated across model files.",
                           "Define it once in a shared module and import it.", check="dup-model"))
    return out


def _caching():
    out = []
    for f, ln, line in grep([BACKEND / "test_project"], PY, r'CHIRON_USE_CACHES\s*=\s*False'):
        out.append(Finding("low", "caching", "Concept/stat caching disabled",
                           f"{rel(f)}:{ln}", line[:150],
                           "With caches off, concept stats & cohort counts recompute every request; enable + invalidate.",
                           check="caching"))
    return out


def run(base_url: str = "") -> list[Finding]:
    findings = []
    findings += _nplus1()
    findings += _pagination()
    findings += _lodash()
    findings += _dead_code()
    findings += _duplication()
    findings += _caching()
    return findings
