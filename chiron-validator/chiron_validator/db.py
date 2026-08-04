"""SQLite store for the validator.

Why a database (not loose schema files): the brief frames this as a "database
of type validations", and SQLite gives us three things at once with zero extra
dependencies:

  1. The **expectations** (endpoints + expected field types) in a queryable
     form — ``SELECT * FROM expected_field WHERE type='integer' AND nullable=1``.
  2. The **results** of every run in the same place, so correctness can be
     *tracked over time* (needed for the nightly scheduled run + dashboard in
     Task 7), not just printed once.
  3. A single self-contained file (``validator.db``) that is trivial to ship,
     inspect (``sqlite3 validator.db``), and back up.

The canonical, human-editable source of truth stays as JSON under ``specs/``;
``load_specs`` ingests it into the DB. The DB is a derived + results store.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS endpoint (
    id            INTEGER PRIMARY KEY,
    key           TEXT UNIQUE NOT NULL,      -- version|method|path|action
    version       TEXT NOT NULL,
    resource      TEXT NOT NULL,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    action        TEXT NOT NULL,
    purpose       TEXT,
    permissions   TEXT,
    response_kind TEXT,
    contract_json TEXT NOT NULL,             -- full response contract
    request_json  TEXT NOT NULL,             -- request body+query contract
    testable      INTEGER NOT NULL DEFAULT 1,
    test_note     TEXT,
    source_refs   TEXT
);

CREATE TABLE IF NOT EXISTS expected_field (
    id          INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL REFERENCES endpoint(id),
    section     TEXT NOT NULL,               -- response | request_body | request_query
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    nullable    INTEGER NOT NULL DEFAULT 0,
    required    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS run (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    base_url      TEXT NOT NULL,
    dataset       TEXT,
    chiron_version TEXT,
    n_endpoints   INTEGER DEFAULT 0,
    n_passed      INTEGER DEFAULT 0,
    n_failed      INTEGER DEFAULT 0,
    n_skipped     INTEGER DEFAULT 0,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS result (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES run(id),
    endpoint_id INTEGER NOT NULL REFERENCES endpoint(id),
    request_url TEXT,
    http_status INTEGER,
    duration_ms REAL,
    skipped     INTEGER NOT NULL DEFAULT 0,
    skip_reason TEXT,
    passed      INTEGER,
    n_error     INTEGER DEFAULT 0,
    n_warning   INTEGER DEFAULT 0,
    n_info      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS issue (
    id         INTEGER PRIMARY KEY,
    result_id  INTEGER NOT NULL REFERENCES result(id),
    code       TEXT NOT NULL,
    severity   TEXT NOT NULL,
    path       TEXT,
    message    TEXT,
    expected   TEXT,
    actual     TEXT
);

CREATE INDEX IF NOT EXISTS idx_result_run ON result(run_id);
CREATE INDEX IF NOT EXISTS idx_issue_result ON issue(result_id);
CREATE INDEX IF NOT EXISTS idx_field_endpoint ON expected_field(endpoint_id);
"""


class ValidatorDB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---- expectations ----
    def clear_specs(self):
        # Refresh expected fields only; endpoints are upserted (ON CONFLICT) so
        # historical `result` rows referencing them stay intact across reloads.
        with self.tx() as c:
            c.execute("DELETE FROM expected_field")

    def upsert_endpoint(self, spec: dict) -> int:
        contract = spec["response_contract"]
        request = spec.get("request_contract", {"body": [], "query": []})
        with self.tx() as c:
            cur = c.execute(
                """INSERT INTO endpoint
                   (key,version,resource,method,path,action,purpose,permissions,
                    response_kind,contract_json,request_json,testable,test_note,source_refs)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                     purpose=excluded.purpose, permissions=excluded.permissions,
                     response_kind=excluded.response_kind, contract_json=excluded.contract_json,
                     request_json=excluded.request_json, testable=excluded.testable,
                     test_note=excluded.test_note, source_refs=excluded.source_refs
                   RETURNING id""",
                (spec["key"], spec["version"], spec["resource"], spec["method"],
                 spec["path"], spec["action"], spec.get("purpose"), spec.get("permissions"),
                 contract.get("kind"), json.dumps(contract), json.dumps(request),
                 int(spec.get("testable", True)), spec.get("test_note"),
                 json.dumps(spec.get("source_refs", []))),
            )
            eid = cur.fetchone()[0]
            c.execute("DELETE FROM expected_field WHERE endpoint_id=?", (eid,))
            for f in contract.get("fields", []):
                c.execute("""INSERT INTO expected_field(endpoint_id,section,name,type,nullable,required)
                             VALUES (?,?,?,?,?,?)""",
                          (eid, "response", f["name"], f["type"],
                           int(f.get("nullable", False)), int(f.get("required", True))))
            for f in request.get("body", []):
                c.execute("""INSERT INTO expected_field(endpoint_id,section,name,type,nullable,required)
                             VALUES (?,?,?,?,?,?)""",
                          (eid, "request_body", f["name"], f["type"],
                           int(f.get("nullable", False)), int(f.get("required", False))))
            for f in request.get("query", []):
                c.execute("""INSERT INTO expected_field(endpoint_id,section,name,type,nullable,required)
                             VALUES (?,?,?,?,?,?)""",
                          (eid, "request_query", f["name"], f["type"], 0, int(f.get("required", False))))
        return eid

    def endpoints(self, version: str | None = None, testable_only: bool = False) -> list[sqlite3.Row]:
        q = "SELECT * FROM endpoint"
        clauses, args = [], []
        if version:
            clauses.append("version=?"); args.append(version)
        if testable_only:
            clauses.append("testable=1")
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY version, resource, path, method"
        return self.conn.execute(q, args).fetchall()

    def get_endpoint(self, key: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM endpoint WHERE key=?", (key,)).fetchone()

    # ---- runs / results ----
    def start_run(self, started_at: str, base_url: str, dataset: str, chiron_version: str, notes: str = "") -> int:
        with self.tx() as c:
            cur = c.execute(
                """INSERT INTO run(started_at,base_url,dataset,chiron_version,notes)
                   VALUES (?,?,?,?,?) RETURNING id""",
                (started_at, base_url, dataset, chiron_version, notes))
            return cur.fetchone()[0]

    def finish_run(self, run_id: int, finished_at: str, n_endpoints: int,
                   n_passed: int, n_failed: int, n_skipped: int):
        with self.tx() as c:
            c.execute("""UPDATE run SET finished_at=?, n_endpoints=?, n_passed=?, n_failed=?, n_skipped=?
                         WHERE id=?""",
                      (finished_at, n_endpoints, n_passed, n_failed, n_skipped, run_id))

    def record_result(self, run_id: int, endpoint_id: int, request_url: str, http_status,
                       duration_ms: float, skipped: bool, skip_reason: str,
                       passed, issues: list) -> int:
        n_error = sum(1 for i in issues if i.severity == "error")
        n_warning = sum(1 for i in issues if i.severity == "warning")
        n_info = sum(1 for i in issues if i.severity == "info")
        with self.tx() as c:
            cur = c.execute(
                """INSERT INTO result(run_id,endpoint_id,request_url,http_status,duration_ms,
                                      skipped,skip_reason,passed,n_error,n_warning,n_info)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (run_id, endpoint_id, request_url, http_status, duration_ms,
                 int(skipped), skip_reason, (None if passed is None else int(passed)),
                 n_error, n_warning, n_info))
            rid = cur.fetchone()[0]
            for iss in issues:
                c.execute("""INSERT INTO issue(result_id,code,severity,path,message,expected,actual)
                             VALUES (?,?,?,?,?,?,?)""",
                          (rid, iss.code, iss.severity, iss.path, iss.message, iss.expected, iss.actual))
        return rid

    def latest_run(self) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM run ORDER BY id DESC LIMIT 1").fetchone()

    def results_for_run(self, run_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT r.*, e.version,e.resource,e.method,e.path,e.action,e.response_kind
               FROM result r JOIN endpoint e ON e.id=r.endpoint_id
               WHERE r.run_id=? ORDER BY e.version,e.resource,e.path""", (run_id,)).fetchall()

    def issues_for_result(self, result_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM issue WHERE result_id=? ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END",
            (result_id,)).fetchall()
