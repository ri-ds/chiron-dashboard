#!/usr/bin/env python3
"""UI/API checker for live RDCRN / Chiron pages — drives a real browser.

Companion to checker.py (which does authenticated API GETs). This one checks the
*pages*: are they up, do they render, do they still behave when you interact with
them. Every check here runs with **no credentials at all**, which is the point —
it monitors the parts of the estate you can reach from outside, including the login
page itself.

What it verifies per target:
  · HTTP status and where the redirect chain actually lands
  · page title
  · wall-clock load time
  · JS errors and console errors raised while loading
  · presence of expected elements
  · real interactions — typing, clicking — and their expected effect

Checks are declarative (see CHECKS below, or supply --config with the same shape),
so adding a page or an assertion needs no new code.

Output: readable to stdout, plus machine-readable JSON for the dashboard to ingest.

Exit codes: 0 all passed · 3 one or more failed · 1 usage/internal error.

    ./.venv/bin/python ui_check.py
    ./.venv/bin/python ui_check.py --only login-idp-search --headed
    ./.venv/bin/python ui_check.py --json results/ui_check.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
import sso_session as _sso

# Whichever site was signed into on the Login tab, or CATALOG_BASE_URL. Never a
# hardcoded deployment. NOTE: the CHECKS below still assert RDCRN-specific hosts
# (www.rarediseasesnetwork.org, shib.rarediseasesnetwork.org); they describe that
# deployment's public pages and are not portable to another site as they stand.
CATALOG = _sso.load_site()

NAV_TIMEOUT_MS = int(os.environ.get("UI_NAV_TIMEOUT_MS", "45000"))
STEP_TIMEOUT_MS = int(os.environ.get("UI_STEP_TIMEOUT_MS", "25000"))

# ── The checks ────────────────────────────────────────────────────────────────
# Each entry: name, url, optional expect{...}, optional steps[...].
# expect keys: status, final_url_contains, title, title_contains, selector,
#              max_load_ms, allow_console_errors
# step actions: wait_for, type, fill, click, expect_text, expect_min_count, wait_ms
CHECKS = [
    {
        "name": "rdcrn-public-site",
        "why": "The public RDCRN site should serve without any SSO involvement.",
        "url": "https://www.rarediseasesnetwork.org/",
        "expect": {
            "status": 200,
            "final_url_contains": "rarediseasesnetwork.org",
            "max_load_ms": 15000,
            # Third-party analytics on this page log console noise; not our failure.
            "allow_console_errors": True,
        },
    },
    {
        "name": "catalog-auth-wall",
        "why": ("The catalog must send anonymous visitors into SSO. If this ever "
                "renders the app instead, the gate has failed open."),
        "url": CATALOG + "/",
        "expect": {
            "status": 200,
            "final_url_contains": "shib.rarediseasesnetwork.org",
            "title_contains": "Login",
            "allow_console_errors": True,
        },
    },
    {
        "name": "catalog-api-guarded",
        "why": ("The API must refuse anonymous callers outright with 401 rather than "
                "redirecting — a 200 here would mean data is exposed."),
        "url": CATALOG + "/api/version/",
        "expect": {"status": 401, "allow_console_errors": True},
    },
    {
        "name": "login-idp-search",
        "why": ("The real interaction test: the login page's institution picker must "
                "load the federation feed and filter it as a user types."),
        "url": CATALOG + "/",
        "expect": {"title_contains": "Login", "allow_console_errors": True},
        "steps": [
            {"action": "wait_for", "selector": "#idpSelectInput"},
            # The widget fetches a 6000+ entry discovery feed before it can filter.
            {"action": "wait_ms", "ms": 2500},
            {"action": "click", "selector": "#idpSelectInput"},
            {"action": "type", "selector": "#idpSelectInput", "text": "Cincinnati",
             "delay": 80},
            {"action": "wait_ms", "ms": 1500},
            # `:visible` matters — the widget leaves hidden leftover rows in the DOM.
            {"action": "expect_min_count", "selector": "li[id^=IdPSelectOption]:visible",
             "min": 1, "note": "typing must filter the federation list"},
            {"action": "expect_text", "selector": "li[id^=IdPSelectOption]:visible",
             "contains": "Cincinnati Children's Hospital Medical Center",
             "note": "CCHMC must be reachable as an identity provider"},
            # Now prove the filter discriminates rather than always showing rows.
            {"action": "fill", "selector": "#idpSelectInput", "text": ""},
            {"action": "type", "selector": "#idpSelectInput", "text": "zzzzqqqq",
             "delay": 60},
            {"action": "wait_ms", "ms": 1500},
            {"action": "expect_max_count", "selector": "li[id^=IdPSelectOption]:visible",
             "max": 0, "note": "a nonsense query must surface no institutions"},
        ],
    },
]


class StepFailure(Exception):
    """An assertion inside a check's steps did not hold."""


# ── Step handlers ─────────────────────────────────────────────────────────────

def _step_wait_for(page, s):
    page.wait_for_selector(s["selector"], timeout=s.get("timeout", STEP_TIMEOUT_MS))
    return f"element present: {s['selector']}"


def _step_wait_ms(page, s):
    page.wait_for_timeout(s["ms"])
    return f"waited {s['ms']}ms"


def _step_click(page, s):
    page.click(s["selector"], timeout=s.get("timeout", STEP_TIMEOUT_MS))
    return f"clicked {s['selector']}"


def _step_type(page, s):
    # Real keystrokes, so JS keyup handlers fire the way they do for a person.
    page.type(s["selector"], s["text"], delay=s.get("delay", 60),
              timeout=s.get("timeout", STEP_TIMEOUT_MS))
    return f"typed {s['text']!r} into {s['selector']}"


def _step_fill(page, s):
    page.fill(s["selector"], s["text"], timeout=s.get("timeout", STEP_TIMEOUT_MS))
    return f"filled {s['selector']}"


def _step_expect_text(page, s):
    """Pass if ANY element matching the selector contains the text.

    Matching across all elements rather than just the first is what you almost always
    mean for a list of results — asserting on .first would only ever see one row.
    """
    want = s["contains"].lower()
    loc = page.locator(s["selector"])
    try:
        n = loc.count()
    except Exception as e:
        raise StepFailure(f"could not query {s['selector']}: {type(e).__name__}") from e
    if n == 0:
        raise StepFailure(f"{s['selector']} matched no elements")

    for i in range(n):
        try:
            got = loc.nth(i).inner_text(timeout=5000)
        except Exception:
            continue
        if want in (got or "").lower():
            return f"found {s['contains']!r} in {s['selector']} (match {i + 1} of {n})"
    raise StepFailure(
        f"none of the {n} element(s) matching {s['selector']} contain {s['contains']!r}")


def _step_expect_min_count(page, s):
    n = page.locator(s["selector"]).count()
    if n < s["min"]:
        raise StepFailure(f"{s['selector']} matched {n}, expected >= {s['min']}")
    return f"{s['selector']} matched {n} (>= {s['min']})"


def _step_expect_max_count(page, s):
    """Upper bound — how you assert that something is *absent* or filtered away.

    Pair with a `:visible` selector. The IdP widget, for one, leaves hidden leftover
    <li> rows in the DOM after a non-matching search, so a raw count would happily
    report 8 "results" for a nonsense query.
    """
    n = page.locator(s["selector"]).count()
    if n > s["max"]:
        raise StepFailure(f"{s['selector']} matched {n}, expected <= {s['max']}")
    return f"{s['selector']} matched {n} (<= {s['max']})"


STEPS = {
    "wait_for": _step_wait_for,
    "wait_ms": _step_wait_ms,
    "click": _step_click,
    "type": _step_type,
    "fill": _step_fill,
    "expect_text": _step_expect_text,
    "expect_min_count": _step_expect_min_count,
    "expect_max_count": _step_expect_max_count,
}


# ── Running a check ───────────────────────────────────────────────────────────

def run_check(context, spec: dict) -> dict:
    """Execute one check. Never raises — failures are recorded in the result."""
    result = {
        "name": spec["name"],
        "url": spec["url"],
        "why": spec.get("why", ""),
        "passed": False,
        "failures": [],
        "steps": [],
        "console_errors": [],
        "js_errors": [],
        "status": None,
        "final_url": None,
        "title": None,
        "load_ms": None,
    }
    expect = spec.get("expect", {})

    page = context.new_page()
    page.on("console",
            lambda m: m.type == "error" and result["console_errors"].append(m.text[:200]))
    page.on("pageerror", lambda e: result["js_errors"].append(str(e)[:200]))

    started = time.perf_counter()
    try:
        resp = page.goto(spec["url"], wait_until="load", timeout=NAV_TIMEOUT_MS)
        result["load_ms"] = int((time.perf_counter() - started) * 1000)
        result["status"] = resp.status if resp else None
        result["final_url"] = page.url
        try:
            result["title"] = page.title()
        except Exception:
            result["title"] = None
    except Exception as e:
        result["load_ms"] = int((time.perf_counter() - started) * 1000)
        result["failures"].append(f"navigation failed: {type(e).__name__}: {str(e)[:120]}")
        page.close()
        return result

    # Page-level expectations.
    if "status" in expect and result["status"] != expect["status"]:
        result["failures"].append(
            f"status {result['status']}, expected {expect['status']}")
    if "final_url_contains" in expect and \
            expect["final_url_contains"] not in (result["final_url"] or ""):
        result["failures"].append(
            f"landed {(result['final_url'] or '')[:70]}, "
            f"expected it to contain {expect['final_url_contains']!r}")
    if "title" in expect and (result["title"] or "") != expect["title"]:
        result["failures"].append(f"title {result['title']!r}, expected {expect['title']!r}")
    if "title_contains" in expect and \
            expect["title_contains"].lower() not in (result["title"] or "").lower():
        result["failures"].append(
            f"title {result['title']!r} does not contain {expect['title_contains']!r}")
    if "selector" in expect and page.locator(expect["selector"]).count() == 0:
        result["failures"].append(f"missing expected element {expect['selector']}")
    if "max_load_ms" in expect and result["load_ms"] > expect["max_load_ms"]:
        result["failures"].append(
            f"load took {result['load_ms']}ms, budget {expect['max_load_ms']}ms")

    # Interaction steps — stop at the first failure, since later steps assume it.
    for s in spec.get("steps", []):
        handler = STEPS.get(s["action"])
        if handler is None:
            result["failures"].append(f"unknown step action {s['action']!r}")
            break
        try:
            detail = handler(page, s)
            result["steps"].append({"action": s["action"], "ok": True, "detail": detail})
        except StepFailure as e:
            note = f" ({s['note']})" if s.get("note") else ""
            result["steps"].append({"action": s["action"], "ok": False, "detail": str(e)})
            result["failures"].append(f"{s['action']}: {e}{note}")
            break
        except Exception as e:
            result["steps"].append({"action": s["action"], "ok": False,
                                    "detail": f"{type(e).__name__}: {str(e)[:120]}"})
            result["failures"].append(f"{s['action']} errored: {type(e).__name__}")
            break

    if result["js_errors"]:
        result["failures"].append(f"{len(result['js_errors'])} uncaught JS error(s)")
    if result["console_errors"] and not expect.get("allow_console_errors"):
        result["failures"].append(f"{len(result['console_errors'])} console error(s)")

    result["passed"] = not result["failures"]
    page.close()
    return result


def print_result(r: dict) -> None:
    mark = "PASS" if r["passed"] else "FAIL"
    print(f"[{mark}] {r['name']}")
    print(f"       {r['url']}")
    bits = []
    if r["status"] is not None:
        bits.append(f"HTTP {r['status']}")
    if r["load_ms"] is not None:
        bits.append(f"{r['load_ms']}ms")
    if r["title"]:
        bits.append(f"title={r['title']!r}")
    if bits:
        print("       " + "  ".join(bits))
    if r["final_url"] and r["final_url"] != r["url"]:
        print(f"       landed {r['final_url'][:96]}")
    for s in r["steps"]:
        print(f"         {'✓' if s['ok'] else '✗'} {s['detail']}")
    for f in r["failures"]:
        print(f"       ! {f}")
    if r["console_errors"]:
        print(f"       ({len(r['console_errors'])} console error(s), not counted here)"
              if r["passed"] else "")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", metavar="NAME", action="append",
                    help="run only this check (repeatable)")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser window (useful for watching a failure)")
    ap.add_argument("--json", metavar="PATH", default=os.path.join(HERE, "results",
                                                                  "ui_check.json"),
                    help="write machine-readable results here")
    ap.add_argument("--config", metavar="PATH",
                    help="JSON file of checks, same shape as the built-in CHECKS")
    ap.add_argument("--html", metavar="PATH", nargs="?",
                    const=os.path.join(HERE, "results", "report.html"),
                    help="also write a self-contained HTML report "
                         "(default: results/report.html)")
    ap.add_argument("--html-fragment", action="store_true",
                    help="with --html, emit style+markup only, for embedding")
    args = ap.parse_args()

    checks = CHECKS
    if args.config:
        try:
            with open(args.config, encoding="utf-8") as f:
                checks = json.load(f)
        except Exception as e:
            print(f"! could not read {args.config}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1
    if args.only:
        wanted = set(args.only)
        checks = [c for c in checks if c["name"] in wanted]
        missing = wanted - {c["name"] for c in checks}
        if missing:
            print(f"! no such check(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
    if not checks:
        print("! nothing to run", file=sys.stderr)
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. See requirements.txt:\n"
              "  ./.venv/bin/pip install -r requirements.txt\n"
              "  ./.venv/bin/playwright install chromium", file=sys.stderr)
        return 1

    started = datetime.now(timezone.utc)
    print(f"UI/API checks — {len(checks)} target(s), no credentials used")
    print(f"{started.isoformat(timespec='seconds')}\n")

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=False,
        )
        context.set_default_timeout(STEP_TIMEOUT_MS)
        for spec in checks:
            r = run_check(context, spec)
            results.append(r)
            print_result(r)
        browser.close()

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    print(f"{passed}/{len(results)} passed" + (f", {failed} FAILED" if failed else ""))

    payload = {
        "tool": "ui_check",
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_base": CATALOG,
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    try:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"JSON: {args.json}")
    except OSError as e:
        print(f"! could not write {args.json}: {e}", file=sys.stderr)

    if args.html:
        try:
            import report_html

            out = report_html.render(payload, fragment=args.html_fragment)
            os.makedirs(os.path.dirname(os.path.abspath(args.html)), exist_ok=True)
            with open(args.html, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"HTML: {args.html}")
        except Exception as e:
            print(f"! could not write {args.html}: {type(e).__name__}: {e}",
                  file=sys.stderr)

    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
