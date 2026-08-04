"""HTTP client for the validator.

**Public API only.** This client speaks to Chiron exclusively over HTTP the way
any external consumer would — it never imports Chiron, never touches its
databases, and holds no knowledge of its internals beyond the published URL
shapes. That black-box constraint is the whole point: the validator proves the
*behaviour* of the running service, not the intent of its source.

Auth: HTTP Basic by default (stateless, ideal for the dataset-in-URL v2 API).
Session login (cookie jar + CSRF) is also supported because the v1 API resolves
the active dataset from the Django session, so exercising v1 requires logging in
and POSTing to ``/select_dataset`` first — exactly what the browser UI does.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class Response:
    status: int
    ok: bool
    duration_ms: float
    url: str
    method: str
    json: Any = None
    text: str = ""
    content_type: str = ""
    error: str = ""


class ChironClient:
    def __init__(self, base_url: str, username: str, password: str,
                 auth_mode: str = "basic", timeout: float = 30.0, verify: bool = True):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.auth_mode = auth_mode
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify
        if auth_mode == "basic":
            self.session.auth = (username, password)
        self._logged_in = False

    # ---- session login (for v1 / UI-realistic flows) ----
    def login(self) -> bool:
        """Establish a Django session via the standard admin login form."""
        login_url = f"{self.base_url}/admin/login/"
        r = self.session.get(login_url, timeout=self.timeout)
        csrf = self.session.cookies.get("csrftoken")
        data = {"username": self.username, "password": self.password,
                "csrfmiddlewaretoken": csrf, "next": "/admin/"}
        r = self.session.post(login_url, data=data,
                              headers={"Referer": login_url}, timeout=self.timeout,
                              allow_redirects=False)
        self._logged_in = r.status_code in (302, 301)
        return self._logged_in

    def select_dataset(self, dataset_id: int) -> bool:
        """Set the session's active dataset (needed by the v1 API)."""
        if not self._logged_in and not self.login():
            return False
        url = f"{self.base_url}/select_dataset"
        csrf = self.session.cookies.get("csrftoken")
        r = self.session.post(url, data={"dataset_id": dataset_id, "csrfmiddlewaretoken": csrf},
                              headers={"Referer": self.base_url}, timeout=self.timeout,
                              allow_redirects=False)
        return r.status_code in (200, 302, 301)

    # ---- core request ----
    def request(self, method: str, path: str, json_body: Any = None,
                params: dict | None = None) -> Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            csrf = self.session.cookies.get("csrftoken")
            if csrf:
                headers["X-CSRFToken"] = csrf
                headers["Referer"] = self.base_url
        t0 = time.perf_counter()
        try:
            r = self.session.request(method.upper(), url, json=json_body, params=params,
                                     headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            dt = (time.perf_counter() - t0) * 1000
            return Response(status=0, ok=False, duration_ms=dt, url=url, method=method.upper(),
                            error=f"{type(exc).__name__}: {exc}")
        dt = (time.perf_counter() - t0) * 1000
        ctype = r.headers.get("Content-Type", "")
        body_json, text = None, ""
        if "application/json" in ctype:
            try:
                body_json = r.json()
            except ValueError as exc:
                text = r.text[:500]
                return Response(status=r.status_code, ok=r.ok, duration_ms=dt, url=r.url,
                                method=method.upper(), text=text, content_type=ctype,
                                error=f"invalid JSON: {exc}")
        else:
            text = r.text[:2000]
        return Response(status=r.status_code, ok=r.ok, duration_ms=dt, url=r.url,
                        method=method.upper(), json=body_json, text=text, content_type=ctype)

    def get(self, path, params=None) -> Response:
        return self.request("GET", path, params=params)

    def post(self, path, json_body=None, params=None) -> Response:
        return self.request("POST", path, json_body=json_body, params=params)

    def put(self, path, json_body=None, params=None) -> Response:
        return self.request("PUT", path, json_body=json_body, params=params)
