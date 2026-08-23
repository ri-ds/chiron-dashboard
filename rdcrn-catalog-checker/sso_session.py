#!/usr/bin/env python3
"""RDCRN SSO session manager — one interactive login, then silent re-auth.

Companion to checker.py. checker.py deliberately does not log in; this module is
how a live session reaches it without anyone pasting cookies by hand.

  login    You log in once in a real browser window (any IdP the RDCRN discovery
           page offers — Google, your institution, Login.gov). Your password and
           MFA code go into Google's/your IdP's own page. This script never reads,
           types, or stores them; it only saves the resulting cookies.
  refresh  Headless. Replays the saved cookies. If the short-lived Shibboleth SP
           session has expired but the upstream IdP session is still good, the
           SAML/OIDC redirect chain completes *silently* — no password, no MFA —
           and we get a fresh _shibsession_ cookie. This is what makes unattended
           periodic monitoring possible.
  status   Is the saved session still usable? Names and expiries only, no values.

Why a browser and not requests: the silent re-SSO hop runs through Google's OIDC
endpoints, which are JS- and bot-check-sensitive. A real browser engine replaying
a real profile is the only version of this that reliably survives.

Secrets: the state file holds live session cookies — it is equivalent to your
logged-in browser. Written 0600 into .session/ (gitignored). Cookie *values* are
never printed by this module.

Exit codes: 0 session live · 2 needs interactive login · 1 usage/other error.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("SSO_STATE_FILE") or os.path.join(HERE, ".session", "state.json")

# The site under test is NOT hardcoded here. It is whichever deployment was last
# signed into on the dashboard's Login tab, recorded next to the session it belongs
# to. Resolution order: CATALOG_BASE_URL (explicit override) -> the saved site ->
# nothing. "Nothing" is a hard stop rather than a fallback to some default
# deployment: a tool silently pointed at the wrong host produces results that look
# authoritative and are entirely about a different system.
SITE_FILE = os.environ.get("SSO_SITE_FILE") or os.path.join(
    os.path.dirname(STATE_FILE), "site.json")

# Distinguishes anonymous from signed-in (see _check_api). 200 either way.
AUTH_PATH = "/api/v2/auth/"
# Older fallback: 200+JSON when authenticated, 401/redirect when not.
PROBE_PATH = "/api/version/"

# Cookie names that actually carry an authenticated session. A saved state file
# holding none of these is an anonymous browse, however many cookies it has --
# a load balancer and an analytics tag alone will produce three.
SESSION_COOKIE_MARKERS = ("shibsession", "sessionid", "mod_auth_openidc_session",
                          "_saml", "mellon")


def _origin(url: str) -> str:
    """Scheme+host only; every caller appends its own path."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def load_site() -> str:
    """The site every tool should target, or "" if none has been chosen yet."""
    env = _origin(os.environ.get("CATALOG_BASE_URL", ""))
    if env:
        return env
    try:
        with open(SITE_FILE, encoding="utf-8") as f:
            return _origin((json.load(f) or {}).get("site", ""))
    except (OSError, ValueError):
        return ""


def set_site(url: str) -> str:
    """Record the site a successful sign-in was for; returns the stored origin.

    Written beside the session state -- which docker-compose already mounts from
    the host -- so the host CLI and the dashboard container resolve the same
    target with no environment variable threaded through both.
    """
    origin = _origin(url)
    if not origin:
        raise ValueError(f"not a usable site URL: {url!r}")
    os.makedirs(os.path.dirname(SITE_FILE), exist_ok=True)
    os.chmod(os.path.dirname(SITE_FILE), stat.S_IRWXU)  # 0700
    tmp = SITE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"site": origin,
                   "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                  f, indent=2)
    os.replace(tmp, SITE_FILE)  # atomic: a concurrent reader never sees a half-write
    global BASE
    BASE = origin
    return origin


def require_site() -> str:
    """BASE, or exit with the one instruction that fixes it."""
    global BASE
    site = BASE or load_site()
    if not site:
        sys.exit("No site configured. Sign in on the dashboard's Login tab (or set "
                 "CATALOG_BASE_URL) so the tools know which deployment to check.")
    BASE = site
    return site


def session_cookie_names(cookies) -> list:
    """Which of these cookies, if any, are authentication-bearing."""
    return [c.get("name", "") for c in (cookies or [])
            if any(m in (c.get("name", "") or "").lower()
                   for m in SESSION_COOKIE_MARKERS)]


BASE = load_site()

# Hostnames that mean "we are being asked to log in", not "we are in".
SSO_HOST_MARKERS = ("shib", "idp", "accounts.google.com", "login.gov", "satosa", "auth.ncats")

LOGIN_TIMEOUT_S = int(os.environ.get("SSO_LOGIN_TIMEOUT", "600"))
NAV_TIMEOUT_MS = int(os.environ.get("SSO_NAV_TIMEOUT_MS", "45000"))


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        sys.exit(
            "Playwright is not installed in this interpreter.\n"
            "  python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt\n"
            "  ./.venv/bin/playwright install chromium\n"
            "then run this script with ./.venv/bin/python"
        )
    from playwright.sync_api import sync_playwright

    return sync_playwright


def _save_state(context) -> None:
    """Persist cookies 0600. Directory is created private, too."""
    d = os.path.dirname(STATE_FILE)
    os.makedirs(d, exist_ok=True)
    os.chmod(d, stat.S_IRWXU)  # 0700
    context.storage_state(path=STATE_FILE)
    os.chmod(STATE_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _state_exists() -> bool:
    return os.path.isfile(STATE_FILE) and os.path.getsize(STATE_FILE) > 0


def _looks_like_sso(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in SSO_HOST_MARKERS)


def _drive_sso(page) -> str:
    """Navigate the real browser to the app root and let any pending SSO chain finish.

    This has to be a genuine navigation, not an HTTP fetch: the SAML and OIDC hops
    hand off through auto-submitting HTML forms that only fire when JavaScript runs.
    If the upstream IdP session is still valid this completes silently and lands us
    back on the app with a fresh SP session cookie. Returns the final URL.
    """
    try:
        page.goto(BASE + "/", wait_until="load", timeout=NAV_TIMEOUT_MS)
    except Exception as e:
        return f"about:error/{type(e).__name__}"
    try:
        # Let a JS auto-submit form fire and settle. Absence of quiet network is not
        # itself a failure, so a timeout here is ignored deliberately.
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    return page.url


def _check_api(context) -> tuple[bool, str]:
    """Ask the API directly, reusing the context's cookies. Returns (ok, detail).

    Uses the context's request API rather than a page navigation so the answer is the
    raw HTTP response — no browser rendering of the JSON to work around.
    """
    base = BASE or load_site()
    if not base:
        return False, "no site configured"
    try:
        resp = context.request.get(base + AUTH_PATH, timeout=NAV_TIMEOUT_MS)
    except Exception as e:
        return False, f"request failed: {type(e).__name__}"

    if _looks_like_sso(resp.url):
        return False, f"redirected to SSO ({resp.url.split('?')[0][:70]})"
    if resp.status == 404:
        return _check_version_api(context, base)   # deployment without v2 auth
    if resp.status in (401, 403):
        return False, f"HTTP {resp.status} from the Shibboleth SP"
    try:
        parsed = resp.json() or {}
    except Exception:
        return False, f"HTTP {resp.status} but body was not JSON (login page?)"

    # The decisive bit. Chiron answers this endpoint 200 whether or not anyone is
    # signed in, reporting {"user": null} when nobody is -- so a 2xx proves only
    # that the host is reachable. Treating that as proof of a session is what let
    # an anonymous browse be saved and reported as "signed in".
    user = parsed.get("user")
    if not user:
        return False, "reached the API anonymously (it reports no signed-in user)"
    who = user.get("username") or user.get("email") or "unknown"
    return True, f"signed in as {who}"


def _check_version_api(context, base: str) -> tuple[bool, str]:
    """Fallback for deployments that predate /api/v2/auth/."""
    try:
        resp = context.request.get(base + PROBE_PATH, timeout=NAV_TIMEOUT_MS)
    except Exception as e:
        return False, f"request failed: {type(e).__name__}"
    if _looks_like_sso(resp.url):
        return False, f"redirected to SSO ({resp.url.split('?')[0][:70]})"
    if resp.status in (401, 403):
        return False, f"HTTP {resp.status} from the Shibboleth SP"
    try:
        parsed = resp.json()
    except Exception:
        return False, f"HTTP {resp.status} but body was not JSON (login page?)"
    return True, json.dumps(parsed)[:160]


def _authenticated_body(page) -> tuple[bool, str]:
    """Complete any pending SSO, then report whether the API is readable."""
    _drive_sso(page)
    return _check_api(page.context)


def _cookie_header_for_catalog(context) -> str:
    """Build the Cookie header a browser would send to the catalog.

    Scoping to the catalog URL is what keeps upstream IdP cookies (Google, the hub)
    out of the handoff: checker.py only ever talks to the catalog, so a narrower
    header means less secret in flight.
    """
    base = BASE or load_site()
    if not base:
        return ""
    return "; ".join(f"{c['name']}={c['value']}" for c in context.cookies(base + "/"))


def _summarize_cookies(context) -> list[dict]:
    """Cookie metadata for humans — names, domains, expiry. Never values."""
    out = []
    for c in context.cookies():
        exp = c.get("expires", -1)
        if exp and exp > 0:
            when = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(timespec="minutes")
        else:
            when = "session"
        out.append({"name": c.get("name"), "domain": c.get("domain"), "expires": when})
    return out


def cmd_login(args) -> int:
    """Open a real browser and let the human authenticate. We only save cookies."""
    sync_playwright = _require_playwright()

    print(f"Target: {require_site()}")
    print("\nA browser window will open on the RDCRN login flow.")
    print("Pick your identity provider and sign in normally.")
    print("  · Google, your institution, or Login.gov — whichever you have access with.")
    print("  · Type your password and MFA code into that provider's own page.")
    print("  · This script does not read or store them; it saves only the session cookies.")
    print(f"\nWaiting up to {LOGIN_TIMEOUT_S // 60} minutes for you to finish. Ctrl-C to abort.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        # Reuse an existing session if one is present, so a partial re-login works.
        ctx_args = {"storage_state": STATE_FILE} if _state_exists() else {}
        context = browser.new_context(**ctx_args)
        page = context.new_page()
        try:
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception as e:
            print(f"! could not open {BASE}: {type(e).__name__}: {e}", file=sys.stderr)
            browser.close()
            return 1

        deadline = time.time() + LOGIN_TIMEOUT_S
        ok = False
        detail = "timed out"
        while time.time() < deadline:
            time.sleep(3)
            if page.is_closed():
                detail = "browser window was closed"
                break
            # Only probe once their tab is back on the application's own origin, and
            # do it in a separate tab so we never yank the page out from under them.
            # Testing "not an SSO host" by keyword is not enough: an institution can
            # route through a host no keyword matches, and probing mid-login would
            # start a second, competing SSO flow. Requiring the app's own origin is
            # the safe direction to be wrong in — at worst we wait a few more seconds.
            if not page.url.startswith(BASE):
                continue
            probe = context.new_page()
            try:
                ok, detail = _authenticated_body(probe)
            finally:
                probe.close()
            if ok:
                break

        if ok:
            _save_state(context)
            print(f"\nLogged in. {PROBE_PATH} -> {detail}")
            print(f"Session saved to {STATE_FILE} (0600).")
            print("\nFrom here on it is hands-off:")
            print("  ./.venv/bin/python monitor.py      # refresh + run the checks")
            browser.close()
            return 0

        print(f"\nDid not reach an authenticated state ({detail}).", file=sys.stderr)
        if not _looks_like_sso(page.url if not page.is_closed() else ""):
            print("If you did log in, the account may be authenticated but not yet "
                  "authorized for the catalog — that provisioning is an RDCRN admin step.",
                  file=sys.stderr)
        browser.close()
        return 2


# ── Terminal-driven login ─────────────────────────────────────────────────────
# You type your own credentials into your own terminal. They are held in local
# variables just long enough to enter them into the identity provider's form, are
# never written to disk, never logged, and never included in any output.

# Verified against the live page: CCHMC runs a stock Shibboleth IdP login form.
IDP_FORMS = [
    {"name": "shibboleth", "user": "#username, input[name=j_username]",
     "pass": "#password, input[name=j_password]",
     "submit": "button[name=_eventId_proceed], button[type=submit], input[type=submit]"},
    # Generic fallback, so another institution's IdP still has a chance of working.
    {"name": "generic", "user": "input[type=email], input[type=text]:visible",
     "pass": "input[type=password]",
     "submit": "button[type=submit], input[type=submit]"},
]

DUO_HOST_MARKERS = ("duosecurity.com", "duo.com", "/duo")
ERROR_MARKERS = ("incorrect", "invalid", "failed", "denied", "unable to log",
                 "credentials", "try again", "locked")


def _first_present(page, selectors: str, timeout_ms: int = 8000):
    """Return a locator for whichever comma-separated selector exists first."""
    for sel in [s.strip() for s in selectors.split(",")]:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc
        except Exception:
            continue
    return None


# Matched against the discovery widget's own option list rather than a hardcoded
# entityID, so a change in federation metadata does not need a code edit.
IDP_MATCH = ("cchmc", "cincinnati children")


def _select_cchmc(page) -> bool:
    """Choose the institution on the Shibboleth discovery page.

    Three routes, cheapest first: a recognised-network tile, then the full picker
    <select>, then the type-ahead. The <select> is the reliable one -- one exact
    option and one submit, with no autocomplete race to lose.
    """
    try:
        page.wait_for_selector("#idpSelect", state="attached", timeout=25000)
    except Exception:
        return False
    page.wait_for_timeout(2500)  # the widget loads a 6000+ entry federation feed

    # 1. A suggested tile, when the deployment offers one.
    #
    # Scoped to http(s) links inside the widget. The previous a[href*='cchmc'] was
    # unscoped and matched this page's support address, mailto:help-cloud@bmi.cchmc
    # .org -- clicking which navigates nowhere, so the sign-in then sat in
    # wait_for_load_state for the full 45s and reported "the site took too long to
    # respond" from the discovery page it had never actually left.
    tiles = page.locator("#idpSelect a[href^='http']")
    for i in range(min(tiles.count(), 40)):
        href = (tiles.nth(i).get_attribute("href") or "").lower()
        if any(m in href for m in IDP_MATCH):
            tiles.nth(i).click()
            return True

    # 2. The full picker.
    try:
        sel = page.locator("#idpSelectSelector")
        if sel.count():
            value = page.evaluate(
                """(markers) => {
                    const s = document.querySelector('#idpSelectSelector');
                    if (!s) return '';
                    const hit = [...s.options].find(o => markers.some(m =>
                        (o.value + ' ' + o.text).toLowerCase().includes(m)));
                    return hit ? hit.value : '';
                }""", list(IDP_MATCH))
            if value:
                sel.select_option(value)
                btn = page.locator("#idpSelectListButton")
                if btn.count():
                    btn.first.click()
                    return True
    except Exception:
        pass

    # 3. Type-ahead, as a last resort.
    try:
        page.fill("#idpSelectInput", "")
        page.type("#idpSelectInput", "Cincinnati Children", delay=60)
        page.wait_for_timeout(1500)
        opt = page.locator("li[id^=IdPSelectOption]:visible").first
        opt.wait_for(state="visible", timeout=8000)
        opt.click()
        page.wait_for_timeout(500)
        btn = page.locator("#idpSelectSelectButton")
        if btn.count():
            btn.first.click()
        return True
    except Exception:
        return False


def _page_error_text(page) -> str:
    """Any visible text that looks like a rejected-login message."""
    try:
        body = (page.inner_text("body", timeout=5000) or "").lower()
    except Exception:
        return ""
    for line in body.splitlines():
        line = line.strip()
        if 8 < len(line) < 200 and any(m in line for m in ERROR_MARKERS):
            return line
    return ""


def _duo_inventory(page) -> list[str]:
    """Every control Duo is currently showing, as readable labels.

    Duo's Universal Prompt changes its markup without notice, so when a step fails the
    useful thing is the actual list of controls rather than a guess about selectors.
    """
    try:
        return page.evaluate("""() => [...document.querySelectorAll(
            'button,a,input,[role=button]')]
            .filter(e => !!(e.offsetWidth||e.offsetHeight))
            .map(e => {
              const label = (e.getAttribute('aria-label') || e.value ||
                             e.textContent || e.placeholder || '').trim();
              return (e.tagName.toLowerCase() +
                      (e.type ? '[' + e.type + ']' : '') +
                      (e.name ? ' name=' + e.name : '') +
                      (label ? ' "' + label.slice(0, 48) + '"' : ''));
            }).slice(0, 30)""")
    except Exception:
        return []


def _duo_dump(page, why: str) -> None:
    """Save what Duo is showing, so the next attempt is informed rather than guessed."""
    d = os.path.join(HERE, "results")
    try:
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, "duo_debug.png"), full_page=True)
        with open(os.path.join(d, "duo_debug.txt"), "w", encoding="utf-8") as f:
            f.write(f"{why}\nurl: {page.url}\n\ncontrols:\n")
            for line in _duo_inventory(page):
                f.write(f"  {line}\n")
        print(f"  (saved what Duo is showing to {d}/duo_debug.png and .txt)")
    except Exception:
        pass


def _duo_click(page, names: tuple[str, ...], timeout_ms: int = 4000):
    """Click the first control whose visible text or label matches, case-insensitively."""
    for name in names:
        for finder in (lambda n: page.get_by_role("button", name=n),
                       lambda n: page.get_by_role("link", name=n),
                       lambda n: page.get_by_text(n)):
            try:
                el = finder(name)
                if el.count():
                    el.first.click(timeout=timeout_ms)
                    return name
            except Exception:
                continue
    return None


def _handle_duo(page, trust_device: bool, deadline: float, headed: bool) -> None:
    """Get through Duo from the terminal.

    Written against this tenant's actual prompt, which is Duo's classic one: plain
    submit buttons for "Send Me a Push" / "Call Me" / "Enter a Passcode", and a
    `dampen_choice` checkbox for "remember me". That is straightforward to drive
    headlessly — no window needed, you just approve on your phone.
    """
    print("\n  Duo two-factor step reached.")
    if headed:
        print("  Complete Duo in the browser window that is open.")
        _duo_wait(page, deadline)
        return

    if trust_device:
        # Duo's own "remember me" — the thing that lets later runs skip this entirely.
        try:
            box = page.locator("input[name=dampen_choice]")
            if box.count() and not box.first.is_checked():
                box.first.check(timeout=3000)
                print("  ticked Duo's 'remember me' box")
        except Exception:
            pass

    choice = input("  Enter a Duo passcode, or just press Enter to send a push "
                   "to your phone: ").strip()
    if choice:
        opened = _duo_click(page, ("Enter a Passcode", "Passcode"))
        if opened:
            print(f"  clicked '{opened}'")
            page.wait_for_timeout(1200)
        field = _first_present(page, "input[name=passcode], input[name*=passcode], "
                                     "input[id*=passcode], input[type=tel]",
                               timeout_ms=8000)
        if field is None:
            _duo_dump(page, "could not find a passcode field")
            print("  ! no passcode field found — see results/duo_debug.txt",
                  file=sys.stderr)
        else:
            field.fill(choice)
            _duo_click(page, ("Log In", "Verify", "Continue", "Submit"))
            print("  passcode submitted")
        del choice
    else:
        sent = _duo_click(page, ("Send Me a Push", "Send me a Push", "Push"))
        if sent:
            print(f"  requested a push ('{sent}') — approve it on your phone now")
        else:
            _duo_dump(page, "no push button found")
            print("  ! could not find a push button — see results/duo_debug.txt",
                  file=sys.stderr)

    _duo_wait(page, deadline)


def _duo_wait(page, deadline: float) -> None:
    """Wait for Duo to hand back to the identity provider."""
    print("  waiting for Duo…")
    warned_at = time.time() + 60
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        if not any(m in page.url.lower() for m in DUO_HOST_MARKERS):
            print("  Duo cleared")
            return
        if time.time() > warned_at:
            warned_at = float("inf")
            print("  still waiting — if nothing reached your phone, Ctrl-C and retry "
                  "with a passcode")
    _duo_dump(page, "timed out waiting for Duo")


def _await_application(page, deadline: float) -> bool:
    """Wait until the SAML chain actually lands back on the application.

    Leaving Duo is not the finish line. Two more auto-submitting SAML forms have to
    post — identity provider to hub, hub to the catalog — before the catalog issues
    its own session cookie. Checking the API before that lands reports "not
    authorized" when the truth is "not finished yet", which is exactly the false
    alarm this function exists to prevent.
    """
    while time.time() < deadline:
        if page.url.startswith(BASE):
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return True
        page.wait_for_timeout(1500)
    return False


def cmd_cli_login(args) -> int:
    """Log in entirely from the terminal: you type, the browser is driven for you."""
    sync_playwright = _require_playwright()
    verify_url = args.verify_url or (require_site() + "/")

    print(f"Target: {verify_url}")
    print("You will be asked for your username and password. They go into the "
          "identity provider's\nown form and are never stored, logged, or printed.\n")

    username = input("CCHMC username or email: ").strip()
    if not username:
        print("! no username given", file=sys.stderr)
        return 1
    password = getpass.getpass("Password (not echoed): ")
    if not password:
        print("! no password given", file=sys.stderr)
        return 1

    deadline = time.time() + LOGIN_TIMEOUT_S

    # Headless by default — this tenant's Duo prompt drives fine from the terminal.
    # --headed stays available for when a step misbehaves and you want to watch.
    headed = args.headed
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()

        try:
            print("\n  opening the catalog…")
            page.goto(verify_url, wait_until="load", timeout=NAV_TIMEOUT_MS)

            if BASE in page.url and "shib" not in page.url:
                print("  already reachable without logging in — nothing to do.")
            else:
                print("  selecting Cincinnati Children's…")
                if not _select_cchmc(page):
                    print("! could not select the institution on the discovery page.\n"
                          "  Watch the browser window to see what it does.", file=sys.stderr)
                    browser.close()
                    return 3
                page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
                page.wait_for_timeout(1500)

                print(f"  identity provider: {page.url.split('?')[0][:70]}")
                form = None
                for candidate in IDP_FORMS:
                    if _first_present(page, candidate["pass"], timeout_ms=6000):
                        form = candidate
                        break
                if form is None:
                    print("! no password field found on the IdP page.\n"
                          "  Check the browser window.", file=sys.stderr)
                    browser.close()
                    return 3

                print(f"  filling the {form['name']} login form…")
                _first_present(page, form["user"]).fill(username)
                _first_present(page, form["pass"]).fill(password)
                del password  # used; drop the reference immediately

                submit = _first_present(page, form["submit"])
                if submit is None:
                    print("! no submit control found", file=sys.stderr)
                    browser.close()
                    return 3
                submit.click()
                page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
                page.wait_for_timeout(2500)

                err = _page_error_text(page)
                if err and any(m in page.url.lower() for m in ("idp", "login")):
                    print(f"\n! the identity provider rejected the sign-in: {err}",
                          file=sys.stderr)
                    browser.close()
                    return 2

                if any(m in page.url.lower() for m in DUO_HOST_MARKERS):
                    _handle_duo(page, args.trust_device, deadline, headed)

                # Do not check anything until the SAML chain has actually landed.
                print("  completing the SAML handoff…")
                if not _await_application(page, deadline):
                    print(f"\n! never made it back to the application "
                          f"(stopped at {page.url.split('?')[0][:70]})", file=sys.stderr)
                    _save_state(context)
                    browser.close()
                    return 3
                print(f"  landed on {page.url.split('?')[0][:70]}")

            ok, detail = _check_api(context)
            if not ok:
                print(f"\n! signed in, but the catalog API is still refusing: {detail}")
                print("  Authentication and authorization are different things — this "
                      "account may\n  simply not be provisioned for the catalog. That is "
                      "an RDCRN admin step.", file=sys.stderr)
                # The session is still worth keeping; page checks may work even so.
                _save_state(context)
                print(f"  Session saved anyway to {STATE_FILE}")
                browser.close()
                return 2

            _save_state(context)
            print(f"\n  AUTHENTICATED.  {PROBE_PATH} -> {detail}")
            print(f"  Session saved to {STATE_FILE} (0600).")

            # Now the page they actually asked about.
            resp = context.request.get(verify_url, timeout=NAV_TIMEOUT_MS)
            print(f"  {verify_url} -> HTTP {resp.status}")

            print("\nFrom here it is hands-off:")
            print("  ./.venv/bin/python monitor.py")
            browser.close()
            return 0

        except KeyboardInterrupt:
            browser.close()
            print("\naborted", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"\n! login failed: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
            print("  Check the browser window for where it stopped.", file=sys.stderr)
            browser.close()
            return 3


def refresh(verbose: bool = True) -> tuple[int, str]:
    """Headless silent re-SSO. Returns (exit_code, cookie_header).

    cookie_header is empty unless exit_code == 0. Callers should keep it in memory
    and pass it to the child process's environment rather than writing it to disk.
    """
    require_site()
    if not _state_exists():
        if verbose:
            print(f"No saved session at {STATE_FILE}.", file=sys.stderr)
            print("Run:  ./.venv/bin/python sso_session.py login", file=sys.stderr)
        return 2, ""

    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=STATE_FILE)
        except Exception as e:
            if verbose:
                print(f"Saved session unreadable ({type(e).__name__}); re-run login.",
                      file=sys.stderr)
            browser.close()
            return 2, ""

        # Try the saved cookies as they are, before any SSO round-trip.
        #
        # This is what makes a PASTED cookie usable: it carries the application's
        # session but none of the identity-provider cookies, so driving the SAML
        # chain could only ever fail. A cookie that already works needs no chain.
        # Live sessions benefit too — it skips a pointless navigation, and avoids
        # the stale _opensaml_req_ cookie that makes a re-drive 401 on first try.
        ok, detail = _check_api(context)
        if not ok:
            page = context.new_page()
            ok, detail = _authenticated_body(page)

        if not ok:
            if verbose:
                print(f"Session is no longer usable: {detail}", file=sys.stderr)
                # Do not claim the IdP session expired: a pasted cookie never had
                # one, and saying so sends people chasing the wrong problem.
                print("Sign in again (Login tab), or paste a fresh cookie.",
                      file=sys.stderr)
            browser.close()
            return 2, ""

        header = _cookie_header_for_catalog(context)
        # Re-save: the silent re-SSO usually issued a brand-new SP session cookie,
        # and rolling it forward is what keeps the next run from needing a login.
        _save_state(context)
        browser.close()

    if verbose:
        n = len(header.split(";")) if header else 0
        print(f"Session live. {PROBE_PATH} -> {detail}")
        print(f"Carrying {n} catalog cookie(s) into the check.")
    if not header:
        if verbose:
            print("! authenticated but no catalog cookies found — nothing to hand over.",
                  file=sys.stderr)
        return 3, ""
    return 0, header


def cmd_refresh(args) -> int:
    code, header = refresh(verbose=True)
    if code == 0 and args.print_cookie:
        # Opt-in only. This puts a live credential on stdout.
        print(header)
    return code


def cmd_status(args) -> int:
    print(f"Target:     {BASE or '(none configured - sign in on the Login tab)'}")
    print(f"State file: {STATE_FILE}")
    if not _state_exists():
        print("Status:     NO SESSION — run 'login' first.")
        return 2
    age_s = time.time() - os.path.getmtime(STATE_FILE)
    mode = stat.S_IMODE(os.stat(STATE_FILE).st_mode)
    print(f"Saved:      {age_s / 3600:.1f} h ago   (mode {oct(mode)})")
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print("!           file is group/other-readable — it holds live session cookies.")

    if args.offline:
        try:
            raw = json.load(open(STATE_FILE))
        except Exception as e:
            print(f"Status:     unreadable state file ({type(e).__name__})")
            return 2
        names = [(c.get("domain"), c.get("name")) for c in raw.get("cookies", [])]
        print(f"Cookies:    {len(names)} saved")
        for dom, name in sorted(set(names))[:25]:
            print(f"              {dom}  {name}")
        auth = session_cookie_names(raw.get("cookies", []))
        if names and not auth:
            print("Status:     ANONYMOUS - cookies are saved, but none of them carry")
            print("            a session (no shibsession/sessionid). Re-run 'login'.")
            return 2
        if auth:
            print(f"Session:    {', '.join(auth)}")
        if not names:
            print("Status:     UNUSABLE — state file holds no cookies; re-run 'login'.")
            return 2
        return 0

    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        ok, detail = _authenticated_body(page)
        print(f"Status:     {'LIVE' if ok else 'EXPIRED'} — {detail}")
        host = urlsplit(BASE).netloc.split(":")[0]
        for c in _summarize_cookies(context):
            if session_cookie_names([c]) or (host and
                                             c["domain"].lstrip(".").endswith(host)):
                print(f"              {c['domain']}  {c['name']}  exp={c['expires']}")
        browser.close()
    return 0 if ok else 2


def main() -> int:
    ap = argparse.ArgumentParser(
        description="RDCRN SSO session manager (login once, then silent re-auth).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="interactive one-time login in a real browser").set_defaults(
        func=cmd_login)

    c = sub.add_parser("cli-login",
                       help="log in from the terminal: you type username, password, "
                            "and any Duo passcode")
    c.add_argument("--verify-url", metavar="URL",
                   default=os.environ.get("CATALOG_VERIFY_URL") or "",
                   help="page to land on and verify after signing in "
                        "(default: the configured site's root)")
    c.add_argument("--headed", action="store_true",
                   help="show the browser window and drive Duo yourself; only needed "
                        "if a step misbehaves")
    c.add_argument("--trust-device", action="store_true",
                   help="tick Duo's 'remember me' box so later logins skip the push "
                        "(changes your Duo posture — opt in)")
    c.set_defaults(func=cmd_cli_login)

    r = sub.add_parser("refresh", help="headless silent re-SSO; refresh the SP session")
    r.add_argument("--print-cookie", action="store_true",
                   help="print the Cookie header to stdout (a live secret — opt-in)")
    r.set_defaults(func=cmd_refresh)

    s = sub.add_parser("status", help="is the saved session still usable?")
    s.add_argument("--offline", action="store_true",
                   help="inspect the state file only; make no network requests")
    s.set_defaults(func=cmd_status)

    args = ap.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
