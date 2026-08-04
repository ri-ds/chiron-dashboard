"""HTTP load driver — self-contained, public-API only.

Authenticates like the browser UI (session cookie + CSRF), then samples a
scenario's latency sequentially and, separately, measures throughput under a
short concurrent burst. Never touches Chiron internals or its DB — everything
is over the published HTTP API, driven by synthetic data.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .stats import Sample, Stats, summarize


class LoadClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()

    def login(self) -> bool:
        url = f"{self.base_url}/admin/login/"
        self.session.get(url, timeout=self.timeout)
        csrf = self.session.cookies.get("csrftoken")
        r = self.session.post(url, data={"username": self.username, "password": self.password,
                                         "csrfmiddlewaretoken": csrf, "next": "/admin/"},
                              headers={"Referer": url}, timeout=self.timeout, allow_redirects=False)
        return r.status_code in (301, 302)

    def _fresh_session(self) -> requests.Session:
        """A throughput burst needs independent sessions so the cookie jar isn't a
        contention point; clone auth cookies into a new Session."""
        s = requests.Session()
        s.cookies.update(self.session.cookies)
        return s

    def one(self, method: str, path: str, params=None, json_body=None,
            session: requests.Session | None = None) -> Sample:
        s = session or self.session
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            csrf = s.cookies.get("csrftoken")
            if csrf:
                headers["X-CSRFToken"] = csrf
                headers["Referer"] = self.base_url
        t0 = time.perf_counter()
        try:
            r = s.request(method.upper(), url, params=params, json=json_body,
                          headers=headers, timeout=self.timeout)
            ms = (time.perf_counter() - t0) * 1000
            return Sample(ok=r.ok, status=r.status_code, ms=ms)
        except requests.RequestException:
            ms = (time.perf_counter() - t0) * 1000
            return Sample(ok=False, status=0, ms=ms)

    def latency(self, method: str, path: str, iterations: int, params=None,
                json_body=None, warmup: int = 2) -> Stats:
        """Sequential latency sampling (single client) → p50/p95/p99."""
        for _ in range(warmup):
            self.one(method, path, params, json_body)
        samples = [self.one(method, path, params, json_body) for _ in range(iterations)]
        return summarize(samples)

    def throughput(self, method: str, path: str, total: int, concurrency: int,
                   params=None, json_body=None) -> Stats:
        """Concurrent burst → throughput (rps) + latency under load."""
        sessions = [self._fresh_session() for _ in range(concurrency)]
        samples: list[Sample] = []
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futs = [ex.submit(self.one, method, path, params, json_body, sessions[i % concurrency])
                    for i in range(total)]
            for f in as_completed(futs):
                samples.append(f.result())
        wall = time.perf_counter() - t0
        return summarize(samples, wall_s=wall)
