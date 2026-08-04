"""Vulnerability scanner — runs live every time.

Three real check families, all executed on each run:
  1. STATIC  — regex over the actual backend + UI source for dangerous patterns.
  2. DEPS    — parse requirements/*.txt + package.json and flag risky version floors.
  3. LIVE    — unauthenticated probes of the running API (security headers, DEBUG
               tracebacks, whether protected endpoints actually reject anon access).
Nothing is read from a prior report.
"""

from __future__ import annotations

import re
from pathlib import Path

from .common import BACKEND, UI, Finding, grep, http_probe, rel

PY = [".py"]
TS = [".ts", ".tsx", ".js", ".jsx"]


def _static_backend():
    out = []
    checks = [
        # (pattern, flags, severity, category, title, fix)
        (r'SECRET_KEY\s*=\s*["\'][^"\']+["\']', 0, "high", "secrets",
         "Hardcoded Django SECRET_KEY", "Load SECRET_KEY from an environment variable / secrets manager, not a literal."),
        (r'^\s*DEBUG\s*=\s*True', re.M, "medium", "config",
         "DEBUG = True", "Ensure DEBUG=False in any non-local settings; DEBUG leaks tracebacks + data."),
        (r'\beval\(|\bexec\(', 0, "high", "code-exec",
         "Use of eval()/exec()", "Avoid eval/exec; use explicit parsing (ast.literal_eval, dispatch dicts)."),
        (r'pickle\.loads?\(', 0, "high", "deserialization",
         "Insecure deserialization (pickle)", "Never unpickle untrusted data; use JSON."),
        (r'yaml\.load\((?![^)]*Loader)', 0, "medium", "deserialization",
         "yaml.load without SafeLoader", "Use yaml.safe_load()."),
        (r'shell\s*=\s*True|os\.system\(', 0, "medium", "command-injection",
         "Shell execution (shell=True / os.system)", "Pass an argv list without shell=True; never interpolate input."),
        (r'\.execute\(\s*f["\']|\.execute\([^)]*%[^)]*\)|text\(\s*f["\']', 0, "high", "sql-injection",
         "SQL built by string interpolation", "Use bound parameters / SQLAlchemy text(:param); never f-string SQL."),
        (r'^\s*ALLOWED_HOSTS\s*=\s*\[\s*\]', re.M, "medium", "config",
         "Empty ALLOWED_HOSTS", "Set ALLOWED_HOSTS explicitly for any deployed instance."),
    ]
    for pat, flags, sev, cat, title, fix in checks:
        for f, ln, line in grep([BACKEND / "chiron", BACKEND / "test_project"], PY, pat, flags):
            out.append(Finding(sev, cat, title, f"{rel(f)}:{ln}", line[:160], fix, check=cat))
    return out


def _static_ui():
    out = []
    for f, ln, line in grep([UI / "src"], TS, r'dangerouslySetInnerHTML'):
        out.append(Finding("high", "xss", "Raw HTML injection via dangerouslySetInnerHTML",
                           f"{rel(f)}:{ln}", line[:160],
                           "Sanitise HTML (e.g. DOMPurify) before rendering, or render as text.", check="xss"))
    for f, ln, line in grep([UI], [".conf"], r'Access-Control-Allow-Origin.*\*'):
        out.append(Finding("low", "cors", "Permissive CORS (Access-Control-Allow-Origin: *)",
                           f"{rel(f)}:{ln}", line[:160],
                           "Restrict allowed origins to the known frontend host.", check="cors"))
    # nginx security headers present?
    ngx = UI / "nginx.conf"
    if ngx.exists():
        text = ngx.read_text(errors="replace")
        for hdr, sev in [("Strict-Transport-Security", "medium"), ("X-Frame-Options", "low"),
                         ("X-Content-Type-Options", "low"), ("Content-Security-Policy", "low")]:
            if hdr.lower() not in text.lower():
                out.append(Finding(sev, "headers", f"nginx: no {hdr} header",
                                   rel(ngx), f"{hdr} not configured in nginx.conf",
                                   f"Add `add_header {hdr} ...;` to nginx.conf.", check="headers"))
    return out


# lower-bound version floors considered risky (min_safe, severity, note)
_DEP_RULES = {
    "django": ("4.2", "medium", "3.2 is end-of-life; floor allows unpatched releases."),
    "requests": ("2.32.0", "low", "older requests have credential-leak CVEs (e.g. CVE-2024-35195)."),
    "djangorestframework": ("3.15.2", "low", "older DRF browsable API had reflected-XSS CVEs."),
    "lodash": ("4.17.21", "low", "older lodash had prototype-pollution CVEs."),
    "axios": ("1.7.4", "medium", "older axios had SSRF/redirect CVEs."),
}
_VER = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def _floor(constraint):
    m = re.search(r">=\s*([\d.]+)", constraint) or re.search(r"[\^~]?\s*([\d.]+)", constraint)
    return m.group(1) if m else None


def _ver_tuple(v):
    m = _VER.search(v or "")
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def _deps():
    out = []
    # python requirements
    for req in (BACKEND / "requirements").glob("*.txt") if (BACKEND / "requirements").exists() else []:
        for i, line in enumerate(req.read_text(errors="replace").splitlines(), 1):
            s = line.strip().lower()
            if not s or s.startswith("#"):
                continue
            name = re.split(r"[<>=!~ \[]", s, 1)[0]
            if name in _DEP_RULES:
                floor = _floor(s)
                min_safe, sev, note = _DEP_RULES[name]
                if floor is None or _ver_tuple(floor) < _ver_tuple(min_safe):
                    out.append(Finding(sev, "dependency", f"{name}: version floor allows vulnerable releases",
                                       f"{rel(req)}:{i}", f"{line.strip()}  (safe floor >= {min_safe})",
                                       f"Raise the lower bound to >= {min_safe}. {note}", check="dependency"))
    # package.json
    pkg = UI / "package.json"
    if pkg.exists():
        import json
        try:
            data = json.loads(pkg.read_text())
        except Exception:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for name, constraint in deps.items():
            if name in _DEP_RULES:
                floor = _floor(constraint)
                min_safe, sev, note = _DEP_RULES[name]
                if floor is None or _ver_tuple(floor) < _ver_tuple(min_safe):
                    out.append(Finding(sev, "dependency", f"{name}: version floor allows vulnerable releases",
                                       f"{rel(pkg)} ({name} {constraint})", f"safe floor >= {min_safe}",
                                       f"Raise the constraint to >= {min_safe}. {note}", check="dependency"))
    return out


def _live(base_url):
    out = []
    probe = http_probe(f"{base_url}/api/version/")
    if probe is None:
        out.append(Finding("info", "live", "Live checks skipped — API not reachable",
                           f"live: {base_url}", "Could not connect to the running API.",
                           "Start the Chiron API to include live security checks.", check="live"))
        return out
    status, headers, body = probe
    for hdr, sev in [("strict-transport-security", "medium"), ("x-frame-options", "low"),
                     ("x-content-type-options", "low"), ("content-security-policy", "low")]:
        if hdr not in headers:
            out.append(Finding(sev, "headers", f"Live: response missing {hdr} header",
                               f"live: {base_url}/api/version/", f"{hdr} not sent by the server",
                               f"Send the {hdr} header (via middleware / nginx).", check="live-headers"))
    # DEBUG traceback leak
    err = http_probe(f"{base_url}/api/v2/__nonexistent_scanner_probe__/")
    if err and err[2] and ("Traceback" in err[2] or "django.core.exceptions" in err[2] or "Exception at /" in err[2]):
        out.append(Finding("high", "info-leak", "Live: server leaks Django tracebacks (DEBUG on)",
                           f"live: {base_url}", "A bad path returned a Django debug traceback in the body.",
                           "Set DEBUG=False in production so errors don't leak stack traces + data.", check="live-debug"))
    # protected endpoint must reject anonymous access
    anon = http_probe(f"{base_url}/api/v2/dataset/")
    if anon and anon[0] == 200:
        out.append(Finding("high", "authz", "Live: protected endpoint served to unauthenticated caller",
                           f"live: {base_url}/api/v2/dataset/", "GET without credentials returned HTTP 200.",
                           "Require authentication on dataset endpoints.", check="live-authz"))
    return out


def run(base_url: str) -> list[Finding]:
    findings = []
    findings += _static_backend()
    findings += _static_ui()
    findings += _deps()
    findings += _live(base_url)
    return findings
