#!/usr/bin/env python3
"""RDCRN public data catalog — read-only checker.

Standalone. Reuses an authenticated session that YOU provide (see README); it does
NOT log in, never handles your password/2FA, and never stores or prints the secret.

Auth is read from the environment (pick whichever you have):
  CATALOG_COOKIE        raw Cookie header, e.g. "_shibsession_abc=...; other=..."
  CATALOG_COOKIES_FILE  cookie file path (Mozilla/Netscape or LWP, e.g. cookies.txt)
  CATALOG_AUTH_HEADER   Authorization header value, e.g. "Bearer <token>"
Config:
  CATALOG_BASE_URL      overrides the site signed into on the dashboard Login tab
  CATALOG_DATASET       optional dataset slug to spot-check

Exit codes: 0 authenticated & ran · 2 not authenticated · 3 reachable/unexpected · 1 other.
"""

from __future__ import annotations

import json
import os
import sys
from http.cookiejar import LWPCookieJar, MozillaCookieJar

import requests


def _load_dotenv(path: str) -> None:
    """Minimal .env loader (no dependency). KEY=VALUE lines; '#' comments; does not
    override variables already set in the real environment. Splits on the FIRST '='
    only, so a raw Cookie header value (with its own '=' and ';') stays intact."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                os.environ.setdefault(key, val)
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import sso_session as _sso  # noqa: E402  (must follow .env load: it reads the env)

# No deployment is baked in. The target is whichever site was signed into on the
# dashboard's Login tab (sso_session records it beside the session), or an explicit
# CATALOG_BASE_URL. Empty means "not configured yet", which callers must treat as a
# stop rather than substituting a default host.
BASE = _sso.load_site()
DATASET = os.environ.get("CATALOG_DATASET", "").strip()
UA = "Mozilla/5.0 (rdcrn-catalog-checker; read-only)"
TIMEOUT = 20


def build_session():
    """Return (session, have_auth). Loads whatever credential the env provides."""
    s = requests.Session()
    s.headers["User-Agent"] = UA
    have_auth = False

    auth_header = os.environ.get("CATALOG_AUTH_HEADER", "").strip()
    if auth_header:
        s.headers["Authorization"] = auth_header
        have_auth = True

    raw_cookie = os.environ.get("CATALOG_COOKIE", "").strip()
    if raw_cookie:
        s.headers["Cookie"] = raw_cookie
        have_auth = True

    cookie_file = os.environ.get("CATALOG_COOKIES_FILE", "").strip()
    if cookie_file:
        jar = None
        for JarClass in (LWPCookieJar, MozillaCookieJar):
            try:
                j = JarClass(cookie_file)
                j.load(ignore_discard=True, ignore_expires=True)
                jar = j
                break
            except Exception:
                continue
        if jar is None:
            print(f"! could not load {cookie_file} (tried LWP + Mozilla formats)",
                  file=sys.stderr)
        else:
            for c in jar:
                s.cookies.set_cookie(c)
            have_auth = True

    return s, have_auth


def looks_unauthenticated(resp) -> bool:
    """True if the response is the SSO gate rather than real API content."""
    if resp.status_code in (401, 403):
        return True
    final = (resp.url or "").lower()
    if any(x in final for x in ("shib", "/login", "idp", "saml")):
        return True
    ctype = resp.headers.get("Content-Type", "")
    # A 200 that hands back HTML where JSON was expected is almost certainly the login page.
    if resp.status_code == 200 and "html" in ctype and "json" not in ctype:
        return True
    return False


def get(s, path):
    return s.get(BASE + path, timeout=TIMEOUT, allow_redirects=True)


def main() -> int:
    s, have_auth = build_session()
    print(f"Target: {BASE}")
    print(f"Auth provided: {'yes' if have_auth else 'NO (probing the gate unauthenticated)'}\n")

    # Cheapest authenticated check first.
    try:
        r = get(s, "/api/version/")
    except Exception as e:
        print(f"UNREACHABLE: {type(e).__name__}: {e}")
        return 3

    if looks_unauthenticated(r):
        print(f"NOT AUTHENTICATED  (/api/version/ -> HTTP {r.status_code}, landed {r.url[:90]})")
        print("\nThe catalog is behind RDCRN Shibboleth SSO + MFA. Supply a live session:")
        print("  CATALOG_COOKIE='_shibsession_xxx=...'   (from a browser login), or")
        print("  CATALOG_COOKIES_FILE=cookies.txt        (from the SSO login script), or")
        print("  CATALOG_AUTH_HEADER='Bearer <token>'    (only if RDCRN issues a token).")
        return 2

    try:
        version = r.json()
    except ValueError:
        print(f"Reached /api/version/ (HTTP {r.status_code}) but the body wasn't JSON.")
        return 3
    print(f"AUTHENTICATED.  /api/version/ -> {json.dumps(version)[:200]}")

    # Datasets visible to this session.
    try:
        r2 = get(s, "/api/v2/dataset/")
    except Exception as e:
        print(f"/api/v2/dataset/ error: {type(e).__name__}: {e}")
        return 3
    if looks_unauthenticated(r2):
        print("Session worked for /api/version/ but not /api/v2/dataset/ (partial access?).")
        return 3
    try:
        data = r2.json()
        if isinstance(data, list):
            n = len(data)
        elif isinstance(data, dict):
            n = len(data.get("results", data.get("datasets", [])))
        else:
            n = 0
        print(f"/api/v2/dataset/ -> {n} dataset(s) visible")
    except ValueError:
        print(f"/api/v2/dataset/ -> HTTP {r2.status_code}, non-JSON body")

    if DATASET:
        try:
            r3 = get(s, f"/api/v2/dataset/{DATASET}/")
            print(f"/api/v2/dataset/{DATASET}/ -> HTTP {r3.status_code}"
                  f"{' (not authorized / not found)' if looks_unauthenticated(r3) else ''}")
        except Exception as e:
            print(f"/api/v2/dataset/{DATASET}/ error: {type(e).__name__}: {e}")

    print("\nOK: authenticated read-only check completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
