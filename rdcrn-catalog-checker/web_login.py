#!/usr/bin/env python3
"""Sign in to an RDCRN site, driven by the dashboard's Login tab.

Runs as a short-lived subprocess of the dashboard. The credentials arrive as one
JSON object on **stdin** — never as command-line arguments (which are visible in
`ps`), never as environment variables (which leak into child processes and crash
dumps), and never through the dashboard's job-log pipe (which is written to disk).
They live in local variables for the few seconds it takes to type them into the
identity provider's own form, and nothing about them is written to the status file.

Progress goes to --status as JSON, so the web page can show where the sign-on has
got to — which matters most while it is waiting for you to approve the Duo push.

    echo '{"url": "...", "username": "...", "password": "..."}' \
        | python web_login.py --status /tmp/login.json

Exit codes: 0 signed in · 2 rejected or timed out · 3 the flow broke · 1 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import sso_session as S

# The user-visible sign-on sequence. `key` is what the status file reports; the
# page turns these into a stepper, so the wording is what a person reads.
STEPS = [
    ("open", "Opening the site"),
    ("idp", "Choosing Cincinnati Children's"),
    ("credentials", "Signing in"),
    ("duo", "Approving with Duo"),
    ("saml", "Completing sign-on"),
    ("done", "Signed in"),
]

# Chiron's Shibboleth-protected entry point. Loading the site ROOT proves nothing:
# both deployments serve a public home page, so a bare origin renders fine while
# completely anonymous. This is the path used to actually start a sign-on.
LOGIN_PATH = os.environ.get("CATALOG_LOGIN_PATH", "/login/")

STATUS_PATH = None
_state = {
    "state": "starting",
    "step": "open",
    "message": "",
    "url": "",
    "site": "",
    "user": None,
    "error": "",
    "session": "absent",
    "updated": "",
}


def _emit(**kw) -> None:
    """Update the status file. Never called with anything credential-derived."""
    _state.update(kw)
    _state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not STATUS_PATH:
        return
    try:
        os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
        tmp = STATUS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2)
        os.replace(tmp, STATUS_PATH)  # atomic, so a poll never sees a half-write
    except OSError:
        pass


def _fail(step: str, message: str, code: int) -> int:
    _emit(state="error", step=step, message=message, error=message)
    print(f"! {message}", file=sys.stderr)
    return code


def main() -> int:
    global STATUS_PATH
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", required=True, help="where to write progress JSON")
    ap.add_argument("--timeout", type=int, default=300,
                    help="seconds to wait for the whole sign-on, Duo included")
    args = ap.parse_args()
    STATUS_PATH = os.path.abspath(args.status)

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return _fail("open", "Could not read the sign-in request.", 1)

    url = (payload.get("url") or "").strip()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    payload.clear()  # drop the only other reference to the password

    if not url or not username or not password:
        return _fail("open", "URL, username and password are all required.", 1)

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return _fail("open", "That does not look like a valid URL.", 1)
    origin = f"{parts.scheme}://{parts.netloc}"

    # sso_session's helpers resolve "are we back on the application yet?" against
    # its module-level BASE. Point it at whichever site is being signed into, so
    # the same code works for any RDCRN app rather than only the data catalog.
    S.BASE = origin

    _emit(state="running", step="open", url=url, message=f"Opening {origin}")
    deadline = time.time() + args.timeout

    sync_playwright = S._require_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="load", timeout=S.NAV_TIMEOUT_MS)

            # Landing on the application is not proof of a session. The old test was
            # URL-only, so a public home page read as "already signed in": the whole
            # sign-on was skipped and what got saved could not read a single dataset.
            # Ask the API instead, and when nobody is signed in, start the chain at
            # the protected path rather than wherever the typed URL happened to land.
            already = False
            if page.url.startswith(origin) and not S._looks_like_sso(page.url):
                already, _ = S._check_api(context)
            if not already and not S._looks_like_sso(page.url):
                page.goto(origin + LOGIN_PATH, wait_until="load",
                          timeout=S.NAV_TIMEOUT_MS)

            if already:
                _emit(step="saml", message="Already signed in — reusing the session.")
            else:
                _emit(step="idp", message="Choosing Cincinnati Children's")
                if not S._select_cchmc(page):
                    browser.close()
                    return _fail("idp", "Could not pick the institution on the "
                                        "discovery page.", 3)
                page.wait_for_load_state("load", timeout=S.NAV_TIMEOUT_MS)
                page.wait_for_timeout(1500)

                _emit(step="credentials", message="Signing in")
                form = None
                for candidate in S.IDP_FORMS:
                    if S._first_present(page, candidate["pass"], timeout_ms=6000):
                        form = candidate
                        break
                if form is None:
                    browser.close()
                    return _fail("credentials",
                                 "No password field found on the identity provider "
                                 "page.", 3)

                S._first_present(page, form["user"]).fill(username)
                S._first_present(page, form["pass"]).fill(password)
                password = ""          # used; drop it immediately
                del password           # and remove the name entirely

                submit = S._first_present(page, form["submit"])
                if submit is None:
                    browser.close()
                    return _fail("credentials", "No sign-in button found.", 3)
                submit.click()
                page.wait_for_load_state("load", timeout=S.NAV_TIMEOUT_MS)
                page.wait_for_timeout(2500)

                err = S._page_error_text(page)
                if err and any(m in page.url.lower() for m in ("idp", "login")):
                    browser.close()
                    return _fail("credentials",
                                 f"The identity provider rejected the sign-in: {err}",
                                 2)

                if any(m in page.url.lower() for m in S.DUO_HOST_MARKERS):
                    sent = S._duo_click(page, ("Send Me a Push", "Send me a Push",
                                               "Push"))
                    if not sent:
                        browser.close()
                        return _fail("duo", "Reached Duo but found no push button.", 3)
                    _emit(step="duo",
                          message="Duo push sent — approve it on your phone")
                    while time.time() < deadline:
                        page.wait_for_timeout(2000)
                        if not any(m in page.url.lower() for m in S.DUO_HOST_MARKERS):
                            break
                    else:
                        browser.close()
                        return _fail("duo", "Timed out waiting for the Duo approval.", 2)

                _emit(step="saml", message="Completing sign-on")
                if not S._await_application(page, deadline):
                    browser.close()
                    return _fail("saml", "Signed in, but never landed back on the "
                                         "site.", 3)

            # The session is only worth saving once it actually works, and the
            # authoritative test is whether the API names a signed-in user -- not
            # whether cookies exist. Anonymous browsing produces cookies too (a
            # load balancer plus an analytics tag is already three), so counting
            # them reported success for sessions that could not read one dataset.
            ok, detail = S._check_api(context)
            if not ok:
                # The SAML handoff can land on the public home page, which touches no
                # protected view and so never establishes the application session.
                # One trip through the protected path settles it.
                try:
                    page.goto(origin + LOGIN_PATH, wait_until="load",
                              timeout=S.NAV_TIMEOUT_MS)
                    S._await_application(page, deadline)
                except Exception:
                    pass
                ok, detail = S._check_api(context)
            if not ok:
                # Names only, never values -- and they are the whole diagnosis: a
                # shibsession cookie present means SSO worked and the application
                # session did not; absent means the chain never completed.
                jar = context.cookies(origin + "/")
                names = ", ".join(sorted({c["name"] for c in jar})) or "none"
                carrying = ", ".join(S.session_cookie_names(jar)) or "none"
                browser.close()
                return _fail("saml",
                             f"Reached the site, but the session is not authenticated "
                             f"({detail}). Cookies: {names}. Session-bearing: "
                             f"{carrying}. Nothing was saved.", 2)

            user = None
            try:
                r = context.request.get(origin + "/api/v2/auth/", timeout=20000)
                if r.status == 200:
                    user = ((r.json() or {}).get("user") or {}).get("username")
            except Exception:
                pass

            S._save_state(context)
            # Record WHICH site this session belongs to. Every other tool resolves
            # its target from here, so signing in is the act that re-points the
            # whole toolchain -- no environment variable, no code edit.
            S.set_site(origin)
            cookies = context.cookies(origin + "/")
            carrying = S.session_cookie_names(cookies)

            browser.close()
            _emit(state="done", step="done", session="live", user=user or username,
                  site=origin,
                  message=f"Signed in to {urlsplit(origin).netloc} - session saved "
                          f"({len(cookies)} cookies, {len(carrying)} carrying the "
                          f"session).")
            print(f"signed in; {len(cookies)} cookies; {detail[:80]}")
            return 0

        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass
            # Playwright errors carry a multi-line "Call log:" trace. The first line
            # is the actual cause; the rest is noise on a sign-in screen.
            first = str(e).split("\n", 1)[0].strip() or type(e).__name__
            if "ERR_NAME_NOT_RESOLVED" in str(e):
                first = "That site could not be reached — check the URL."
            elif "Timeout" in type(e).__name__:
                first = "The site took too long to respond."
            return _fail(_state.get("step", "open"), first[:200], 3)


if __name__ == "__main__":
    sys.exit(main())
