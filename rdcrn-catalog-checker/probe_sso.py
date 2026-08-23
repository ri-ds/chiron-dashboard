#!/usr/bin/env python3
"""RDCRN SSO topology prober — stdlib only, no credentials, read-only.

Answers the questions you actually need answered before debugging an auth failure:
where does this environment's login wall sit, which identity providers will it
accept, and is the Google bridge wired up today?

    trace   Follow the redirect chain from a target URL and label every hop, so you
            can see exactly where the Shibboleth SP hands off and where it stops.
    idps    Search the discovery feed for an identity provider by name and print
            its entityID (what you pick on the login page).
    google  Check whether the Google -> SAML bridge is live, by driving the hub
            with Google's entityID and confirming it reaches accounts.google.com.

Everything here is an unauthenticated GET against public endpoints. Nothing logs
in; no credential is read, sent, or stored.

    python3 probe_sso.py trace
    python3 probe_sso.py trace --url https://shibstage.rarediseasesnetwork.org/
    python3 probe_sso.py idps cincinnati
    python3 probe_sso.py google
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

import sso_session as _sso

# Whichever site was signed into on the Login tab, or CATALOG_BASE_URL -- no
# hardcoded deployment. HUB below is still the RDCRN Shibboleth hub, which is what
# this probe is specifically about.
BASE = _sso.load_site()

HUB = "https://shib.rarediseasesnetwork.org"
DISCO_FEED = f"{HUB}/idp/shibboleth-ds/DiscoFeed_small.json"
GOOGLE_ENTITY_ID = (
    f"{HUB}/satosa/proxy.xml/" + base64.b64encode(b"https://accounts.google.com").decode()
)

UA = "rdcrn-catalog-checker/probe (read-only, unauthenticated)"
TIMEOUT = 25
MAX_HOPS = 12

# How to describe each host in plain language when it shows up in a chain.
HOST_ROLES = (
    ("accounts.google.com", "Google sign-in (OIDC) — the human types their password here"),
    ("satosa", "SATOSA proxy — bridges Google/OIDC into the SAML federation"),
    ("shibboleth-ds", "discovery service — 'pick your institution' page"),
    ("/idp/profile/SAML2", "hub IdP — SAML authn request"),
    ("auth.ncats.nih.gov", "NCATS auth — Login.gov route"),
    ("login.gov", "Login.gov"),
    ("shibstage", "RDCRN staging Shibboleth"),
    ("shib.rarediseasesnetwork.org", "RDCRN hub Shibboleth IdP"),
    ("Shibboleth.sso", "Shibboleth SP endpoint"),
)


def _role(url: str) -> str:
    for needle, desc in HOST_ROLES:
        if needle.lower() in url.lower():
            return desc
    return "application / resource"


class _Recorder(urllib.request.HTTPRedirectHandler):
    """Follow redirects but remember every hop."""

    def __init__(self):
        self.hops: list[tuple[int, str]] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops.append((code, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl_context() -> ssl.SSLContext:
    """A context that can actually verify these hosts.

    Framework/python.org builds on macOS do not read the system keychain, so
    urllib fails with CERTIFICATE_VERIFY_FAILED on sites curl handles fine. certifi
    ships as a dependency of requests, so it is present in .venv; prefer its bundle
    when importable and fall back to the platform defaults otherwise.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return ctx


def _fetch(url: str):
    """GET with cookies + redirect recording. Returns (status, final_url, body, hops)."""
    rec = _Recorder()
    opener = urllib.request.build_opener(
        rec,
        urllib.request.HTTPSHandler(context=_ssl_context()),
        urllib.request.HTTPCookieProcessor(CookieJar()),
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    sys.stdout.flush()  # keep stderr diagnostics from jumping ahead of our output
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.status, r.geturl(), r.read(), rec.hops
    except urllib.error.HTTPError as e:
        return e.code, e.geturl(), e.read(), rec.hops
    except urllib.error.URLError as e:
        print(f"! request failed: {type(e).__name__}: {e}", file=sys.stderr)
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            print("  This interpreter has no usable CA bundle. Either run it with the "
                  "project venv:\n    ./.venv/bin/python probe_sso.py …\n"
                  "  or install certifi for this interpreter.", file=sys.stderr)
        return 0, url, b"", rec.hops
    except Exception as e:
        print(f"! request failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0, url, b"", rec.hops


def _shorten(url: str, width: int = 96) -> str:
    base, _, query = url.partition("?")
    if not query:
        return base[:width]
    return f"{base[:width]}?{query[:24]}…({len(query)} chars of SAML/OIDC params)"


def cmd_trace(args) -> int:
    target = args.url or (BASE + args.path)
    print(f"Tracing: {target}\n")

    status, final, body, hops = _fetch(target)
    if status == 0:
        return 1

    print(f"  [start] {_shorten(target)}")
    print(f"          → {_role(target)}")
    for i, (code, url) in enumerate(hops, 1):
        print(f"  [{i:>2}] {code}  {_shorten(url)}")
        print(f"          → {_role(url)}")
    print(f"\n  [final] HTTP {status}  {_shorten(final)}")
    print(f"          → {_role(final)}")

    authwall = any(
        m in final.lower() for m in ("shib", "idp", "accounts.google", "login.gov", "satosa"))
    print()
    if status in (401, 403):
        # The SP guards API paths by refusing them outright rather than redirecting,
        # because a 302 to an HTML login page would be useless to an API client.
        print(f"VERDICT: behind SSO. The Shibboleth SP refused this outright (HTTP {status})")
        print("         instead of redirecting — that is how it guards API paths. A live")
        print("         session cookie is required (see sso_session.py).")
    elif authwall:
        print("VERDICT: behind SSO. An unauthenticated client cannot read this; a live")
        print("         session cookie is required (see sso_session.py).")
        if "shibboleth-ds" in final.lower():
            print("         It stopped at the discovery page, so the identity provider has")
            print("         not been chosen yet — that is a human decision on first login.")
    elif status == 200:
        ctype_json = body.lstrip()[:1] in (b"{", b"[")
        print(f"VERDICT: reachable without SSO (HTTP 200, "
              f"{'JSON' if ctype_json else 'HTML'} body). Genuinely public.")
    else:
        print(f"VERDICT: ended on HTTP {status} without an SSO redirect — inspect manually.")
    return 0


def _load_feed():
    status, _, body, _ = _fetch(DISCO_FEED)
    if status != 200 or not body:
        print(f"! could not load the discovery feed (HTTP {status})", file=sys.stderr)
        return None
    try:
        return json.loads(body)
    except ValueError as e:
        print(f"! discovery feed was not JSON: {e}", file=sys.stderr)
        return None


def cmd_idps(args) -> int:
    feed = _load_feed()
    if feed is None:
        return 1
    term = args.term.lower()

    matches = []
    for entry in feed:
        eid = entry.get("entityID") or ""
        names = [(n.get("value") or "") for n in (entry.get("DisplayNames") or [])]
        if term in (eid + " " + " ".join(names)).lower():
            matches.append((eid, names))

    print(f"Federation size: {len(feed)} identity providers")
    print(f"Matching '{args.term}': {len(matches)}\n")
    for eid, names in matches[: args.limit]:
        label = names[0] if names else "(no display name)"
        print(f"  {label}")
        print(f"    entityID: {eid}")
    if len(matches) > args.limit:
        print(f"\n  … {len(matches) - args.limit} more (raise --limit to see them)")
    if not matches:
        print("  nothing matched — try a shorter term, e.g. 'cincinnati' or 'google'")
    return 0


def cmd_google(args) -> int:
    """Confirm the Google→SAML bridge is live without logging in."""
    print(f"Google IdP entityID:\n  {GOOGLE_ENTITY_ID}")
    tail = GOOGLE_ENTITY_ID.rsplit("/", 1)[-1]
    try:
        print(f"  (the trailing segment base64-decodes to "
              f"{base64.b64decode(tail).decode()})\n")
    except Exception:
        print()

    # IdP choice only takes effect at the hub's own SP endpoint; the application SP
    # ignores entityID and defers to the hub's discovery page.
    url = (f"{HUB}/Shibboleth.sso/Login?entityID="
           f"{urllib.parse.quote(GOOGLE_ENTITY_ID, safe='')}&target=%2F")
    status, final, _, hops = _fetch(url)
    if status == 0:
        return 1

    for i, (code, hop) in enumerate(hops, 1):
        print(f"  [{i:>2}] {code}  {_shorten(hop, 80)}")
    print(f"  [final] HTTP {status}  {_shorten(final, 80)}\n")

    reached_google = any("accounts.google.com" in h for _, h in hops) or \
        "accounts.google.com" in final
    via_satosa = any("satosa" in h.lower() for _, h in hops)

    if reached_google:
        print("VERDICT: the Google bridge is LIVE"
              f"{' (routed through the SATOSA proxy)' if via_satosa else ''}.")
        print("         A Google account is an accepted way to authenticate here.")
        print("         Authentication only, though — whether that identity is *authorized*")
        print("         for the catalog is a separate RDCRN provisioning step.")
        return 0
    print("VERDICT: did not reach Google. The bridge may be down or reconfigured;")
    print("         re-run 'idps google' to see what the feed advertises now.")
    return 3


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Probe RDCRN SSO topology (read-only, no credentials).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trace", help="follow and label the redirect chain")
    t.add_argument("--url", help=f"full URL to trace (default: {BASE} + --path)")
    t.add_argument("--path", default="/api/version/",
                   help="path on the configured base URL (default: /api/version/)")
    t.set_defaults(func=cmd_trace)

    i = sub.add_parser("idps", help="find an identity provider's entityID by name")
    i.add_argument("term", help="substring to search for, e.g. cincinnati")
    i.add_argument("--limit", type=int, default=15)
    i.set_defaults(func=cmd_idps)

    g = sub.add_parser("google", help="check whether the Google->SAML bridge is live")
    g.set_defaults(func=cmd_google)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
