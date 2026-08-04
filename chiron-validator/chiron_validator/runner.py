"""The validation runner.

Flow:
  1. **Discovery** — call a handful of live list endpoints to harvest real IDs
     (a concept ``permanent_id``, a category ``id``, a collection id, a report
     ``pk``, snapshot pks). These fill the ``{…}`` path placeholders so detail
     endpoints can be exercised without any knowledge of Chiron's DB.
  2. **Exercise** — for every testable endpoint, substitute path params, attach
     minimal synthetic query params/body, issue the request over the public API,
     and type-check the response field-by-field against the stored contract.
  3. **Record** — persist status, timing, pass/fail and every issue to the DB.

Safety: GET/HEAD reads and the non-mutating concept ``PUT`` run by default.
Creates/updates/deletes only run with ``include_writes`` / ``include_destructive``
so a default run never mutates the demo data.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import synthetic
from .client import ChironClient, Response
from .typecheck import check_response, Issue

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_]+)\}")


def _methods(method: str) -> list[str]:
    return [m.strip().upper() for m in method.replace("/", ",").split(",") if m.strip()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Runner:
    def __init__(self, db, client: ChironClient, dataset: str,
                 include_writes: bool = False, include_destructive: bool = False,
                 include_v1: bool = False, verbose: bool = False):
        self.db = db
        self.client = client
        self.dataset = dataset
        self.include_writes = include_writes
        self.include_destructive = include_destructive
        self.include_v1 = include_v1
        self.verbose = verbose
        self.ctx: dict[str, object] = {"dataset_string": dataset}

    # ---------- discovery ----------
    def discover(self) -> dict:
        c, ds = self.client, self.dataset
        log = {}

        # datasets (also confirms dataset id)
        r = c.get("/api/v2/dataset/")
        if r.json and isinstance(r.json, dict):
            for d in r.json.get("datasets", []):
                if d.get("name") == ds or d.get("unique_id") == ds:
                    self.ctx["dataset_pk"] = d.get("id")
            log["datasets"] = len(r.json.get("datasets", []))

        # concepts (paginated)
        r = c.get(f"/api/v2/{ds}/concepts/")
        results = self._as_list(r.json, "results")
        if results:
            self.ctx["concept_permanent_id"] = results[0].get("permanent_id")
            log["concepts"] = len(results)

        # concept categories -> {categories:[{id,...}]}
        r = c.get(f"/api/v2/{ds}/concept_categories/")
        cats = self._as_list(r.json, "categories")
        if cats:
            self.ctx["category_id"] = cats[0].get("id")
            log["categories"] = len(cats)

        # collections
        r = c.get(f"/api/v2/{ds}/collections/")
        cols = self._as_list(r.json, "results") or self._as_list(r.json, "collections")
        if cols and isinstance(cols[0], dict):
            self.ctx["collection_permanent_id"] = cols[0].get("permanent_id") or cols[0].get("id")
            log["collections"] = len(cols)

        # reports (viewable)
        r = c.get(f"/api/v2/{ds}/reports/viewable_reports/")
        reps = self._as_list(r.json, "results") or self._as_list(r.json, "reports")
        if not reps:
            r = c.get(f"/api/v2/{ds}/reports/")
            reps = self._as_list(r.json, "results")
        if reps and isinstance(reps[0], dict):
            self.ctx["report_pk"] = reps[0].get("id") or reps[0].get("pk")
            log["reports"] = len(reps)

        # snapshots (cohort/table/analysis def list -> pks if present)
        for res, pkkey in (("cohort_def", "cohort_pk"), ("table_def", "table_pk"),
                           ("analysis_def", "analysis_pk")):
            r = c.get(f"/api/v2/{ds}/{res}/")
            items = self._as_list(r.json, "results") or (r.json if isinstance(r.json, list) else None)
            if items and isinstance(items[0], dict):
                self.ctx[pkkey] = items[0].get("id") or items[0].get("pk")

        return log

    @staticmethod
    def _as_list(body, key):
        if body is None:
            return None
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            v = body.get(key)
            if isinstance(v, list):
                return v
        return None

    # ---------- path / param building ----------
    def _resolve_path(self, path: str, resource: str) -> tuple[str | None, str]:
        by_res = {
            "concepts": {"permanent_id": "concept_permanent_id"},
            "collections": {"permanent_id": "collection_permanent_id"},
            "concept_categories": {"id": "category_id"},
            "reports": {"pk": "report_pk"},
            "report_tools": {"pk": "report_pk"},
            "cohort_def": {"pk": "cohort_pk"},
            "table_def": {"pk": "table_pk"},
            "analysis_def": {"pk": "analysis_pk"},
            "datasets": {"pk": "dataset_pk"},
            "dataset": {"pk": "dataset_pk"},
        }
        mapping = by_res.get(resource, {})
        out = path
        for ph in PLACEHOLDER_RE.findall(path):
            if ph == "dataset_string":
                val = self.dataset
            else:
                ctx_key = mapping.get(ph)
                val = self.ctx.get(ctx_key) if ctx_key else None
            if val is None:
                return None, f"no test id available for path param '{{{ph}}}'"
            out = out.replace("{" + ph + "}", str(val))
        return out, ""

    def _required_query_params(self, request_contract: dict, resource: str) -> dict:
        known = {
            "search": "a", "concept_type": "cohort", "cohort_type": "cohort",
            "report_id": self.ctx.get("report_pk"),
            "output_type": "json",
        }
        params = {}
        for q in request_contract.get("query", []):
            if q.get("required"):
                name = q["name"]
                params[name] = known.get(name, synthetic.scalar_for_type(q.get("type", "string")))
        return params

    # ---------- exercise one endpoint ----------
    def _choose_call(self, ep) -> tuple[str | None, object, str]:
        """Return (method_to_call, body, skip_reason)."""
        ms = _methods(ep["method"])
        action = ep["action"]
        resource = ep["resource"]
        if "GET" in ms or "HEAD" in ms:
            return "GET", None, ""
        if "PUT" in ms and resource == "concepts":
            return "PUT", {}, ""  # non-mutating param passthrough
        if action == "create" or "POST" in ms:
            if not self.include_writes:
                return None, None, "write action — enable with --include-writes"
            body = self._synthetic_body(ep)
            return "POST", body, ""
        if "DELETE" in ms:
            if not self.include_destructive:
                return None, None, "destructive — enable with --include-destructive"
            return "DELETE", None, ""
        return None, None, f"no safe method among {ms}"

    def _synthetic_body(self, ep) -> object:
        resource = ep["resource"]
        if resource == "cohort_def":
            return synthetic.empty_cohort_def()
        if resource == "table_def":
            return synthetic.minimal_table_def(self.ctx.get("concept_permanent_id"))
        body = {}
        for f in json.loads(ep["request_json"]).get("body", []):
            if f.get("required"):
                body[f["name"]] = synthetic.scalar_for_type(f.get("type", "string"))
        return body

    def run_endpoint(self, run_id: int, ep) -> str:
        eid = ep["id"]
        if not ep["testable"]:
            self.db.record_result(run_id, eid, "", None, 0.0, True, ep["test_note"] or "not testable",
                                  None, [])
            return "skip"

        method, body, skip = self._choose_call(ep)
        if method is None:
            self.db.record_result(run_id, eid, "", None, 0.0, True, skip, None, [])
            return "skip"

        path, why = self._resolve_path(ep["path"], ep["resource"])
        if path is None:
            self.db.record_result(run_id, eid, "", None, 0.0, True, why, None, [])
            return "skip"

        request_contract = json.loads(ep["request_json"])
        params = self._required_query_params(request_contract, ep["resource"])

        resp: Response = self.client.request(method, path, json_body=body, params=params or None)

        issues: list[Issue] = []
        # Classification philosophy:
        #   2xx            -> type-check the payload (the real validation result: pass/fail)
        #   401/403/5xx/transport -> HARD FAIL (the endpoint should be reachable & healthy)
        #   404 / 400-precondition / 405 -> UNREACHED (stateful/edge; not a type-contract
        #                     verdict) so the pass-rate isn't polluted by "couldn't exercise".
        if resp.error:
            issues.append(Issue("transport_error", "error", "", resp.error, "", ""))
            passed = False
        elif resp.status in (401, 403):
            issues.append(Issue("auth_error", "error", "",
                                f"HTTP {resp.status}: {self._body_snippet(resp)} — expected authorised access",
                                "2xx", str(resp.status)))
            passed = False
        elif resp.status >= 500:
            issues.append(Issue("server_error", "error", "",
                                f"HTTP {resp.status} server error; body: {self._body_snippet(resp)}",
                                "2xx", str(resp.status)))
            passed = False
        elif resp.status == 404:
            issues.append(Issue("not_found", "warning", "",
                                f"HTTP 404 — {self._body_snippet(resp)}; path id may be stale/not-applicable",
                                "2xx", "404"))
            passed = None
        elif resp.status == 405:
            issues.append(Issue("method_not_allowed", "warning", "",
                                "HTTP 405 — method advertised but not dispatched",
                                "2xx", "405"))
            passed = None
        elif resp.status >= 400:
            issues.append(Issue("precondition", "warning", "",
                                f"HTTP {resp.status} — {self._body_snippet(resp)} (stateful precondition not met)",
                                "2xx", str(resp.status)))
            passed = None
        else:
            contract = json.loads(ep["contract_json"])
            issues = check_response(contract, resp.json if resp.json is not None else resp.text)
            passed = not any(i.severity == "error" for i in issues)

        # passed is None => record as "unreached" (skipped flag off, passed NULL) with a reason.
        skip_reason = "" if passed is not None else (issues[0].message if issues else f"HTTP {resp.status}")
        self.db.record_result(run_id, eid, resp.url or path, resp.status, resp.duration_ms,
                              False, skip_reason, passed, issues)
        if passed is None:
            return "unreached"
        return "pass" if passed else "fail"

    @staticmethod
    def _body_snippet(resp: Response) -> str:
        if resp.json is not None:
            s = json.dumps(resp.json)
        else:
            s = resp.text or ""
        return s[:160]

    # ---------- full run ----------
    def run(self, notes: str = "") -> dict:
        # Session auth (the way the browser UI authenticates) is required by
        # several v2 viewsets that reject HTTP Basic, so establish it up-front.
        if self.client.auth_mode == "session":
            self.client.login()
        run_id = self.db.start_run(_now(), self.client.base_url, self.dataset,
                                   self._chiron_version(), notes)
        disc = self.discover()
        if self.verbose:
            print("discovery:", disc, "ctx:", {k: v for k, v in self.ctx.items()})

        versions = ["v2"] + (["v1"] if self.include_v1 else [])
        if self.include_v1:
            self.client.login()
            if self.ctx.get("dataset_pk"):
                self.client.select_dataset(int(self.ctx["dataset_pk"]))

        eps = [e for e in self.db.endpoints() if e["version"] in versions]
        n_pass = n_fail = n_skip = n_unreached = 0
        for ep in eps:
            outcome = self.run_endpoint(run_id, ep)
            n_pass += outcome == "pass"
            n_fail += outcome == "fail"
            n_skip += outcome == "skip"
            n_unreached += outcome == "unreached"
            if self.verbose:
                print(f"  [{outcome:9}] {ep['version']} {ep['method']:9} {ep['path']}")

        # n_skipped stored = explicit skips + unreached (both are "not a type verdict")
        self.db.finish_run(run_id, _now(), len(eps), n_pass, n_fail, n_skip + n_unreached)
        return {"run_id": run_id, "endpoints": len(eps), "passed": n_pass,
                "failed": n_fail, "skipped": n_skip, "unreached": n_unreached, "discovery": disc}

    def _chiron_version(self) -> str:
        r = self.client.get("/api/version/")
        if r.json and isinstance(r.json, dict):
            return str(r.json.get("chiron", "unknown"))
        return "unknown"
