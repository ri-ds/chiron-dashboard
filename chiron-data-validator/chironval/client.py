"""Thin HTTP client for Chiron's v2 REST API.

Auth flow (Django session + CSRF), verified empirically against a live Chiron
dev instance on 2026-07-15:

    1. GET  <base_url>/accounts/login/            -> sets a `csrftoken` cookie
    2. POST <base_url>/accounts/login/  with form data:
           username, password, csrfmiddlewaretoken=<csrftoken cookie value>
       On success this returns HTTP 302 and sets a `sessionid` cookie.
       On failure it returns HTTP 200 (re-renders the login form) and sets NO
       `sessionid` cookie - there is no reliable error string to scrape (the
       demo server's login page does not surface one in a stable way), so this
       client treats "got a 302 AND a sessionid cookie" as the sole definition
       of success, and anything else as failure.
    3. Subsequent requests just reuse the same requests.Session (cookie jar).

All requests.exceptions.RequestException subclasses (connection errors,
timeouts, etc.) are allowed to propagate out of login()/get_datasets()/
get_dataset_detail()/get_concepts() - those are prerequisites for the whole
run and a failure there should stop the run with a clear message. Per-concept
statistics fetches are handled more forgivingly (see get_concept_statistics)
since one bad concept should not abort an entire dataset scan.
"""

from __future__ import annotations

import requests
from typing import Any, Dict, List, Optional, Tuple


class ChironAuthError(Exception):
    """Raised when login to Chiron fails."""


class ChironAPIError(Exception):
    """Raised for unexpected/unhandled API failures on calls that must succeed."""


class ChironClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 30.0,
        verbose: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.verbose = verbose
        self.session = requests.Session()
        self._authenticated = False

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[verbose] {msg}")

    # ------------------------------------------------------------------ auth
    def login(self) -> None:
        """Authenticate via Django session + CSRF. Raises ChironAuthError on
        failure, or requests.exceptions.RequestException if the server is
        unreachable."""
        login_url = f"{self.base_url}/accounts/login/"
        self._log(f"GET {login_url}")
        r = self.session.get(login_url, timeout=self.timeout)
        r.raise_for_status()

        csrf = self.session.cookies.get("csrftoken")
        if not csrf:
            raise ChironAuthError(
                f"No csrftoken cookie was set by GET {login_url}. "
                "This does not look like a Chiron login page - check --base-url."
            )

        self._log(f"POST {login_url} (username={self.username})")
        resp = self.session.post(
            login_url,
            data={
                "username": self.username,
                "password": self.password,
                "csrfmiddlewaretoken": csrf,
            },
            headers={"Referer": login_url},
            timeout=self.timeout,
            allow_redirects=False,
        )

        got_session_cookie = bool(self.session.cookies.get("sessionid"))
        if resp.status_code == 302 and got_session_cookie:
            self._authenticated = True
            self._log("Login succeeded (302 + sessionid cookie).")
            return

        raise ChironAuthError(
            f"Login failed for user '{self.username}' at {login_url}: "
            f"server returned HTTP {resp.status_code} and "
            f"{'did' if got_session_cookie else 'did not'} set a sessionid cookie "
            "(a successful login returns 302 and sets one). "
            "Check --username/--password/--base-url."
        )

    # -------------------------------------------------------------- internal
    def _get(self, path_or_url: str, params: Optional[dict] = None) -> requests.Response:
        if not self._authenticated:
            raise ChironAuthError("Not authenticated - call login() before making API calls.")
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        self._log(f"GET {url} params={params}")
        return self.session.get(url, params=params, timeout=self.timeout)

    # ---------------------------------------------------------------- reads
    def get_datasets(self) -> List[Dict[str, Any]]:
        r = self._get("/api/v2/dataset/")
        r.raise_for_status()
        return r.json().get("datasets", [])

    def get_dataset_detail(self, dataset_string: str) -> Dict[str, Any]:
        r = self._get(f"/api/v2/dataset/{dataset_string}/")
        r.raise_for_status()
        return r.json()

    def get_concepts(self, dataset_string: str, page_size: int = 100) -> List[Dict[str, Any]]:
        """Fetch ALL concepts for a dataset, following DRF's `next` pagination
        link until it is null. `next` is returned as a full absolute URL by
        this API, so subsequent requests are made directly against it (no
        params needed after the first page)."""
        concepts: List[Dict[str, Any]] = []
        url: Optional[str] = f"/api/v2/{dataset_string}/concepts/"
        params: Optional[dict] = {"page_size": page_size}
        while url:
            r = self._get(url, params=params)
            r.raise_for_status()
            data = r.json()
            concepts.extend(data.get("results", []))
            url = data.get("next")
            params = None
        return concepts

    def get_concept_statistics(
        self, dataset_string: str, permanent_id: str, prefilter_value: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Fetch one concept's detail + statistics.

        Returns (concept_detail, None) on success, or (concept_detail_or_None,
        error_message) when the statistics could not be retrieved. This never
        raises for the "expected" failure modes observed against a live
        Chiron server:
          - HTTP 403 (e.g. an aggregate-only user hitting a subject-level
            concept) -> (None, "<reason>")
          - HTTP 404 (bad dataset/concept id)      -> (None, "<reason>")
          - HTTP 200 with body {"statistics": {"error": "..."}} - this is how
            Chiron reports, in-band, permission problems for de-identified
            users AND missing-prefilter-value problems for concepts that have
            concept_for_prefilter set -> (concept_detail, "<error text>")
        Network-level errors (connection refused, timeout, ...) are also
        caught here and reported as an error string, rather than raised,
        because we do not want one flaky concept call to abort an entire
        dataset scan.
        """
        params = {"include_statistics": "true"}
        if prefilter_value is not None:
            params["prefilter_value"] = prefilter_value
        try:
            r = self._get(f"/api/v2/{dataset_string}/concepts/{permanent_id}/", params=params)
        except requests.exceptions.RequestException as exc:
            return None, f"network error: {exc}"

        if r.status_code == 403:
            return None, f"HTTP 403 permission denied: {_short(r.text)}"
        if r.status_code == 404:
            return None, f"HTTP 404 not found: {_short(r.text)}"
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            return None, f"HTTP {r.status_code}: {exc}"

        try:
            data = r.json()
        except ValueError:
            return None, f"non-JSON response (HTTP {r.status_code}): {_short(r.text)}"

        stats = data.get("statistics")
        if isinstance(stats, dict) and "error" in stats:
            return data, str(stats["error"])
        if stats is None:
            return data, "no 'statistics' key in response (include_statistics may not have been honored)"
        return data, None


def _short(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."
