# chiron-validator

A **database of type validations** for Chiron's public API. It derives the
expected request/response type of every field from Chiron's own DRF serializers
and Django models, stores those expectations in a queryable SQLite DB, then calls
the **live** Chiron API with synthetic data and checks every response
field-by-field against the expectations — flagging wrong types, missing/extra
fields, unexpected nulls, bad enums, wrong containers, and server errors.

> Standalone tool. Unrelated to any pre-existing `chiron-data-validator/` folder.

## Why it exists
Chiron ships **no OpenAPI/schema generator**, so there is no machine-checkable
contract for its ~120 endpoints. This tool builds one from the source-of-truth
(serializers/models), pins it, and continuously verifies the running service
against it. It found 5 endpoints that return HTTP 500 on ordinary reads (see the
generated `VALIDATOR_REPORT.md`).

## Design

```
specs/inventory.json   field-level inventory of every endpoint (from Chiron's
                       serializers/models) — the raw expectations
specs/overrides.json   hand-written, serializer-accurate contracts for the key
                       endpoints (strict). Override the auto-derived contracts.
        │  load_specs.py + normalize.py  (normalise types, build contracts)
        ▼
validator.db (SQLite)  endpoints + expected_field + run + result + issue
        │  runner.py  →  client.py (HTTP, public API only)  →  live Chiron
        │             →  typecheck.py (field-by-field engine)
        ▼
report.py  →  VALIDATOR_REPORT.md  +  reports/latest_run.json
```

**Why SQLite (not loose files):** the brief frames this as a "database of type
validations." SQLite gives (1) the expectations in a *queryable* form, (2) every
run's results in the *same* place so correctness is tracked over time (powers the
nightly health check + dashboard), and (3) a single self-contained file — with
zero extra dependencies. The human-editable source of truth stays as JSON under
`specs/`; the DB is the derived + results store.

**Two-tier contracts:** endpoints the runner exercises heavily have strict,
serializer-verified contracts in `overrides.json`. Everything else uses
auto-derived contracts that are deliberately *lenient* (type-check present fields
+ container shape only) so that a reported failure is a genuine problem, not
prose-imprecision noise.

**Type language** (see `typecheck.py`): `string | integer | number | boolean |
null | any`, string subtypes `string:iso8601|url|email`, containers `array |
array<T> | object`, `enum:a|b|c`, plus nested `object_fields` / `item_fields`.

## Install
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Usage
```bash
# 1. build the expectations DB from specs/
chiron-validator load

# 2. run against a live Chiron (defaults target the local dev instance)
chiron-validator run \
    --base-url http://127.0.0.1:8000 \
    --username admin --password demo1234 \
    --dataset dataset1_stored \
    [--include-v1] [--include-writes] [--include-destructive] [--fail-on-error]

# 3. re-render a report from any stored run
chiron-validator report [--run N]

# 4. ad-hoc query the validation DB
chiron-validator query "SELECT version, path, action FROM endpoint WHERE testable=0"
chiron-validator query "SELECT e.path, r.http_status FROM result r
                        JOIN endpoint e ON e.id=r.endpoint_id
                        WHERE r.run_id=(SELECT max(id) FROM run) AND r.passed=0"
```
Environment variables `CHIRON_BASE_URL`, `CHIRON_USER`, `CHIRON_PASSWORD`,
`CHIRON_DATASET` are honoured as defaults (useful for CI / scheduled runs).

Auth defaults to **session** (like the browser UI); several v2 viewsets reject
HTTP Basic. Use `--auth basic` to demonstrate that inconsistency.

## Tests
```bash
.venv/bin/python -m pytest -q      # 24 unit tests for the type engine + normaliser
```

## Layout
| Path | What |
|------|------|
| `chiron_validator/typecheck.py` | field-by-field type-checking engine |
| `chiron_validator/normalize.py` | type-string normaliser + contract builder |
| `chiron_validator/db.py` | SQLite store (expectations + results) |
| `chiron_validator/load_specs.py` | ingest specs → DB |
| `chiron_validator/client.py` | HTTP client (public API only; Basic + session) |
| `chiron_validator/synthetic.py` | synthetic payloads / data provenance |
| `chiron_validator/runner.py` | discovery + exercise + record orchestrator |
| `chiron_validator/report.py` | Markdown + JSON report rendering |
| `chiron_validator/cli.py` | `chiron-validator` command |
| `specs/` | `inventory.json`, `overrides.json` |
| `tests/` | unit tests |
