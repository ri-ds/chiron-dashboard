#!/usr/bin/env python3
"""Run an existing Chiron tool against the LIVE RDCRN site, using the saved session.

The tools authenticate the way local Chiron expects — HTTP Basic, or a Django
login form at /accounts/login/. The live site expects neither: it is behind
Shibboleth, where the only thing that works is a `_shibsession_` cookie. Rather
than modify five tools (the data-validator in particular is deliberately wired in
unmodified), this puts a small proxy in front:

    tool  ->  127.0.0.1:<port>  ->  https://<live site>
                    |
                    +-- injects the session cookie on every forwarded request
                    +-- answers /accounts/login/ itself, so the data-validator's
                        mandatory login step succeeds without that endpoint
                        existing behind the SSO wall

So each tool runs with its real code path, believing it is talking to an ordinary
Chiron. Only the transport changes.

    python live_runner.py --tool dataquality
    python live_runner.py --tool validator

Exit codes are the tool's own, except: 2 if there is no usable session.
"""

from __future__ import annotations

import argparse
import http.server
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import sso_session

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

VALIDATOR = os.path.join(ROOT, "chiron-validator")
DATA_VALIDATOR = os.path.join(ROOT, "chiron-data-validator")
RESULTS = os.path.join(HERE, "results")

# urllib does not consult certifi, and this interpreter has no usable CA store of
# its own, so every HTTPS forward failed with CERTIFICATE_VERIFY_FAILED -- surfacing
# as a bare 502 that reads like the site being down. The tools themselves use
# requests, which bundles certifi, so use that same bundle here. Verification stays
# ON: this proxy carries a live session, and the one thing it must not do is trust
# an unverified peer with it.
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

# Hop-by-hop headers must not be forwarded (RFC 7230 6.1).
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "upgrade"}

# Values the login shim hands back. They are never sent upstream — the real
# credential is the injected session cookie — so they only have to be non-empty
# and consistent enough for the client to believe the login worked.
SHIM_CSRF = "live-runner-csrf-token"
SHIM_SESSIONID = "live-runner-session"


class _Handler(http.server.BaseHTTPRequestHandler):
    target = ""       # the signed-in site, resolved at run time (never hardcoded)
    self_base = ""    # this proxy's own origin, for rewriting upstream links
    cookie = ""       # the live Cookie header
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the tool's own output readable
        pass

    # -- the login the data-validator insists on ---------------------------
    def _shim_login(self, method: str) -> None:
        """Answer /accounts/login/ locally.

        chironval requires a csrftoken cookie from the GET, then a 302 plus a
        sessionid cookie from the POST, or it raises before making any API call.
        Behind Shibboleth that endpoint cannot deliver either, so it is answered
        here and the real authentication happens via the injected cookie.
        """
        if method == "GET":
            body = b"<html><body>login</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", f"csrftoken={SHIM_CSRF}; Path=/")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # POST -> "successful login"
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"sessionid={SHIM_SESSIONID}; Path=/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _forward(self, method: str) -> None:
        if self.path.startswith("/accounts/login"):
            self._shim_login(method)
            return

        url = self.target + self.path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(url, data=body, method=method)
        for k, v in self.headers.items():
            lk = k.lower()
            # Drop the client's own cookies and auth: the session cookie is the
            # only credential that means anything upstream, and the shim's fake
            # csrftoken/sessionid would just be noise.
            if lk in HOP_BY_HOP or lk in ("host", "cookie", "authorization",
                                          "content-length", "accept-encoding"):
                continue
            req.add_header(k, v)
        req.add_header("Cookie", self.cookie)

        try:
            with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
                self._relay(resp.status, resp.headers, resp.read())
        except urllib.error.HTTPError as e:
            self._relay(e.code, e.headers, e.read())
        except Exception as e:
            # Name the cause: "URLError" alone sent this diagnosis to the wrong
            # place entirely once already.
            reason = str(getattr(e, "reason", "") or e)[:160]
            msg = f"live_runner proxy error: {type(e).__name__}: {reason}".encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def _rewrite_links(self, headers, payload: bytes) -> bytes:
        """Point upstream absolute URLs back at this proxy.

        DRF returns pagination `next`/`previous` as absolute URLs built from the
        upstream Host, and chironval follows them verbatim -- its _get() uses any
        string starting with "http" as-is. Left alone, page 1 arrives through the
        proxy and page 2 goes straight to the live site carrying none of the
        injected session, so a 1400-concept dataset dies on its second page.
        Rewriting keeps the whole walk on the proxy, which is the entire point of
        having one.
        """
        ctype = (headers.get("Content-Type") or "").lower()
        if "json" not in ctype and "text" not in ctype:
            return payload
        host = urlsplit(self.target).netloc
        if not host or not self.self_base:
            return payload
        out = payload
        for scheme in (b"https://", b"http://"):
            out = out.replace(scheme + host.encode(), self.self_base.encode())
        return out

    def _relay(self, status, headers, payload: bytes) -> None:
        payload = self._rewrite_links(headers, payload)
        self.send_response(status)
        for k, v in headers.items():
            lk = k.lower()
            # Set-Cookie is dropped so upstream cannot overwrite the shim's
            # cookies and break the client's idea of being logged in.
            if lk in HOP_BY_HOP or lk in ("content-length", "set-cookie",
                                          "content-encoding"):
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")

    def do_HEAD(self):
        self._forward("HEAD")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_proxy(target: str, cookie: str) -> tuple[str, http.server.ThreadingHTTPServer]:
    """Bind to loopback only — nothing outside this host should reach it."""
    _Handler.target = target.rstrip("/")
    _Handler.cookie = cookie
    port = _free_port()
    _Handler.self_base = f"http://127.0.0.1:{port}"
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}", srv


def _tool_cmd(tool: str, base: str, dataset: str) -> tuple[list[str], str]:
    """(command, cwd) for each supported tool, pointed at the proxy."""
    if tool == "dataquality":
        cmd = [os.path.join(DATA_VALIDATOR, "venv", "bin", "python"),
               "chiron_validator.py", "validate",
               "--base-url", base,
               # The shimmed login accepts anything; these are not real
               # credentials and never leave this host.
               "--username", "session", "--password", "session",
               # The live concepts listing takes 25-30s per page and the tool's
               # default timeout is exactly 30.0, so every dataset died on a read
               # timeout before one concept was examined. Per-concept statistics are
               # fast (~0.3s), so a higher ceiling costs a slow run nothing.
               "--timeout", os.environ.get("CATALOG_HTTP_TIMEOUT", "120"),
               "--json-out", os.path.join(RESULTS, "dataquality_live.json")]
        # Without this the tool sweeps EVERY dataset on the site: its CLI does not
        # read CHIRON_DATASET, so the chosen dataset has to be passed as a flag.
        if dataset:
            cmd += ["--dataset", dataset]
        return cmd, DATA_VALIDATOR
    if tool == "validator":
        # No --include-v1: v1 needs a genuine Django session login, which does
        # not exist behind Shibboleth.
        # Same 30.0s default as the data-validator, and the same slow live listing
        # sits behind it, so raise the ceiling here too.
        return ([os.path.join(VALIDATOR, ".venv", "bin", "chiron-validator"),
                 "run",
                 "--timeout", os.environ.get("CATALOG_HTTP_TIMEOUT", "120")],
                VALIDATOR)
    raise SystemExit(f"unknown tool: {tool}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tool", required=True, choices=["dataquality", "validator"])
    ap.add_argument("--dataset", default=os.environ.get("CATALOG_DATASET", ""))
    args = ap.parse_args()

    # Whichever site was last signed into on the Login tab. Nothing here is
    # hardcoded: require_site() stops with instructions rather than falling back to
    # some other deployment, because a run against the wrong host still produces a
    # full, confident report -- about a system nobody asked about.
    origin = sso_session.require_site()
    print(f"Live target: {origin}")
    code, cookie = sso_session.refresh(verbose=True)
    if code != 0:
        print("\nNo usable session — sign in on the Login tab first.", file=sys.stderr)
        return 2

    if not cookie:
        # The header is built by scoping the saved cookies to the target origin, so
        # an empty one means the saved session belongs to a different host than the
        # site now configured. Injecting it would just replay an anonymous request.
        print("\nThe saved session has no cookies for this site - sign in again on "
              "the Login tab.", file=sys.stderr)
        return 2

    base, srv = start_proxy(origin, cookie)
    print(f"Proxy: {base} -> {origin} (session cookie injected)")

    # The dataset name must come from the LIVE site. Inheriting CHIRON_DATASET from
    # the environment points the tools at the local stack's dataset, which does not
    # exist here — every {dataset_string} endpoint then 404s with "No Dataset
    # matches the given query" and is scored "unreached" rather than actually tested.
    dataset = args.dataset
    if not dataset:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(f"{base}/api/v2/dataset/"), timeout=30) as r:
                import json as _json
                payload = _json.loads(r.read() or b"{}")
            items = payload.get("datasets") if isinstance(payload, dict) else payload
            ids = [d["unique_id"] for d in (items or []) if d.get("unique_id")]
            # Prefer the current dataset over a dated freeze. Chiron calls the live
            # one "default" -- HeartsMart's own picker tells people to choose it when
            # unsure -- whereas the API's first entry is arbitrary and here happens to
            # be a June freeze. Falls back to the first id on deployments with no
            # "default", and --dataset/CATALOG_DATASET still overrides both.
            dataset = "default" if "default" in ids else (ids[0] if ids else "")
        except Exception as e:
            print(f"! could not list datasets: {type(e).__name__}", file=sys.stderr)
    if dataset:
        print(f"Dataset: {dataset} (from the live site)\n")
    else:
        print("! no dataset discovered — dataset-scoped endpoints will not be "
              "testable\n", file=sys.stderr)

    os.makedirs(RESULTS, exist_ok=True)
    cmd, cwd = _tool_cmd(args.tool, base, dataset)

    # The validator writes to its own reports/ directory. Preserve whatever the
    # local run left there, so a live run never overwrites local results.
    latest = os.path.join(VALIDATOR, "reports", "latest_run.json")
    backup = latest + ".local-bak"
    restore = False
    if args.tool == "validator" and os.path.isfile(latest):
        shutil.copy2(latest, backup)
        restore = True

    env = {**os.environ, "CHIRON_BASE_URL": base,
           "CHIRON_USER": "session", "CHIRON_PASSWORD": "session"}
    # Always override, never inherit: the local stack's dataset name is wrong here.
    env["CHIRON_DATASET"] = dataset or ""

    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, timeout=1500)
        rc = proc.returncode
    except FileNotFoundError as e:
        print(f"! tool not found: {e}", file=sys.stderr)
        rc = 1
    except subprocess.TimeoutExpired:
        print("! tool timed out", file=sys.stderr)
        rc = 1
    finally:
        srv.shutdown()
        if args.tool == "validator" and os.path.isfile(latest):
            shutil.copy2(latest, os.path.join(RESULTS, "validator_live.json"))
            if restore:
                shutil.copy2(backup, latest)
                os.remove(backup)

    print(f"\n{args.tool} finished with exit code {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
