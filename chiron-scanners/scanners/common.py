"""Shared scanning primitives for the Chiron security + inefficiency scanners.

Both scanners are REAL and re-runnable: every run walks the actual source tree
(and, for a few checks, probes the live API) and reports what it finds *right
now*. Nothing is cached or read from a prior report.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

# workspace root = parent of chiron-scanners/
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "is4r-chiron-develop"
UI = ROOT / "is4r-chiron-ui-develop"

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

_EXCLUDE = ("/.venv/", "/venv/", "/node_modules/", "/__pycache__/", "/migrations/",
            "/.git/", "/dist/", "/build/", "/.pytest_cache/", ".egg-info", "/.ruff_cache/",
            "/static/", "/htmlcov/")


@dataclass
class Finding:
    severity: str
    category: str
    title: str
    location: str            # "relpath:line" or "live: <url>"
    detail: str
    fix: str
    check: str = ""          # the check id that produced it

    def as_dict(self):
        return asdict(self)


def _excluded(path: str) -> bool:
    p = path.replace(os.sep, "/")
    return any(x in p for x in _EXCLUDE)


def iter_files(roots, exts):
    """Yield Path for every file under roots with an allowed extension."""
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if _excluded(dirpath + "/"):
                dirnames[:] = []
                continue
            for fn in filenames:
                if exts and not fn.endswith(tuple(exts)):
                    continue
                full = Path(dirpath) / fn
                if _excluded(str(full)):
                    continue
                yield full


def rel(path: Path) -> str:
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def grep(roots, exts, pattern, flags=0):
    """Yield (path, lineno, line) for every regex match. Real file scan."""
    rx = re.compile(pattern, flags)
    for f in iter_files(roots, exts):
        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                yield f, i, line.strip()


def http_probe(url: str, timeout=3):
    """Best-effort GET. Returns (status, headers_dict, body_snippet) or None."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(4000).decode("utf-8", "replace")
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body
    except Exception:
        return None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def summarize(findings):
    counts = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


def write_results(tool: str, findings, out_path: Path, meta=None):
    findings = sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.category, f.location))
    payload = {
        "tool": tool,
        "generated": now(),
        "summary": summarize(findings),
        "n_findings": len(findings),
        "meta": meta or {},
        "findings": [f.as_dict() for f in findings],
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, indent=2))
    return payload
