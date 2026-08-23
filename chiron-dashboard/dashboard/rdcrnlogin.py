"""RDCRN sign-in, driven from the dashboard's Login tab.

The credential path is the whole design here. The password arrives in one POST,
is handed straight to the sign-in worker over a pipe, and is never stored on this
side: not in a variable that outlives the request, not in the job store, not in a
log line, and not in anything the status endpoint can return.

Deliberately NOT routed through JobRunner: that runner pipes a subprocess's stdout
and stderr into a file under data/logs/, which is exactly where a credential must
never end up. This spawns the worker itself and keeps its output in memory.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from . import config

WORKER = config.RDCRN / "web_login.py"
PYTHON = config.RDCRN / ".venv" / "bin" / "python"
STATUS_FILE = config.RDCRN / "results" / "login_status.json"
STATE_FILE = config.RDCRN / ".session" / "state.json"
# Written by the sign-in worker (sso_session.set_site) and read by every tool, so
# signing in on this tab is what re-points the whole toolchain at a new site.
SITE_FILE = config.RDCRN / ".session" / "site.json"

# Cookie names that carry an authenticated session. Kept in step with
# sso_session.SESSION_COOKIE_MARKERS -- the checker is a separate venv, so this is
# five strings duplicated rather than an import across a deployment boundary.
SESSION_COOKIE_MARKERS = ("shibsession", "sessionid", "mod_auth_openidc_session",
                          "_saml", "mellon")


def saved_site() -> str:
    """The site last signed into, so the Login tab reopens on it.

    Deliberately no default. An empty field is honest about there being no target
    yet, where prefilling one invites signing in against whichever deployment
    happened to be hardcoded -- which is exactly how the live tools ended up
    checking a site nobody had logged into.
    """
    try:
        return ((json.loads(SITE_FILE.read_text()) or {}).get("site") or "").strip()
    except (OSError, ValueError):
        return ""


def _save_site(origin: str) -> None:
    """Point the toolchain at `origin`, in the shape sso_session.load_site reads."""
    try:
        SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(SITE_FILE.parent, 0o700)
        tmp = SITE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"site": origin, "updated": _now()}, indent=2))
        os.replace(tmp, SITE_FILE)   # atomic; a tool mid-read never sees a partial
    except OSError:
        pass

_lock = threading.Lock()
_thread: threading.Thread | None = None
_last_error = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def busy() -> bool:
    return _thread is not None and _thread.is_alive()


def _run(url: str, username: str, password: str) -> None:
    """Worker thread: spawn the sign-in process and feed it the credentials.

    The password reaches the child through stdin only. It is not an argument (which
    `ps` would show), not an environment variable (which children inherit), and the
    child's output is captured here rather than written to disk.
    """
    global _last_error
    payload = json.dumps({"url": url, "username": username, "password": password})
    try:
        proc = subprocess.run(
            [str(PYTHON), str(WORKER), "--status", str(STATUS_FILE)],
            cwd=str(config.RDCRN),
            input=payload,
            text=True,
            capture_output=True,
            timeout=420,
        )
        if proc.returncode != 0:
            # stderr from the worker is safe to surface: it is written by our own
            # code and never contains the submitted values.
            _last_error = (proc.stderr or "").strip()[-400:] or \
                f"Sign-in exited with code {proc.returncode}."
        else:
            _last_error = ""
    except subprocess.TimeoutExpired:
        _last_error = "Sign-in timed out."
    except FileNotFoundError as e:
        _last_error = f"Sign-in helper not found: {e}"
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"
    finally:
        payload = ""
        del payload


def start(url: str, username: str, password: str) -> dict:
    """Begin a sign-in. Returns immediately; poll status() for progress."""
    global _thread, _last_error
    with _lock:
        if busy():
            return {"ok": False, "message": "A sign-in is already in progress."}
        if not (url and username and password):
            return {"ok": False, "message": "URL, username and password are required."}
        if not WORKER.exists():
            return {"ok": False, "message": f"Sign-in helper missing at {WORKER}."}
        _last_error = ""
        try:
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(json.dumps({
                "state": "running", "step": "open", "message": "Starting…",
                "url": url, "user": None, "error": "", "updated": _now(),
            }))
        except OSError:
            pass
        _thread = threading.Thread(target=_run, args=(url, username, password),
                                   daemon=True)
        _thread.start()
    return {"ok": True}


def use_cookie(url: str, cookie: str) -> dict:
    """Adopt a Cookie header the user pasted, instead of signing in here.

    Strictly less exposed than the password flow: no credential of yours reaches
    this dashboard, only a session that already exists. The cookie is validated
    against the site before it is saved, so an expired paste fails immediately
    rather than surfacing later as a confusing tool error.

    The trade-off is that a pasted session cannot be refreshed silently — it has
    no upstream identity-provider cookies — so it dies when the site expires it.
    """
    url = (url or "").strip()
    cookie = (cookie or "").strip()
    if not url or not cookie:
        return {"ok": False, "message": "Site URL and cookie are both required."}
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return {"ok": False, "message": "That does not look like a valid URL."}
    origin = f"{parts.scheme}://{parts.netloc}"

    # Accept a whole "Cookie: a=1; b=2" header or just the pairs.
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()

    pairs = []
    for chunk in cookie.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name, value = name.strip(), value.strip()
        if name:
            pairs.append((name, value))
    if not pairs:
        return {"ok": False, "message": "No name=value pairs found in that cookie."}

    # Validate before saving.
    try:
        r = requests.get(f"{origin}/api/v2/auth/",
                         headers={"Cookie": "; ".join(f"{n}={v}" for n, v in pairs)},
                         timeout=30)
    except Exception as e:
        return {"ok": False, "message": f"Could not reach {origin}: {type(e).__name__}"}
    if r.status_code in (401, 403):
        return {"ok": False,
                "message": "That cookie was rejected — it has probably expired."}
    if r.status_code != 200:
        return {"ok": False, "message": f"{origin} answered HTTP {r.status_code}."}
    try:
        user = ((r.json() or {}).get("user") or {}).get("username")
    except Exception:
        return {"ok": False,
                "message": "That response was not JSON — check the site URL."}
    # Chiron answers this endpoint 200 with {"user": null} for anonymous callers, so
    # a 2xx only proves the host is up. Without this the tab accepted any string as
    # a session, and every downstream tool then ran unauthenticated.
    if not user:
        return {"ok": False,
                "message": "That cookie reaches the site but is not signed in "
                           "(the API reports no user) — it has probably "
                           "expired."}

    # Store in the same shape the rest of the toolchain reads (a Playwright
    # storage state), so nothing downstream needs to care how it was obtained.
    host = parts.netloc.split(":")[0]
    state = {"cookies": [{"name": n, "value": v, "domain": host, "path": "/",
                          "expires": -1, "httpOnly": False,
                          "secure": parts.scheme == "https", "sameSite": "Lax"}
                         for n, v in pairs],
             "origins": []}
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(STATE_FILE.parent, 0o700)
        STATE_FILE.write_text(json.dumps(state))
        os.chmod(STATE_FILE, 0o600)
        _save_site(origin)
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps({
            "state": "done", "step": "done", "message": "Cookie accepted.",
            "url": url, "site": origin, "user": user, "error": "",
            "updated": _now(),
        }))
    except OSError as e:
        return {"ok": False, "message": f"Could not save the session: {e}"}
    return {"ok": True, "user": user, "cookies": len(pairs)}


def live_datasets() -> dict:
    """Datasets the saved session can actually see on the live site.

    Read straight from the site with the stored cookies -- no tool run, no proxy --
    so the UI can show what a live Validator or Data-quality run has to choose from
    before anything is launched. Previously the only way to find out was to start a
    run and read what it reported afterwards.
    """
    site = saved_site()
    if not site:
        return {"ok": False, "datasets": [],
                "message": "No site yet \u2014 sign in on the Login tab."}
    if not STATE_FILE.is_file():
        return {"ok": False, "datasets": [],
                "message": "No saved session \u2014 sign in first."}
    try:
        raw = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {"ok": False, "datasets": [],
                "message": "The saved session is unreadable."}

    host = urlsplit(site).netloc.split(":")[0]
    jar = {c["name"]: c["value"] for c in (raw.get("cookies") or [])
           if (c.get("domain") or "").lstrip(".").endswith(host)}
    if not jar:
        return {"ok": False, "datasets": [],
                "message": f"The saved session holds no cookies for {host}."}
    try:
        r = requests.get(f"{site}/api/v2/dataset/", cookies=jar,
                         headers={"Accept": "application/json"}, timeout=30)
    except Exception as e:
        return {"ok": False, "datasets": [],
                "message": f"Could not reach {site}: {type(e).__name__}"}
    if r.status_code in (401, 403):
        return {"ok": False, "datasets": [],
                "message": "The site refused the session \u2014 sign in again."}
    if r.status_code != 200:
        return {"ok": False, "datasets": [],
                "message": f"{site} answered HTTP {r.status_code}."}
    try:
        items = (r.json() or {}).get("datasets") or []
    except Exception:
        return {"ok": False, "datasets": [],
                "message": "That response was not JSON \u2014 check the site URL."}
    return {"ok": True, "site": site,
            "datasets": [{"unique_id": d.get("unique_id"),
                          "name": d.get("name") or d.get("unique_id"),
                          "selectable": bool(d.get("selectable", True))}
                         for d in items if d.get("unique_id")]}


def session_state() -> dict:
    """What we can say about the saved session WITHOUT any cookie values."""
    if not STATE_FILE.is_file() or STATE_FILE.stat().st_size == 0:
        return {"state": "absent", "cookies": 0, "saved": None}
    try:
        raw = json.loads(STATE_FILE.read_text())
    except Exception:
        return {"state": "unreadable", "cookies": 0, "saved": None}
    cookies = raw.get("cookies") or []
    saved = datetime.fromtimestamp(STATE_FILE.stat().st_mtime,
                                   tz=timezone.utc).isoformat(timespec="seconds")
    # Names and domains only — never values.
    domains = sorted({(c.get("domain") or "").lstrip(".") for c in cookies})
    # Cookie count alone says nothing: an anonymous browse of a load-balanced site
    # with analytics already saves three. Separate out the ones that carry a session
    # so "saved" can never again be shown for a state file that reads nothing.
    carrying = [c.get("name", "") for c in cookies
                if any(m in (c.get("name") or "").lower()
                       for m in SESSION_COOKIE_MARKERS)]
    if cookies and not carrying:
        state = "anonymous"
    elif cookies:
        state = "saved"
    else:
        state = "absent"
    return {"state": state, "cookies": len(cookies), "saved": saved,
            "domains": domains[:8], "authCookies": len(carrying),
            "site": saved_site()}


def status() -> dict:
    """Progress of the current or most recent sign-in, plus the session summary."""
    site = saved_site()
    data = {"state": "idle", "step": None, "message": "", "url": site,
            "site": site, "user": None, "error": ""}
    try:
        if STATUS_FILE.is_file():
            data.update(json.loads(STATUS_FILE.read_text()))
    except Exception:
        pass
    if _last_error and data.get("state") != "done":
        data["state"] = "error"
        data["error"] = data.get("error") or _last_error
    data["busy"] = busy()
    data["session"] = session_state()
    data["default_url"] = site
    return data


def sign_out() -> dict:
    """Delete the saved session locally.

    This clears what is on this machine. It does not end the session at CCHMC or
    Duo — say so plainly rather than implying a full logout.
    """
    removed = False
    try:
        if STATE_FILE.is_file():
            STATE_FILE.unlink()
            removed = True
        if STATUS_FILE.is_file():
            STATUS_FILE.unlink()
    except OSError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "removed": removed}
