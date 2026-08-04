# Chiron — Architecture & API Overview

_Task 1 + Task 2 deliverable. Produced by reading both repos end-to-end and
running the system locally. The endpoint/model reference (sections 3–5) is
generated from a machine-readable inventory (`chiron-validator/inventory.json`)
built by fanning out deep source reads across every viewset, serializer, and
model; it is reused verbatim to seed the validator's expected-schema database
in Task 3._

Repos in scope:
- **`is4r-chiron-develop/`** — backend. A reusable Django app (`chiron`) plus a
  runnable demo Django project (`test_project/`).
- **`is4r-chiron-ui-develop/`** — frontend. React 19 + Vite 7 + Redux Toolkit +
  MUI SPA (TypeScript, pnpm).

> The pre-existing `chiron-data-validator/` folder is **out of scope** per the
> brief and was not touched.

---

## 1. Architecture summary

Chiron is a **data-exploration / reporting tool for human-subject research
data** (longitudinal, patient-centric). A research team defines *concepts*
(queryable variables) over their source data; end users build *cohorts*
(subject filters), *table definitions* (columns to pull), and *analyses*, then
save and share *reports* and export data.

### 1.1 Component layout

```
                         ┌─────────────────────────────┐
  Browser (SPA)          │  is4r-chiron-ui  (Vite/React)│
  localhost:3000  ──────▶│  Redux slices → APIRequest() │
                         └───────────────┬──────────────┘
                              /api/v2/... │ (vite proxy in dev; nginx in prod)
                                          ▼
                         ┌─────────────────────────────┐
  Django + DRF           │  chiron app (viewsets, query │
  localhost:8000  ──────▶│  engine, processors, ETL)    │
                         └───────┬─────────────┬────────┘
                                 │             │
              Django ORM (metadata)      SQLAlchemy (data warehouse)
                                 │             │
                        ┌────────▼───┐   ┌─────▼──────────────────────┐
                        │ SQLite     │   │ PostgreSQL "chiron"         │
                        │ db.sqlite3 │   │ schemas: datasetN_stored    │
                        │ concepts,  │   │ the actual research/patient │
                        │ reports,   │   │ data (encounters, labs, …)  │
                        │ users, …   │   └─────────────────────────────┘
                        └────────────┘
```

### 1.2 Two databases (the single most important architectural fact)

Chiron keeps **metadata and data physically separate**:

1. **Metadata DB** — Django ORM. In the demo it is SQLite
   (`test_project/db.sqlite3`). Holds Chiron's own models: `Concept`,
   `Collection`, `Category`, `Dataset`, `ChironUser`, `PermissionGroup`, the
   `*Snapshot` definitions, `UserCreatedContent` (reports), ETL logs, caches.
2. **Data warehouse** — PostgreSQL, reached through **SQLAlchemy** (not the
   Django ORM), configured via `CHIRON_SQL_ALCHEMY_CONNECTION_STRING`. Each
   dataset lives in its own Postgres **schema** (`dataset1_stored`,
   `dataset2_stored`, `dataset3_stored`). This is where the real subject data
   sits, in per-concept tables (`encounter`, `lab_result`, `lkp_*` lookups,
   `col_rel_*` collection-relationship tables, `concept_search`, …).

Query building (cohorts, table pulls, analyses) compiles concept definitions
into SQLAlchemy queries against the appropriate `datasetN_stored` schema. This
separation is why the validator (Task 3) can, and must, treat Chiron as a black
box over HTTP — the "data" it returns comes from a completely different engine
than the metadata that shapes it.

### 1.3 Backend internals (the `chiron` package)

| Module | Role |
|--------|------|
| `api/` (v1), `api_v2/` | DRF viewsets + serializers + permissions. Two API surfaces (see §2). |
| `models/` | Django ORM metadata models — `data_definition_models`, `user_models`, `log_models`, `processor_models`, `cache_models`. |
| `query_definition/` | Turns saved cohort/table/analysis JSON into structured query objects (`Cohort`, `Table`). |
| `query_engine/` | Executes those against the SQLAlchemy data warehouse. |
| `processors/` | Pluggable per-concept-type logic: form options, statistics, SQL fragments, callbacks. Registered via `CHIRON_PROCESSOR_MODULES`. |
| `etl/` | Loads source data into the `datasetN_stored` schemas. |
| `data_dictionary/` | Concept/collection definition + autocreate. |
| `cache/`, `models/cache_models` | Optional cached concept stats / cohorts (`CHIRON_USE_CACHES`, off in demo). |
| `authorization.py`, `middleware/view_as_other_user.py` | Identity resolution + admin impersonation. |
| `management/commands/` | ETL, caching, backup/restore, index creation, etc. |

### 1.4 Frontend internals (the UI)

- **State:** Redux Toolkit slices — `authSlice`, `cohortSlice`, `criteriaSetSlice`,
  `tableSlice`, `aggregateSlice`, `reportSlice`, `reportsSlice`.
- **API layer:** `src/api/index.ts` exposes `APIRequest(method, url, data)` and
  `APIFileRequest(...)` (CSV download). `fetch` with `credentials:"include"`,
  JSON bodies, and Matomo (`_paq`) response-time tracking baked into every call.
- **Config:** `src/config.tsx` + `overrideConfig.tsx`. `apiBaseUrl` is empty by
  default; dev uses the Vite proxy (`vite.config.ts`) to forward `/api`,
  `/admin`, `/accounts`, `/backend`, `/ajax`, `/static` to `:8000`.
- **Routes:** dataset select → dataset home → Query / Results / Reports /
  Aggregate. The UI targets **`/api/v2/` only**.

---

## 2. The two API surfaces

Both are DRF routers mounted in `chiron/urls.py`:

- **v1 — `/api/…`** (flat). `DefaultRouter` over: `chiron_users`, `me`,
  `collections`, `concepts`, `concept_categories`, `cohort_def`, `table_def`,
  `analysis_def`, `query_tools`, `analysis_tools`, `project`, `reports`,
  `report_tools`, `version`. Active dataset comes from the **Django session**
  (`DatasetSelector` permission reads `session['dataset_id']`).
- **v2 — `/api/v2/…`** (dataset-scoped). `DefaultRouter` where almost every
  resource is prefixed by `(?P<dataset_string>.+)/` so the dataset is in the
  **URL**, resolved by `DatasetUrlPermission`. Adds top-level `auth` and
  `dataset`. Resources mirror v1 plus `get_report`/`viewable_reports`.

v2 viewsets typically **subclass** their v1 counterparts and change only the
permission class (session→URL dataset) and, in a few cases, tighten the
queryset. The React UI uses v2 exclusively; v1 remains registered and callable.

**Data flow for a typical query:** UI loads `/api/v2/auth/` → `/api/v2/dataset/`
→ user picks a dataset → `concept_categories` + `concepts` populate the query
builder → user composes filters → `POST cohort_def/` saves a snapshot and
`query_tools/count` + `query_tools/preview` return live counts/rows from the
Postgres warehouse → `table_def` + `report_tools`/`reports` save & export.

## 3. API endpoint inventory (master list)

Total distinct endpoints inventoried: **127** (52 v2, 56 v1, 19 non-API/server-rendered).

| # | Ver | Method | Path | Action | Auth |
|---|-----|--------|------|--------|------|
| 1 | v2 | GET | `/api/v2/{dataset_string}/analysis_def/` | list | ? |
| 2 | v2 | POST | `/api/v2/{dataset_string}/analysis_def/` | create | ? |
| 3 | v2 | GET/POST | `/api/v2/{dataset_string}/analysis_def/associated_concept_ids/` | associated_concept_ids | ? |
| 4 | v2 | GET | `/api/v2/{dataset_string}/analysis_def/{pk}/` | retrieve | ? |
| 5 | v2 | GET | `/api/v2/{dataset_string}/analysis_tools/` | list | ? |
| 6 | v2 | GET/POST | `/api/v2/{dataset_string}/analysis_tools/export_csv/` | export_csv | ? |
| 7 | v2 | GET/POST | `/api/v2/{dataset_string}/analysis_tools/run_analysis/` | run_analysis | ? |
| 8 | v2 | GET | `/api/v2/auth/` | list | ? |
| 9 | v2 | GET | `/api/v2/{dataset_string}/cohort_def/` | list | ? |
| 10 | v2 | POST | `/api/v2/{dataset_string}/cohort_def/` | create | ? |
| 11 | v2 | GET | `/api/v2/{dataset_string}/cohort_def/{pk}/` | retrieve | ? |
| 12 | v2 | GET | `/api/v2/{dataset_string}/collections/` | list | ? |
| 13 | v2 | GET | `/api/v2/{dataset_string}/collections/{permanent_id}/` | retrieve | ? |
| 14 | v2 | GET | `/api/v2/{dataset_string}/concept_categories/` | list | ? |
| 15 | v2 | GET | `/api/v2/{dataset_string}/concept_categories/concept_search/` | concept_search | ? |
| 16 | v2 | GET | `/api/v2/{dataset_string}/concept_categories/{id}/` | retrieve | ? |
| 17 | v2 | GET | `/api/v2/{dataset_string}/concepts/` | list | ? |
| 18 | v2 | GET | `/api/v2/{dataset_string}/concepts/{permanent_id}/` | retrieve | ? |
| 19 | v2 | PUT | `/api/v2/{dataset_string}/concepts/{permanent_id}/` | update | ? |
| 20 | v2 | GET | `/api/v2/{dataset_string}/concepts/{permanent_id}/cohort_def_callback/` | cohort_def_callback | ? |
| 21 | v2 | GET | `/api/v2/{dataset_string}/concepts/{permanent_id}/cohort_def_callback_streaming/` | cohort_def_callback_streaming | ? |
| 22 | v2 | GET | `/api/v2/dataset/` | list | ? |
| 23 | v2 | GET | `/api/v2/dataset/{pk}/` | retrieve | ? |
| 24 | v2 | GET | `/api/v2/{dataset_string}/query_tools/` | list | ? |
| 25 | v2 | GET, POST | `/api/v2/{dataset_string}/query_tools/count/` | count | ? |
| 26 | v2 | GET, POST | `/api/v2/{dataset_string}/query_tools/export_csv/` | export_csv | ? |
| 27 | v2 | GET, POST | `/api/v2/{dataset_string}/query_tools/preview/` | preview | ? |
| 28 | v2 | GET, POST | `/api/v2/{dataset_string}/query_tools/preview_metadata/` | preview_metadata | ? |
| 29 | v2 | GET | `/api/v2/{dataset_string}/report_tools/` | list | ? |
| 30 | v2 | GET | `/api/v2/{dataset_string}/report_tools/{pk}/` | retrieve | ? |
| 31 | v2 | GET | `/api/v2/{dataset_string}/report_tools/{pk}/export_csv/` | export_csv | ? |
| 32 | v2 | GET | `/api/v2/{dataset_string}/report_tools/{pk}/export_json/` | export_json | ? |
| 33 | v2 | POST | `/api/v2/{dataset_string}/report_tools/{pk}/load_as_active/` | load_as_active | ? |
| 34 | v2 | GET | `/api/v2/{dataset_string}/report_tools/{pk}/preview/` | preview | ? |
| 35 | v2 | POST | `/api/v2/{dataset_string}/report_tools/{pk}/share/` | share | ? |
| 36 | v2 | GET | `/api/v2/{dataset_string}/reports/` | list | ? |
| 37 | v2 | POST | `/api/v2/{dataset_string}/reports/` | create | ? |
| 38 | v2 | GET/POST | `/api/v2/{dataset_string}/reports/create_form/` | create_form | ? |
| 39 | v2 | GET | `/api/v2/{dataset_string}/reports/get_report/` | get_report | ? |
| 40 | v2 | GET | `/api/v2/{dataset_string}/reports/viewable_reports/` | viewable_reports | ? |
| 41 | v2 | DELETE | `/api/v2/{dataset_string}/reports/{id}/` | destroy | ? |
| 42 | v2 | GET | `/api/v2/{dataset_string}/reports/{id}/` | retrieve | ? |
| 43 | v2 | PATCH | `/api/v2/{dataset_string}/reports/{id}/` | partial_update | ? |
| 44 | v2 | PUT | `/api/v2/{dataset_string}/reports/{id}/` | update | ? |
| 45 | v2 | GET/POST | `/api/v2/{dataset_string}/reports/{id}/delete_form/` | delete_form | ? |
| 46 | v2 | GET/POST | `/api/v2/{dataset_string}/reports/{id}/edit_form/` | edit_form | ? |
| 47 | v2 | POST | `/api/v2/{dataset_string}/reports/{id}/flag/` | flag | ? |
| 48 | v2 | GET/POST | `/api/v2/{dataset_string}/reports/{id}/share_form/` | share_form | ? |
| 49 | v2 | GET | `/api/v2/{dataset_string}/table_def/` | list | ? |
| 50 | v2 | POST | `/api/v2/{dataset_string}/table_def/` | create | ? |
| 51 | v2 | GET/POST | `/api/v2/{dataset_string}/table_def/associated_concept_ids/` | associated_concept_ids | ? |
| 52 | v2 | GET | `/api/v2/{dataset_string}/table_def/{pk}/` | retrieve | ? |
| 53 | v1 | GET | `/api/analysis_def/` | list | ? |
| 54 | v1 | POST | `/api/analysis_def/` | create | ? |
| 55 | v1 | GET/POST | `/api/analysis_def/associated_concept_ids/` | associated_concept_ids | ? |
| 56 | v1 | GET | `/api/analysis_def/{pk}/` | retrieve | ? |
| 57 | v1 | GET | `/api/analysis_tools/` | list | ? |
| 58 | v1 | GET/POST | `/api/analysis_tools/export_csv/` | export_csv | ? |
| 59 | v1 | GET/POST | `/api/analysis_tools/run_analysis/` | run_analysis | ? |
| 60 | v1 | GET | `/api/chiron_users/` | list | ? |
| 61 | v1 | GET | `/api/chiron_users/{id}/` | retrieve | ? |
| 62 | v1 | GET | `/api/cohort_def/` | list | ? |
| 63 | v1 | POST | `/api/cohort_def/` | create | ? |
| 64 | v1 | GET | `/api/cohort_def/{pk}/` | retrieve | ? |
| 65 | v1 | GET | `/api/collections/` | list | ? |
| 66 | v1 | GET | `/api/collections/{permanent_id}/` | retrieve | ? |
| 67 | v1 | GET | `/api/concept_categories/` | list | ? |
| 68 | v1 | GET | `/api/concept_categories/{id}/` | retrieve | ? |
| 69 | v1 | GET | `/api/concepts/` | list | ? |
| 70 | v1 | GET | `/api/concepts/{permanent_id}/` | retrieve | ? |
| 71 | v1 | PUT | `/api/concepts/{permanent_id}/` | update | ? |
| 72 | v1 | GET | `/api/concepts/{permanent_id}/cohort_def_callback/` | cohort_def_callback | ? |
| 73 | v1 | GET | `/api/concepts/{permanent_id}/cohort_def_callback_streaming/` | cohort_def_callback_streaming | ? |
| 74 | v1 | GET | `/api/me/` | list | ? |
| 75 | v1 | GET | `/api/project/` | list | ? |
| 76 | v1 | POST | `/api/project/` | create | ? |
| 77 | v1 | DELETE | `/api/project/{id}/` | destroy | ? |
| 78 | v1 | GET | `/api/project/{id}/` | retrieve | ? |
| 79 | v1 | PATCH | `/api/project/{id}/` | partial_update | ? |
| 80 | v1 | PUT | `/api/project/{id}/` | update | ? |
| 81 | v1 | GET | `/api/query_tools/` | list | ? |
| 82 | v1 | GET, POST | `/api/query_tools/count/` | count | ? |
| 83 | v1 | GET, POST | `/api/query_tools/export_csv/` | export_csv | ? |
| 84 | v1 | GET, POST | `/api/query_tools/preview/` | preview | ? |
| 85 | v1 | GET, POST | `/api/query_tools/preview_metadata/` | preview_metadata | ? |
| 86 | v1 | GET | `/api/report_tools/` | list | ? |
| 87 | v1 | GET | `/api/report_tools/{pk}/` | retrieve | ? |
| 88 | v1 | GET | `/api/report_tools/{pk}/export_csv/` | export_csv | ? |
| 89 | v1 | GET | `/api/report_tools/{pk}/export_json/` | export_json | ? |
| 90 | v1 | POST | `/api/report_tools/{pk}/load_as_active/` | load_as_active | ? |
| 91 | v1 | GET | `/api/report_tools/{pk}/preview/` | preview | ? |
| 92 | v1 | POST | `/api/report_tools/{pk}/share/` | share | ? |
| 93 | v1 | GET | `/api/reports/` | list | ? |
| 94 | v1 | POST | `/api/reports/` | create | ? |
| 95 | v1 | GET/POST | `/api/reports/create_form/` | create_form | ? |
| 96 | v1 | DELETE | `/api/reports/{id}/` | destroy | ? |
| 97 | v1 | GET | `/api/reports/{id}/` | retrieve | ? |
| 98 | v1 | PATCH | `/api/reports/{id}/` | partial_update | ? |
| 99 | v1 | PUT | `/api/reports/{id}/` | update | ? |
| 100 | v1 | GET/POST | `/api/reports/{id}/delete_form/` | delete_form | ? |
| 101 | v1 | GET/POST | `/api/reports/{id}/edit_form/` | edit_form | ? |
| 102 | v1 | POST | `/api/reports/{id}/flag/` | flag | ? |
| 103 | v1 | GET/POST | `/api/reports/{id}/share_form/` | share_form | ? |
| 104 | v1 | GET | `/api/table_def/` | list | ? |
| 105 | v1 | POST | `/api/table_def/` | create | ? |
| 106 | v1 | GET/POST | `/api/table_def/associated_concept_ids/` | associated_concept_ids | ? |
| 107 | v1 | GET | `/api/table_def/{pk}/` | retrieve | ? |
| 108 | v1 | GET | `/api/version/` | list | ? |
| 109 | non-api | GET | `/ajax/export_data/get_add_id_field_form` | ajax_get_add_id_field_form | ? |
| 110 | non-api | GET | `/ajax/export_data/get_td_resort_form` | ajax_get_td_resort_form | ? |
| 111 | non-api | GET | `/ajax/set_data_view_mode` | ajax_set_data_view_mode | ? |
| 112 | non-api | GET | `/ajax/get_view_mode_selector` | ajax_view_mode_widget | ? |
| 113 | non-api | GET | `/backend/data_dictionary` | data_dictionary | ? |
| 114 | non-api | GET | `/backend/etl_logs/<int:log_id>` | etl_log_details | ? |
| 115 | non-api | GET | `/backend/etl_logs` | etl_logs | ? |
| 116 | non-api | GET | `/` | home | ? |
| 117 | non-api | GET | `/backend/query_troubleshooting` | query_troubleshooting | ? |
| 118 | non-api | GET | `/backend/etl_logs/<int:log_id>/subject/<str:subject_id>` | record_logs_for_subject | ? |
| 119 | non-api | GET | `/report/<int:report_id>` | report | ? |
| 120 | non-api | GET | `/reports` | reports | ? |
| 121 | non-api | GET, POST | `/select_dataset` | select_dataset | ? |
| 122 | non-api | GET | `/backend/source_logs/<int:source_log_id>/data_issues` | source_data_issues | ? |
| 123 | non-api | GET | `/backend/source_logs/<int:source_log_id>/subject_matching` | source_record_subject_matching | ? |
| 124 | non-api | GET | `/backend/stop_viewing_as_user` | stop_viewing_as_user | ? |
| 125 | non-api | GET, POST | `/backend/user_report` | user_report | ? |
| 126 | non-api | GET, POST | `/backend/view_schema` | view_schema | ? |
| 127 | non-api | GET | `/workspace` | workspace | ? |

## 4. Field-level request / response types

Grouped by API version and resource. `T` = wire type. For request/response fields, types are derived from DRF serializers, model fields, and observed `Response(...)` payloads; inferred types are marked in notes.


### v2 · `analysis_def`

#### GET `/api/v2/{dataset_string}/analysis_def/` — list

Inherited from v1 AnalysisDefViewSet.list unchanged. Active analysis_def for chironuser resolved from dataset_string.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, AnalysisViewOn, CanViewWorkspacePermission
- **Response (object):**
  - `analysis_def`: `object` (non-null) — Same as v1 list; {} if no active snapshot
  - `extended_analysis_def`: `object` (non-null) — Same as v1
  - `warnings`: `array[str]` (non-null) — 
  - `errors`: `array[str]` (non-null) — 
  - `snapshot_id`: `int` (non-null) — 
  - `previous_snapshot_id`: `int` (nullable) — 
  - `next_snapshot_id`: `int` (nullable) — 
- **Source:** `chiron/api_v2/viewsets/analysis_def.py:11-21`, `chiron/api/viewsets/analysis_def.py:40-75`

#### POST `/api/v2/{dataset_string}/analysis_def/` — create

Inherited from v1 AnalysisDefViewSet.create unchanged. Applies transformation, persists snapshot.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, AnalysisViewOn, CanViewWorkspacePermission
- **Request body fields:**
  - `transformation`: `object` (required) — Same as v1; required, 'type' selects transform
  - `analysis_def`: `object` (optional) — Optional; active used if omitted
- **Response (object):**
  - `transformation_successful`: `bool` (non-null) — 
  - `analysis_def`: `object` (non-null) — 
  - `transformation_errors`: `array[str]` (non-null) — On failure only
  - `extended_analysis_def`: `object` (non-null) — On success only
  - `warnings`: `array[str]` (non-null) — On success only
  - `errors`: `array[str]` (non-null) — On success only
  - `snapshot_id`: `int` (non-null) — On success only
  - `previous_snapshot_id`: `int` (nullable) — On success only
  - `next_snapshot_id`: `int` (nullable) — On success only
- **Source:** `chiron/api_v2/viewsets/analysis_def.py:11-21`, `chiron/api/viewsets/analysis_def.py:111-162`

#### GET/POST `/api/v2/{dataset_string}/analysis_def/associated_concept_ids/` — associated_concept_ids

Inherited from v1. Concept ids referenced in analysis def.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, AnalysisViewOn, CanViewWorkspacePermission
- **Query params:**
  - `analysis_def`: `str(json)` (optional) — GET param optional
- **Request body fields:**
  - `analysis_def`: `object` (optional) — POST body optional
- **Response (object):**
  - `concept_ids`: `array[str]` (non-null) — Unique concept ids
- **Source:** `chiron/api_v2/viewsets/analysis_def.py:11-21`, `chiron/api/viewsets/analysis_def.py:176-187`

#### GET `/api/v2/{dataset_string}/analysis_def/{pk}/` — retrieve

OVERRIDDEN in v2. Retrieve specific snapshot scoped to request.chironuser (AnalysisDefSnapshot.objects.filter(chironuser=...)). Optionally set active.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, AnalysisViewOn, CanViewWorkspacePermission. Snapshot filtered by chironuser (differs from v1)
- **Query params:**
  - `set_to_active`: `bool/str` (optional) — Default False; truthy sets active
- **Response (object):**
  - `analysis_def`: `object` (non-null) — 
  - `extended_analysis_def`: `object` (non-null) — 
  - `warnings`: `array[str]` (non-null) — 
  - `errors`: `array[str]` (non-null) — 
  - `snapshot_id`: `int` (non-null) — 
  - `previous_snapshot_id`: `int` (nullable) — 
  - `next_snapshot_id`: `int` (nullable) — 
- **Source:** `chiron/api_v2/viewsets/analysis_def.py:23-57`


### v2 · `analysis_tools`

#### GET `/api/v2/{dataset_string}/analysis_tools/` — list

OVERRIDDEN in v2. Returns dict of hyperlinks to sub-actions, rewriting the v1 URL prefix (/api/) to the v2 dataset-scoped prefix (/api/v2/<dataset>/).

- **Permissions:** IsAuthenticated, DatasetUrlPermission, AnalysisViewOn, CanViewWorkspacePermission
- **Response (object):**
  - `run_analysis`: `str(url)` (non-null) — v2 URL: <v2-list-url>+'preview_metadata'. Same 'preview_metadata' vs actual 'run_analysis' route mismatch as v1
  - `export_csv`: `str(url)` (non-null) — v2 URL: <v2-list-url>+'export_csv'
- **Source:** `chiron/api_v2/viewsets/analysis_tools.py:10-27`

#### GET/POST `/api/v2/{dataset_string}/analysis_tools/export_csv/` — export_csv

Inherited from v1 AnalysisToolsViewSet.export_csv unchanged. CSV export for the URL dataset.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, AnalysisViewOn, CanViewWorkspacePermission
- **Query params:**
  - `use_active_cohort`: `bool/str` (optional) — default True
  - `cohort_def`: `str(json)` (optional) — GET
  - `analysis_def`: `str(json)` (optional) — GET
- **Request body fields:**
  - `cohort_def`: `array/object` (optional) — POST body optional
  - `analysis_def`: `object` (optional) — POST body optional
  - `use_active_cohort`: `bool/str` (optional) — default True
- **Response (csv):**
  - `(body)`: `text/csv` (non-null) — CSV attachment; PermissionDenied on cohort validation errors
- **Source:** `chiron/api_v2/viewsets/analysis_tools.py:10-18`, `chiron/api/viewsets/analysis_tools.py:97-127`

#### GET/POST `/api/v2/{dataset_string}/analysis_tools/run_analysis/` — run_analysis

Inherited from v1 AnalysisToolsViewSet.run_analysis unchanged. Run pivottable analysis for the URL dataset.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, AnalysisViewOn, CanViewWorkspacePermission
- **Query params:**
  - `data_view_mode`: `str` (optional) — default 'active'
  - `cohort_def`: `str(json)` (optional) — GET; convert_to_obj
  - `analysis_def`: `str(json)` (optional) — GET (see open question re _get_analysis_def key check)
- **Request body fields:**
  - `cohort_def`: `array/object` (optional) — POST body optional; else active
  - `analysis_def`: `object` (optional) — POST body optional; else active
  - `data_view_mode`: `str` (optional) — default 'active'; 'all' => empty cohort
- **Response (object):**
  - `dataset`: `object` (nullable) — {columns,index,data} or null
  - `cohort_def`: `array/object` (non-null) — Echoed
  - `analysis_def`: `object` (non-null) — Echoed
  - `pivot_table_html`: `str` (non-null) — HTML table or ''
- **Source:** `chiron/api_v2/viewsets/analysis_tools.py:10-18`, `chiron/api/viewsets/analysis_tools.py:45-95`


### v2 · `auth`

#### GET `/api/v2/auth/` — list

Return the logged-in user's identity and the running Chiron version. Used by the React UI to determine auth/login state. AllowAny: works for anonymous users too.

- **Permissions:** AllowAny (permission_classes=[AllowAny], auth.py:16). No pagination. Default host authentication (session).
- **Response (object):**
  - `user`: `object\|null` (nullable) — null when request.user is not authenticated (chiron/api_v2/viewsets/auth.py:25-26). Otherwise the nested object below.
  - `user.id`: `int` (non-null) — Django User.id. AuthUserSerializer.id IntegerField (serializers/auth.py:5).
  - `user.username`: `str` (non-null) — AuthUserSerializer.username CharField (serializers/auth.py:6).
  - `user.isStaff`: `bool` (non-null) — user.is_staff; can view admin. BooleanField (serializers/auth.py:7).
  - `user.name`: `str` (non-null) — user.get_full_name(); may be empty string if no first/last name set. CharField (serializers/auth.py:8).
  - `user.email`: `str` (non-null) — CharField (serializers/auth.py:9).
  - `chironVersion`: `str` (non-null) — 'v' + installed chiron package version, e.g. 'v1.2.3'; falls back to 'v0.0.0' if importlib version lookup fails (auth.py:20-22).
- **Source:** `chiron/api_v2/viewsets/auth.py:10-41`, `chiron/api_v2/serializers/auth.py:4-9,35-37`, `chiron/api_v2/urls.py:7`, `chiron/urls.py:102`


### v2 · `cohort_def`

#### GET `/api/v2/{dataset_string}/cohort_def/` — list

V2 dataset-scoped variant of cohort_def list. Inherits CohortDefViewSet.list unchanged; overrides get_queryset (unused by list) and permissions. Returns active cohort def for the user.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission. dataset_string in URL identifies the dataset.
- **Response (object):**
  - `cohort_def`: `array` (non-null) — Same shape as v1 list.
  - `extended_cohort_def`: `array` (non-null) — See ExtendedCriteriaSet.
  - `describe`: `string` (non-null) — HTML summary.
  - `warnings`: `array[string]` (non-null) — 
  - `errors`: `array[string]` (non-null) — 
  - `snapshot_id`: `integer` (nullable) — None if no active snapshot.
  - `previous_snapshot_id`: `integer` (nullable) — 
  - `next_snapshot_id`: `integer` (nullable) — 
- **Source:** `chiron/api_v2/viewsets/cohort_def.py:9`, `chiron/api_v2/urls.py:10`, `chiron/api/viewsets/cohort_def.py:39`

#### POST `/api/v2/{dataset_string}/cohort_def/` — create

V2 dataset-scoped variant of cohort_def create (apply transformation + save active snapshot). Identical body/response to v1 create.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission.
- **Request body fields:**
  - `transformation`: `object` (required) — Required; see v1 create for full type list and per-type keys. Missing -> HTTP 400 {}.
  - `cohort_def`: `array` (optional) — Optional; active def used if omitted.
- **Response (object):**
  - `transformation_successful`: `boolean` (non-null) — 
  - `cohort_def`: `array` (non-null) — Original on failure; new on success.
  - `transformation_errors`: `array[string]` (non-null) — Failure only.
  - `transformation_warnings`: `array[string]` (non-null) — Failure only.
  - `entry_id`: `string` (nullable) — add_entry success only.
  - `extended_cohort_def`: `array` (non-null) — Success only.
  - `warnings`: `array[string]` (non-null) — Success only.
  - `errors`: `array[string]` (non-null) — Success only.
  - `describe`: `string` (non-null) — Success only.
  - `snapshot_id`: `integer` (non-null) — Success only.
  - `previous_snapshot_id`: `integer` (nullable) — Success only.
  - `next_snapshot_id`: `integer` (nullable) — Success only.
- **Source:** `chiron/api_v2/viewsets/cohort_def.py:9`, `chiron/api/viewsets/cohort_def.py:109`

#### GET `/api/v2/{dataset_string}/cohort_def/{pk}/` — retrieve

V2 dataset-scoped retrieve of a specific CohortDefSnapshot. Behavior identical to v1 retrieve.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `set_to_active`: `boolean` (optional) — Default False; if truthy sets the snapshot active.
- **Response (object):**
  - `cohort_def`: `array` (non-null) — 
  - `extended_cohort_def`: `array` (non-null) — 
  - `describe`: `string` (non-null) — 
  - `warnings`: `array[string]` (non-null) — 
  - `errors`: `array[string]` (non-null) — 
  - `snapshot_id`: `integer` (non-null) — get_object_or_404 -> non-null.
  - `previous_snapshot_id`: `integer` (nullable) — 
  - `next_snapshot_id`: `integer` (nullable) — 
- **Source:** `chiron/api_v2/viewsets/cohort_def.py:9`, `chiron/api/viewsets/cohort_def.py:76`


### v2 · `collections`

#### GET `/api/v2/{dataset_string}/collections/` — list

List collections for the URL-scoped dataset, ordered by name. Read-only (inherits v1 ReadOnlyModelViewSet). Optional filter by parent collection or event-based only.

- **Permissions:** IsAuthenticated + DatasetUrlPermission. Dataset resolved from URL dataset_string (Dataset.unique_id); requires ChironUser for it. Queryset scoped to chironuser.dataset. chiron/api_v2/viewsets/collection.py:15,31
- **Query params:**
  - `collection`: `string` (optional) — A collection permanent_id (scoped to the user's dataset). Then filters queryset with .filter(collection=selected_collection). NOTE: Collection has no 'collection' field; filter is likely dead/buggy. chiron/api_v2/viewsets/collection.py:36-42
  - `show`: `string` (optional) — If ='event', filter to collections with event_date_field not null. chiron/api_v2/viewsets/collection.py:44-46
- **Response (array):**
  - `[]`: `array` (non-null) — Plain (non-paginated) JSON array of CollectionSerializer objects; pagination_class=None. Each item: permanent_id(str), name(str), get_name_plural(str), is_root_collection(bool), has_event(bool). chiron/api_v2/viewsets/collection.py:16; chiron/api/serializers.py:142
- **Source:** `chiron/api_v2/viewsets/collection.py:11`, `chiron/api_v2/viewsets/collection.py:23`, `chiron/api_v2/urls.py:34`, `chiron/urls.py:102`, `chiron/api_v2/permissions.py:7`

#### GET `/api/v2/{dataset_string}/collections/{permanent_id}/` — retrieve

Retrieve one collection (scoped to URL dataset) by permanent_id. Optionally augment with cohort-def criteria-set options / event options.

- **Permissions:** IsAuthenticated + DatasetUrlPermission (dataset from URL). Object fetched via get_object_or_404 on dataset-scoped queryset. chiron/api_v2/viewsets/collection.py:67
- **Query params:**
  - `include_criteria_set_options`: `boolean` (optional) — Default False (string_to_bool). If truthy adds criteria_set_options; requires criteria_set_entry_id. chiron/api_v2/viewsets/collection.py:71
  - `include_criteria_set_event_options`: `boolean` (optional) — Default False (string_to_bool). If truthy adds criteria_set_event_options; requires criteria_set_entry_id. chiron/api_v2/viewsets/collection.py:72-74
  - `criteria_set_entry_id`: `string` (optional) — entry_id of criteria set in active cohort def. Required (else ValueError) if either options flag truthy. chiron/api_v2/viewsets/collection.py:79-81
- **Response (object):**
  - `permanent_id`: `string` (non-null) — CollectionSerializer (same shape as v1 retrieve).
  - `name`: `string` (non-null) — Collection.name.
  - `get_name_plural`: `string` (non-null) — name_plural or name+'s'.
  - `is_root_collection`: `boolean` (non-null) — self == dataset.root_collection.
  - `has_event`: `boolean` (non-null) — event_date_field is not None.
  - `criteria_set_options`: `array` (non-null) — Present only if include_criteria_set_options truthy. Same 2-dict structure as v1. chiron/api_v2/viewsets/collection.py:83-85 -> inherited _get_criteria_set_options (chiron/api/viewsets/collection.py:114)
  - `criteria_set_event_options`: `object` (non-null) — Present only if include_criteria_set_event_options truthy. {event_options: array, selected_event_option: str}. chiron/api_v2/viewsets/collection.py:86-88 -> inherited _get_criteria_set_event_options (chiron/api/viewsets/collection.py:148)
  - `criteria_set_entry_id`: `string` (non-null) — Echoed; present only if either options flag truthy. chiron/api_v2/viewsets/collection.py:89
- **Source:** `chiron/api_v2/viewsets/collection.py:51`, `chiron/api/serializers.py:142`


### v2 · `concept_categories`

#### GET `/api/v2/{dataset_string}/concept_categories/` — list

Return top-level categories (parent is null) and category-less concepts for the dataset, filtered by concept_type and user permissions. Inherited from v1 ConceptCategoryViewSet._fetch_concepts_and_categories. Not paginated.

- **Permissions:** IsAuthenticated, DatasetUrlPermission
- **Query params:**
  - `concept_type`: `string` (optional) — cohort\|table\|analysis; filters both categories and concepts; default None returns all
- **Response (object):**
  - `category_id`: `string` (non-null) — Literal 'top' for the list action
  - `categories`: `array<CategorySerializer>` (non-null) — Each: id(int), name(str), parent_id(int\|null), get_level(int); depth=1
  - `concepts`: `array<ConceptSerializer>` (non-null) — v1 ConceptSerializer (no pk field): permanent_id, concept_type, name, get_name_plural, description, get_additional_metadata, collection(permanent_id), collection_name, collection_name_plural, source, concept_for_prefilter, prefilter_mode, category_hierarchy, order, published, include_in_cohort_def, include_in_table_def, include_in_analysis_def, has_phi
- **Source:** `chiron/api_v2/viewsets/concept_category.py:11`, `chiron/api/viewsets/concept_category.py:42`, `chiron/api/viewsets/concept_category.py:112`, `chiron/api/serializers.py:72`

#### GET `/api/v2/{dataset_string}/concept_categories/concept_search/` — concept_search

Search published concepts across the dataset by search term and concept_type. @action(detail=False). v2-only (not present in v1 base).

- **Permissions:** IsAuthenticated, DatasetUrlPermission
- **Query params:**
  - `search`: `string` (required) — Search term -> stattool.get_concept_search_ids
  - `concept_type`: `string` (optional) — cohort\|table\|analysis; filters include_in_*_def
- **Response (object):**
  - `search`: `string` (non-null) — str(search_param) echoed back
  - `concepts`: `array<ConceptSerializer>` (non-null) — v1 ConceptSerializer(many=True), published concepts matching search
- **Source:** `chiron/api_v2/viewsets/concept_category.py:22`

#### GET `/api/v2/{dataset_string}/concept_categories/{id}/` — retrieve

Return direct child categories and concepts of the given Category pk. Inherited ReadOnlyModelViewSet.retrieve override. Not paginated. {id} = Category primary key (DRF default pk lookup).

- **Permissions:** IsAuthenticated, DatasetUrlPermission
- **Query params:**
  - `concept_type`: `string` (optional) — cohort\|table\|analysis; default None
- **Response (object):**
  - `category_id`: `int` (non-null) — The provided Category pk (int; 'top' only for list)
  - `categories`: `array<CategorySerializer>` (non-null) — Direct child categories (id, name, parent_id, get_level)
  - `concepts`: `array<ConceptSerializer>` (non-null) — Concepts with category pk == id, published, permission-filtered (v1 ConceptSerializer)
- **Source:** `chiron/api_v2/viewsets/concept_category.py:11`, `chiron/api/viewsets/concept_category.py:128`


### v2 · `concepts`

#### GET `/api/v2/{dataset_string}/concepts/` — list

List concepts for a dataset (queryset filtered to collection__dataset__unique_id=dataset_string), further filtered by query params and per-object user_can_view_concept_stats permission. Paginated.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `collection`: `string` (optional) — Collection permanent_id; 404 if not found
  - `category`: `int` (optional) — Category id; ParseError if non-int, 404 if not found
  - `search`: `string` (optional) — Full-text search via stattool.get_concept_search_ids
  - `show_unpublished`: `boolean` (optional) — default False; when False filters published=True
  - `concept_type`: `string` (optional) — cohort\|table; filters include_in_cohort_def / include_in_table_def
  - `page`: `int` (optional) — PageNumberPagination
  - `page_size`: `int` (optional) — default 100, max 1000
- **Response (paginated):**
  - `count`: `int` (non-null) — DRF pagination wrapper
  - `next`: `string(url)` (nullable) — pagination
  - `previous`: `string(url)` (nullable) — pagination
  - `results`: `array<ConceptSerializer>` (non-null) — Each item = ConceptSerializer (v2, includes pk): permanent_id(str), concept_type(str), name(str), get_name_plural(str), description(str\|null), get_additional_metadata(list[str]), collection(str=permanent_id), collection_name(str), collection_name_plural(str), source(int\|null), concept_for_prefilter(ConceptRelated\|null), prefilter_mode(str required\|optional), category_hierarchy(list[Category]), order(float), published(bool), include_in_cohort_def(bool), include_in_table_def(bool), include_in_analysis_def(bool), has_phi(bool), pk(int)
- **Source:** `chiron/api_v2/viewsets/concept.py:33`, `chiron/api_v2/viewsets/concept.py:54`, `chiron/api_v2/viewsets/concept.py:117`, `chiron/api_v2/serializers/concept.py:25`, `chiron/api_v2/urls.py:8`

#### GET `/api/v2/{dataset_string}/concepts/{permanent_id}/` — retrieve

Retrieve one concept (by permanent_id, scoped to dataset_string); optionally augment with cohort_def_options, table_def_options, statistics, callback_data. Returns bare object (not paginated).

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `prefilter_value`: `string` (optional) — Required when concept.concept_for_prefilter is set; echoed back in response
  - `include_cohort_def_options`: `boolean` (optional) — default False; adds cohort_def_options via processor.get_form_options
  - `include_table_def_options`: `boolean` (optional) — default False; adds table_def_options
  - `include_statistics`: `boolean` (optional) — default False; adds statistics via processor.get_statistics
  - `callback`: `boolean` (optional) — default False; adds callback_data via processor.form_callback
  - `cohort_def`: `string(JSON)` (optional) — JSON-encoded cohort def; used by option/stat helpers; falls back to active cohort def
  - `table_def`: `string(JSON)` (optional) — v2-only in _get_table_def_options; falls back to active table def
  - `show_all_data`: `boolean` (optional) — Ignore cohort_def, compute over all subjects
  - `cohort_def_entry_id`: `int` (optional) — Edit existing cohort def entry when generating options
  - `table_def_entry_id`: `int` (optional) — Edit existing table def entry when generating options
- **Response (object):**
  - `<ConceptSerializer fields>`: `object` (non-null) — All ConceptSerializer(v2) fields (see list endpoint). concept_for_prefilter may get a nested cohort_def_options added when include_cohort_def_options set
  - `cohort_def_options`: `object` (non-null) — Present only if include_cohort_def_options; dynamic processor form options (processor-specific); may include entry_id
  - `table_def_options`: `object` (non-null) — Present only if include_table_def_options; dynamic processor form options incl criteria_set_options(list), selected_aggregation_criteria_set, entry_alias, optional entry_id
  - `statistics`: `object` (non-null) — Present only if include_statistics; dynamic stat payload, or {error: reason} if no view perm, or {error:'You must provide a prefilter value.'}
  - `callback_data`: `object` (non-null) — Present only if callback; dynamic processor.form_callback output, or {error:...} when prefilter missing
  - `prefilter_value`: `string` (nullable) — Always added; echoes prefilter_value query param (null if absent)
- **Source:** `chiron/api_v2/viewsets/concept.py:137`, `chiron/api_v2/viewsets/concept.py:231`, `chiron/api_v2/viewsets/concept.py:260`, `chiron/api_v2/viewsets/concept.py:301`

#### PUT `/api/v2/{dataset_string}/concepts/{permanent_id}/` — update

Same as retrieve but accepts long params in the request body (PUT). Reads augmentation flags from request.data instead of query params. Not a real write; returns the (optionally augmented) serialized concept.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `(helper params)`: `mixed` (optional) — Helper methods still read query_params (cohort_def, show_all_data, *_entry_id) via request.query_params
- **Request body fields:**
  - `include_statistics`: `boolean` (optional) — If truthy, adds statistics
  - `include_cohort_def_options`: `boolean` (optional) — If truthy, adds cohort_def_options
  - `prefilter_value`: `string` (optional) — Read from body when include_cohort_def_options set
  - `callback`: `boolean` (optional) — If truthy, adds callback_data
- **Response (object):**
  - `<ConceptSerializer fields>`: `object` (non-null) — All ConceptSerializer(v2) fields
  - `statistics`: `object` (non-null) — Present only if include_statistics truthy
  - `cohort_def_options`: `object` (non-null) — Present only if include_cohort_def_options truthy
  - `callback_data`: `object` (non-null) — Present only if callback truthy. NOTE: unlike retrieve, update does not add prefilter_value or table_def_options
- **Source:** `chiron/api_v2/viewsets/concept.py:52`, `chiron/api_v2/viewsets/concept.py:197`

#### GET `/api/v2/{dataset_string}/concepts/{permanent_id}/cohort_def_callback/` — cohort_def_callback

Run the concept processor's form_callback and return its data. @action(detail=True). Declares GET+POST but POST is blocked (see notes).

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `cohort_def`: `string(JSON)` (optional) — Falls back to active cohort def
  - `show_all_data`: `boolean` (optional) — Empties cohort_def_for_display when true
  - `prefilter_value`: `string` (optional) — 404 if concept.prefilter_required() and missing
  - `(processor params)`: `mixed` (optional) — processor.form_callback(request.GET, ...) consumes arbitrary GET params (processor-specific, e.g. pagination)
- **Response (object):**
  - `<processor form_callback data>`: `object` (non-null) — Dynamic, processor-specific dict
  - `is_callback`: `boolean` (non-null) — Always True
  - `permanent_id`: `string` (non-null) — Echoes the concept permanent_id
- **Source:** `chiron/api_v2/viewsets/concept.py:218`, `chiron/api_v2/viewsets/concept.py:342`

#### GET `/api/v2/{dataset_string}/concepts/{permanent_id}/cohort_def_callback_streaming/` — cohort_def_callback_streaming

Streaming variant of cohort_def_callback: StreamingHttpResponse yielding JSON dicts joined by literal separator '**split**'. @action(detail=True). Declares GET+POST but POST blocked.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `cohort_def`: `string(JSON)` (optional) — Falls back to active cohort def
  - `show_all_data`: `boolean` (optional) — same as callback
  - `(processor params)`: `mixed` (optional) — processor.form_callback_streaming(request.GET, ...)
- **Response (other):**
  - `(stream)`: `text/stream` (non-null) — Concatenated json.dumps(make_json_encodable(chunk)) segments separated by '**split**'; each chunk dict includes is_callback=True and permanent_id plus processor data
- **Source:** `chiron/api_v2/viewsets/concept.py:225`, `chiron/api_v2/viewsets/concept.py:378`


### v2 · `datasets`

#### GET `/api/v2/dataset/` — list

List all datasets visible to the logged-in user, flagging which are selectable (user has a ChironUser or autocreate is on). Hides non-list_visible datasets the user cannot access.

- **Permissions:** IsAuthenticated only. Iterates all Dataset objects; no per-dataset ChironUser required to list (visibility governed by list_visible/autocreate). chiron/api_v2/viewsets/datasets.py:19
- **Response (object):**
  - `datasets`: `array` (non-null) — DatasetListSerializers wraps under 'datasets' key; NOT DRF-paginated. Array of per-dataset objects with the 7 fields below. chiron/api_v2/viewsets/datasets.py:44-46; chiron/api_v2/serializers/auth.py:32
  - `datasets[].id`: `integer` (non-null) — Dataset.id (pk). chiron/api_v2/viewsets/datasets.py:35
  - `datasets[].name`: `string` (non-null) — Dataset.display_name.
  - `datasets[].description`: `string` (nullable) — Dataset.description (TextField, blank/null).
  - `datasets[].siteTitle`: `string` (nullable) — Dataset.override_site_title (CharField, blank/null).
  - `datasets[].unique_id`: `string` (non-null) — Dataset.unique_id (SlugField, unique).
  - `datasets[].selectable`: `boolean` (non-null) — True if user has a ChironUser for the dataset OR dataset.autocreate_chiron_user; else False. chiron/api_v2/viewsets/datasets.py:24-32
  - `datasets[].contactEmail`: `string(email)` (non-null) — Dataset.contact_email (EmailField, may be empty string). chiron/api_v2/viewsets/datasets.py:41
- **Source:** `chiron/api_v2/viewsets/datasets.py:21`, `chiron/api_v2/urls.py:41`, `chiron/urls.py:102`, `chiron/api_v2/serializers/auth.py:11,29`

#### GET `/api/v2/dataset/{pk}/` — retrieve

Retrieve summary/access info for one dataset (pk is Dataset.unique_id) for the current user, including access level, subject count, last import date, and UI config.

- **Permissions:** IsAuthenticated; then manual get_request_chironuser(request, dataset) check -> PermissionDenied (403) if user has no ChironUser for the dataset. Dataset fetched via get_object_or_404 on unique_id=pk. chiron/api_v2/viewsets/datasets.py:49-57
- **Response (object):**
  - `id`: `integer` (non-null) — Dataset.id. DatasetSerializer. chiron/api_v2/viewsets/datasets.py:63
  - `name`: `string` (non-null) — Dataset.display_name.
  - `unique_id`: `string` (non-null) — Dataset.unique_id.
  - `description`: `string` (nullable) — Dataset.description (nullable). Serializer CharField(required=False).
  - `lastImport`: `string` (non-null) — get_summary_data 'Date of last import': 'mm/dd/YYYY' or 'Unknown'. Serializer CharField. chiron/views/views.py:30-32
  - `subjectCount`: `string` (non-null) — get_summary_data 'Total subjects in system': intcomma-formatted count string (e.g. '1,234'). Serializer CharField. chiron/views/views.py:37
  - `accessLevelLabel`: `string` (non-null) — get_summary_data 'Your Access Level' = chironuser.get_access_level_display() (human-readable). chiron/views/views.py:48
  - `accessLevel`: `string` (non-null) — ChironUser.access_level raw value: one of 'phi','deid','agg'. chiron/api_v2/viewsets/datasets.py:65; Dataset.AccessLevel choices data_definition_models.py:43
  - `canViewWorkspace`: `boolean` (non-null) — ChironUser.can_view_workspace.
  - `canViewSubjectDetails`: `boolean` (non-null) — ChironUser.can_view_subject_details.
  - `logoUrl`: `string` (nullable) — Dataset.logo_url (URLField, blank/null). Serializer CharField.
  - `chironUserId`: `integer` (non-null) — ChironUser.pk. chiron/api_v2/viewsets/datasets.py:69
  - `extraHeaderLinks`: `json` (nullable) — Dataset.extra_header_links (JSONField, blank/null); object mapping header text->url. Serializer JSONField(required=False). chiron/api_v2/viewsets/datasets.py:70
- **Source:** `chiron/api_v2/viewsets/datasets.py:49`, `chiron/api_v2/serializers/auth.py:11`, `chiron/views/views.py:26`


### v2 · `query_tools`

#### GET `/api/v2/{dataset_string}/query_tools/` — list

V2 dataset-scoped discovery endpoint. Inherits QueryToolsViewSet.list. NOTE: URLs are built with reverse('chiron:api:query_tools-list'), so the returned links point at the V1 (/api/) surface, not v2.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission.
- **Response (object):**
  - `count`: `string` (non-null) — V1-namespaced absolute URL (quirk: not dataset-scoped).
  - `preview_metadata`: `string` (non-null) — V1-namespaced URL.
  - `preview`: `string` (non-null) — V1-namespaced URL.
  - `export_csv`: `string` (non-null) — V1-namespaced URL.
- **Source:** `chiron/api_v2/viewsets/query_tools.py:7`, `chiron/api_v2/urls.py:24`, `chiron/api/viewsets/query_tools.py:34`

#### GET, POST `/api/v2/{dataset_string}/query_tools/count/` — count

V2 dataset-scoped subject count for the active cohort. Identical logic to v1 count.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
- **Request body fields:**
  - `cohort_def`: `array` (optional) — Documented but ignored; active snapshot used.
- **Response (object):**
  - `count`: `string` (non-null) — str(cohort count).
  - `cohort_def`: `array` (non-null) — Active cohort def used.
- **Source:** `chiron/api_v2/viewsets/query_tools.py:7`, `chiron/api/viewsets/query_tools.py:44`

#### GET, POST `/api/v2/{dataset_string}/query_tools/export_csv/` — export_csv

V2 dataset-scoped CSV export for active cohort + table def. Identical to v1 export_csv.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
  - `table_def`: `object` (optional) — Documented but ignored.
- **Request body fields:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
  - `table_def`: `object` (optional) — Documented but ignored.
- **Response (csv):**
  - `(file)`: `text/csv` (non-null) — CSV HTTP response. 403 PermissionDenied if cohort has errors.
- **Source:** `chiron/api_v2/viewsets/query_tools.py:7`, `chiron/api/viewsets/query_tools.py:73`

#### GET, POST `/api/v2/{dataset_string}/query_tools/preview/` — preview

V2 dataset-scoped paginated data preview. Identical to v1 preview; custom ReportPaginator.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `page`: `integer` (optional) — Default 1.
  - `records_per_page`: `integer` (optional) — Default 10.
  - `output_type`: `string` (optional) — Default 'json'.
- **Request body fields:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
  - `table_def`: `object` (optional) — Documented but ignored.
  - `page`: `integer` (optional) — Default 1.
  - `records_per_page`: `integer` (optional) — Default 10.
  - `output_type`: `string` (optional) — Default 'json'; html/json/csv.
- **Response (object):**
  - `warnings`: `array[string]` (non-null) — 
  - `errors`: `array[string]` (non-null) — 
  - `preview_failed`: `boolean` (non-null) — Present (True) only on error.
  - `extended_table_def`: `array` (non-null) — Always present.
  - `record_count`: `integer` (non-null) — Success only.
  - `subject_count`: `integer` (non-null) — Success only.
  - `paginator`: `object` (non-null) — Success only; first_index,last_index,current_page,previous_page,next_page,last_page,total_records.
  - `data`: `array` (non-null) — Success only; 2D array of strings or {link,value} objects.
  - `perf`: `object` (nullable) — Only if CHIRON_GET_QUERY_PERFORMANCE.
  - `cache_mode`: `string` (nullable) — Only if CHIRON_GET_QUERY_PERFORMANCE.
- **Source:** `chiron/api_v2/viewsets/query_tools.py:7`, `chiron/api/viewsets/query_tools.py:144`

#### GET, POST `/api/v2/{dataset_string}/query_tools/preview_metadata/` — preview_metadata

V2 dataset-scoped preview metadata (no data query). Identical to v1 preview_metadata.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
  - `table_def`: `object` (optional) — Documented but ignored.
- **Request body fields:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
  - `table_def`: `object` (optional) — Documented but ignored.
- **Response (object):**
  - `warnings`: `array[string]` (non-null) — 
  - `errors`: `array[string]` (non-null) — 
  - `extended_table_def`: `array` (non-null) — 
  - `preview_failed`: `boolean` (non-null) — Present (True) only on error.
  - `pipeline`: `string` (non-null) — Success only; DEPRECATED literal string.
- **Source:** `chiron/api_v2/viewsets/query_tools.py:7`, `chiron/api/viewsets/query_tools.py:98`


### v2 · `report_tools`

#### GET `/api/v2/{dataset_string}/report_tools/` — list

Return a map of report_tools action URLs (dataset-scoped rewrite of the v1 URLs).

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess
- **Response (object):**
  - `share`: `string` (non-null) — URL template '.../report_tools/[pk]/share'.
  - `load_as_active`: `string` (non-null) — URL template.
  - `preview`: `string` (non-null) — URL template.
  - `export_csv`: `string` (non-null) — URL template.
  - `export_json`: `string` (non-null) — URL template.
- **Source:** `chiron/api_v2/viewsets/report_tools.py:30`

#### GET `/api/v2/{dataset_string}/report_tools/{pk}/` — retrieve

Return report_tools action URLs for a specific report pk.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess
- **Response (object):**
  - `share`: `string` (non-null) — '.../{pk}/share'.
  - `load_as_active`: `string` (non-null) — '.../{pk}/load_as_active'.
  - `preview`: `string` (non-null) — '.../{pk}/preview'.
  - `export_csv`: `string` (non-null) — '.../{pk}/export_csv'. NOTE: retrieve omits export_json (unlike list).
- **Source:** `chiron/api_v2/viewsets/report_tools.py:43`

#### GET `/api/v2/{dataset_string}/report_tools/{pk}/export_csv/` — export_csv

Stream a CSV of the full report dataset. Filename = slug(name)_YYYY-MM-DD.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess
- **Response (csv):**
  - `(file)`: `text/csv` (non-null) — HttpResponse from export_utils.generate_cohort_csv (not JSON). Attachment.
- **Source:** `chiron/api_v2/viewsets/report_tools.py:132`

#### GET `/api/v2/{dataset_string}/report_tools/{pk}/export_json/` — export_json

Return the full report dataset as JSON (shape depends on output_type) via export_utils.generate_cohort_json.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess
- **Query params:**
  - `output_type`: `string` (optional) — 'html'\|'json'\|'csv'; default 'json'. Reads request.GET (or request.data if not GET).
- **Response (other):**
  - `(payload)`: `object/array` (non-null) — Output of export_utils.generate_cohort_json; structure varies with output_type. Type inferred (not declared in viewset).
- **Source:** `chiron/api_v2/viewsets/report_tools.py:153`

#### POST `/api/v2/{dataset_string}/report_tools/{pk}/load_as_active/` — load_as_active

Set the report's cohort_def/table_def as the active CohortDefSnapshot/TableDefSnapshot for the user, clearing snapshot history.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess
- **Response (object):**
  - `(empty)`: `object` (non-null) — Response({}) — empty object.
- **Source:** `chiron/api_v2/viewsets/report_tools.py:105`

#### GET `/api/v2/{dataset_string}/report_tools/{pk}/preview/` — preview

Return a paginated preview of the report's dataset (via export_utils.get_paginated_preview). Optional runtime sort override.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess
- **Query params:**
  - `sort_field`: `string` (optional) — table_def entry_id to sort by; replaces table_def['sort'] (report_tools.py:216).
  - `sort_direction`: `integer` (optional) — Default 1.
  - `output_type`: `string` (optional) — 'html'\|'json'\|'csv'; default 'json' (per docstring).
  - `records_per_page`: `integer` (optional) — Default 10 (per docstring); consumed inside get_paginated_preview.
  - `page`: `integer` (optional) — Default 1.
- **Response (object):**
  - `record_count`: `integer` (non-null) — Success. From get_paginated_preview (types per docstring).
  - `subject_count`: `integer` (non-null) — Success.
  - `page_number_current`: `integer` (non-null) — Success.
  - `page_number_max`: `integer` (non-null) — Success.
  - `page_first_index`: `integer` (non-null) — Success; index of first record on page.
  - `page_last_index`: `integer` (non-null) — Success; index of last record on page.
  - `extended_table_def`: `array` (non-null) — Present in both success and fail.
  - `data`: `array<array<string>>` (nullable) — Success only; 2D array of record strings.
  - `warnings`: `array<string>` (non-null) — Present in success and fail.
  - `preview_failed`: `boolean` (nullable) — Fail only; True.
  - `errors`: `array<string>` (nullable) — Fail only.
  - `report_id`: `integer` (non-null) — Added by viewset (report_tools.py:229): oContent.id.
- **Source:** `chiron/api_v2/viewsets/report_tools.py:176`

#### POST `/api/v2/{dataset_string}/report_tools/{pk}/share/` — share

Replace all sharing for a report with the supplied ChironUser id list; only the creator may call. Emails newly-added sharees when notifications enabled.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess; plus PermissionDenied unless request.chironuser == report.creator
- **Request body fields:**
  - `(request body)`: `array<integer>` (required) — Raw JSON array of ChironUser ids parsed via json.loads(request.body) (report_tools.py:67). Not a named field. Existing ContentSharing rows for this content are deleted then recreated. V2 additionally scopes the report lookup to request.dataset.
- **Response (object):**
  - `(empty)`: `object` (non-null) — Response({}) — empty object.
- **Source:** `chiron/api_v2/viewsets/report_tools.py:55`


### v2 · `reports`

#### GET `/api/v2/{dataset_string}/reports/` — list

List reports (UserCreatedContent type=table) viewable by the requesting ChironUser in the dataset. Paginated.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Query params:**
  - `state`: `string` (optional) — One of shared_only\|public_only\|mine\|starred; any other value raises 404 NotFound. Filters queryset (report.py:200-215).
  - `project_id`: `integer` (optional) — Filter reports by project FK (report.py:217).
  - `search`: `string` (optional) — icontains match on name OR description (report.py:221).
  - `page_size`: `integer` (optional) — Default 1000, max 10000 (LargeResultsSetPagination).
  - `page`: `integer` (optional) — DRF PageNumberPagination page number.
- **Response (paginated):**
  - `count`: `integer` (non-null) — Total across pages (PageNumberPagination wrapper).
  - `next`: `string` (nullable) — URL of next page or null.
  - `previous`: `string` (nullable) — URL of previous page or null.
  - `results`: `array<object>` (non-null) — Array of UserCreatedContentSerializer objects (see create/retrieve response_fields).
- **Source:** `chiron/api_v2/viewsets/report.py:50`, `chiron/api_v2/viewsets/report.py:185`, `chiron/api/utils/pagination.py:6`

#### POST `/api/v2/{dataset_string}/reports/` — create

Create a report. creator_id and dataset_id are forced from request context in serializer.validate().

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (required) — Required (CharField).
  - `type`: `string` (required) — Must be 'cohort' or 'table' else ValidationError (serializers.py:241).
  - `project`: `integer` (optional) — Project FK pk; nullable.
  - `description`: `string` (optional) — Nullable text.
  - `definition`: `string` (optional) — JSON string; if present, cohort_def is normalized via Cohort() then re-dumped (serializers.py:226-234).
  - `public`: `boolean` (optional) — Default True.
- **Response (object):**
  - `id`: `integer` (non-null) — Full UserCreatedContentSerializer returned (same fields as retrieve).
- **Source:** `chiron/api/serializers.py:180`, `chiron/api/serializers.py:216`

#### GET/POST `/api/v2/{dataset_string}/reports/create_form/` — create_form

Detail-false. GET returns blank ReportForm data (JSON); POST validates+saves a new type=table report from active cohort/table snapshots and optionally emails sharees. V2 returns JSON form data (v1 returns rendered HTML).

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (required) — ReportForm field (UserCreatedContent.name).
  - `description`: `string` (optional) — ReportForm field.
  - `project`: `integer` (optional) — Project pk; empty allowed.
  - `project_other`: `string` (optional) — New project name; if project empty and this set, a Project is created (ui_forms.py:64).
  - `public`: `boolean` (optional) — Checkbox.
  - `share_with`: `array<integer>` (optional) — ChironUser ids (CheckboxSelectMultiple); AGG-access or cross-dataset users rejected.
  - `dataset`: `integer` (optional) — HiddenInput; seeded from request.dataset via initial.
- **Response (form-json):**
  - `status`: `string` (non-null) — 'complete' on POST success else 'incomplete'.
  - `title`: `string` (nullable) — 'Save Current Results View as a Report' (incomplete only).
  - `errors`: `array<string>` (non-null) — [fContent.errors.as_text()].
  - `onSuccess`: `string` (nullable) — 'chiron.manager.reportCreated' (POST success only).
  - `data`: `object` (nullable) — Incomplete only: {fForm:{shared_options:[{username:str,user_id:int,checked:bool}], project_selection:[{label:str,value:int}]}, oReports:[{label:str,value:int}]}.
- **Source:** `chiron/api_v2/viewsets/report.py:320`, `chiron/forms/ui_forms.py:6`

#### GET `/api/v2/{dataset_string}/reports/get_report/` — get_report

Detail-false custom action. Builds cohort/table defs for a report and returns a display context (used to render a report view). Enforces get_viewable_reports().

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission; additionally raises PermissionDenied if report not in get_viewable_reports()
- **Query params:**
  - `report_id`: `integer` (required) — pk looked up via get_object_or_404 (report.py:70).
  - `page`: `integer` (optional) — Default 1.
  - `sort_field`: `string` (optional) — table_def entry_id to sort by; injected at front of sort list.
  - `sort_direction`: `integer` (optional) — Default 1.
- **Response (object):**
  - `current_page`: `string` (non-null) — Constant 'reports'.
  - `oReport`: `object` (non-null) — {name:str, creator:str, created:datetime, description:str\|null, public:str (sharing description), id:int}.
  - `extended_cohort_def`: `object/array` (non-null) — From qdef.Cohort.extended_cohort_def; structure not typed here.
  - `cohort_description`: `array/object` (non-null) — qdef.describe_cohort_def output.
  - `warnings`: `array<string>` (non-null) — cohort.warnings.
  - `errors`: `array<string>` (non-null) — cohort.errors.
  - `full_url`: `string` (non-null) — Absolute URI to chiron:report.
  - `extended_table_def`: `array/object` (non-null) — table.extended_table_def.
  - `td_warnings`: `array<string>` (non-null) — table.warnings.
  - `td_errors`: `array<string>` (non-null) — table.errors.
  - `custom_sort_string`: `string` (non-null) — '' or '&sort_field=..&sort_direction=..'.
  - `cohort_def_interactive`: `boolean` (non-null) — Constant False.
  - `page`: `integer` (non-null) — Echoed page.
  - `sort_field`: `string` (nullable) — Echoed; None if not provided.
  - `sort_direction`: `integer` (non-null) — Echoed.
- **Source:** `chiron/api_v2/viewsets/report.py:68`

#### GET `/api/v2/{dataset_string}/reports/viewable_reports/` — viewable_reports

Detail-false custom action. Returns report category counts and per-project counts for the sidebar. V2 ONLY (not in v1).

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Response (object):**
  - `current_page`: `string` (non-null) — Constant 'reports'.
  - `qProject`: `array<object>` (non-null) — [{label:str, pk:int, state:'' , count:int}] per Project in dataset.
  - `custom_report_categories`: `array<object>` (non-null) — [{label:str, state:str, count:int}]; always includes {'All Reports','all'}; conditionally 'Starred' and 'My Reports' when counts>0.
- **Source:** `chiron/api_v2/viewsets/report.py:133`

#### DELETE `/api/v2/{dataset_string}/reports/{id}/` — destroy

Delete a report.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Response (other):**
  - `(none)`: `empty` (nullable) — 204 No Content (standard DRF destroy).
- **Source:** `chiron/api_v2/viewsets/report.py:29`

#### GET `/api/v2/{dataset_string}/reports/{id}/` — retrieve

Retrieve a single report by pk via UserCreatedContentSerializer.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Response (object):**
  - `id`: `integer` (non-null) — PK.
  - `name`: `string` (non-null) — CharField max_length=255.
  - `project`: `integer` (nullable) — Project FK pk; on_delete=SET_NULL, blank/null.
  - `project_name`: `string` (non-null) — SerializerMethodField; '' when no project (serializers.py:265).
  - `description`: `string` (nullable) — TextField blank/null.
  - `creator`: `integer` (non-null) — ChironUser FK pk; read_only.
  - `created`: `string` (non-null) — DateTimeField auto_now_add (ISO datetime); read_only (from TimeStampedModel).
  - `type`: `string` (non-null) — Choice cohort\|table\|cohort_auto; list only returns type=table.
  - `definition`: `string` (non-null) — TextField JSON-encoded, default '{}'. Holds cohort_def/table_def/records_per_page.
  - `creator_name`: `string` (non-null) — SerializerMethodField; creator full name or username.
  - `public`: `boolean` (non-null) — BooleanField default True.
  - `starred`: `boolean` (non-null) — SerializerMethodField; whether requesting user starred it (ContentFlag STAR).
  - `share_with`: `array<object>` (non-null) — Nested ChironUserSerializer many read_only: [{id:int, user:{id,username,first_name,last_name,email}, access_level:str, permission_groups:[int]}].
  - `sharing_description`: `string` (non-null) — SerializerMethodField; 'public' \| 'private' \| '{n} users'.
- **Source:** `chiron/api_v2/viewsets/report.py:29`, `chiron/api/serializers.py:180`

#### PATCH `/api/v2/{dataset_string}/reports/{id}/` — partial_update

Partial update of a report (any subset of writable fields).

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (optional) — Optional on PATCH.
  - `type`: `string` (optional) — If provided, validated cohort\|table. NOTE: validate() references data['type'] unconditionally (serializers.py:242), so a PATCH omitting type can KeyError — inferred from code.
  - `project`: `integer` (optional) — FK pk, nullable.
  - `description`: `string` (optional) — Nullable.
  - `definition`: `string` (optional) — JSON string.
  - `public`: `boolean` (optional) — bool.
- **Response (object):**
  - `id`: `integer` (non-null) — Full UserCreatedContentSerializer returned.
- **Source:** `chiron/api/serializers.py:216`

#### PUT `/api/v2/{dataset_string}/reports/{id}/` — update

Full update of a report. Custom serializer.update() sets attrs and m2m; creator/created remain read-only.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (required) — Required on PUT.
  - `type`: `string` (required) — cohort\|table validated.
  - `project`: `integer` (optional) — FK pk, nullable.
  - `description`: `string` (optional) — Nullable.
  - `definition`: `string` (optional) — JSON string, cohort_def normalized.
  - `public`: `boolean` (optional) — Default True.
- **Response (object):**
  - `id`: `integer` (non-null) — Full UserCreatedContentSerializer returned (see retrieve fields).
- **Source:** `chiron/api/serializers.py:286`

#### GET/POST `/api/v2/{dataset_string}/reports/{id}/delete_form/` — delete_form

GET returns a confirmation payload; POST deletes the report.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Response (object):**
  - `status`: `string` (non-null) — 'complete' after POST delete; 'incomplete' on GET.
  - `errors`: `array<string>` (non-null) — [''].
  - `title`: `string` (nullable) — 'Delete Report' (GET).
  - `data`: `object` (nullable) — GET only: {oReport: str(report name)}.
- **Source:** `chiron/api_v2/viewsets/report.py:515`

#### GET/POST `/api/v2/{dataset_string}/reports/{id}/edit_form/` — edit_form

Edit a report via ReportForm. POST saves; if overwrite_query_def_with_active=='yes' replaces cohort_def/table_def with active snapshots. GET returns JSON form data when output_type=json, else rendered HTML.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Query params:**
  - `output_type`: `string` (optional) — 'json' returns structured data; otherwise HTML via render_to_string.
  - `overwrite_query_def_with_active`: `boolean` (optional) — GET echo default False.
- **Request body fields:**
  - `name`: `string` (required) — ReportForm.
  - `description`: `string` (optional) — ReportForm.
  - `project`: `integer` (optional) — Project pk.
  - `project_other`: `string` (optional) — New project name.
  - `public`: `boolean` (optional) — Checkbox.
  - `share_with`: `array<integer>` (optional) — ChironUser ids.
  - `overwrite_query_def_with_active`: `string` (optional) — POST body; 'yes' overwrites defs with active snapshots (report.py:398).
- **Response (form-json):**
  - `status`: `string` (non-null) — 'complete' on POST success else 'incomplete'.
  - `title`: `string` (nullable) — 'Edit Report'.
  - `errors`: `array<string>` (non-null) — [fContent.errors.as_text()].
  - `data`: `object` (nullable) — When output_type=json: {fForm:{shared_options:[{username,user_id,checked}], project_selection:[{label,value}]}, oReport:{name,creator,created,description,id,project,project_id,public}, overwrite_query_def_with_active}.
  - `html`: `string` (nullable) — Rendered edit_report.html when output_type!=json.
  - `onLoad`: `string` (nullable) — 'attachReportFormEvents' (HTML branch).
- **Source:** `chiron/api_v2/viewsets/report.py:383`

#### POST `/api/v2/{dataset_string}/reports/{id}/flag/` — flag

Add or remove a flag (default STAR) on a report for a user.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Query params:**
  - `chiron_user_id`: `integer` (optional) — Flag on behalf of this ChironUser; default is request.chironuser.
- **Request body fields:**
  - `flag_type`: `string` (optional) — Read from request.POST; default 'star' (ContentFlag.FlagType.STAR).
  - `add_or_remove`: `string` (optional) — Read from request.data; 'add' (default, get_or_create) or 'remove' (delete). NOTE v1 reads add_or_remove from request.POST instead.
- **Response (object):**
  - `status`: `string` (non-null) — Constant 'complete'.
- **Source:** `chiron/api_v2/viewsets/report.py:278`

#### GET/POST `/api/v2/{dataset_string}/reports/{id}/share_form/` — share_form

Update report sharing via ReportSharingForm. POST sets share_with and emails newly-added sharees. GET returns JSON form data when output_type=json else rendered HTML.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, UserCreatedContentPermission
- **Query params:**
  - `output_type`: `string` (optional) — 'json' vs HTML.
- **Request body fields:**
  - `share_with`: `array<integer>` (optional) — ChironUser ids (only field on ReportSharingForm). POST wraps request.data.get('share_with') into a QueryDict (report.py:457).
- **Response (form-json):**
  - `status`: `string` (non-null) — 'complete' on valid POST; 'Data not valid' on invalid POST; 'incomplete' on GET.
  - `errors`: `array<string>` (non-null) — [fContent.errors.as_text()].
  - `title`: `string` (nullable) — 'Share Report' (GET).
  - `data`: `object/string` (nullable) — output_type=json: {fForm:{shared_options:[{username,user_id,checked}]}, oReport:{...}, full_url:str}. Else: rendered share_report.html string.
- **Source:** `chiron/api_v2/viewsets/report.py:451`


### v2 · `table_def`

#### GET `/api/v2/{dataset_string}/table_def/` — list

Inherited from v1 TableDefViewSet.list unchanged. Returns active table_def for chironuser resolved from dataset_string in URL.

- **Permissions:** IsAuthenticated, DatasetUrlPermission (dataset from URL dataset_string), SubjectLevelAccess, CanViewWorkspacePermission
- **Response (object):**
  - `table_def`: `object` (non-null) — Same as v1 list
  - `extended_table_def`: `object` (non-null) — Same as v1
  - `warnings`: `array[str]` (non-null) — 
  - `errors`: `array[str]` (non-null) — 
  - `snapshot_id`: `int` (non-null) — 
  - `previous_snapshot_id`: `int` (nullable) — 
  - `next_snapshot_id`: `int` (nullable) — 
- **Source:** `chiron/api_v2/viewsets/table_def.py:15-25`, `chiron/api/viewsets/table_def.py:33-67`, `chiron/api_v2/urls.py:13-15`

#### POST `/api/v2/{dataset_string}/table_def/` — create

Inherited from v1 TableDefViewSet.create unchanged. Applies transformation, persists active snapshot.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission
- **Request body fields:**
  - `transformation`: `object` (required) — Same as v1 create; required, has 'type'
  - `table_def`: `object` (optional) — Optional; active used if omitted
- **Response (object):**
  - `transformation_successful`: `bool` (non-null) — 
  - `table_def`: `object` (non-null) — Original on fail, transformed on success
  - `transformation_errors`: `array[str]` (non-null) — On failure only
  - `extended_table_def`: `object` (non-null) — On success only
  - `warnings`: `array[str]` (non-null) — On success only
  - `errors`: `array[str]` (non-null) — On success only
  - `snapshot_id`: `int` (non-null) — On success only
  - `previous_snapshot_id`: `int` (nullable) — On success only
  - `next_snapshot_id`: `int` (nullable) — On success only
- **Source:** `chiron/api_v2/viewsets/table_def.py:15-25`, `chiron/api/viewsets/table_def.py:101-148`

#### GET/POST `/api/v2/{dataset_string}/table_def/associated_concept_ids/` — associated_concept_ids

Inherited from v1. Concept ids referenced in table def.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `table_def`: `str(json)` (optional) — GET param optional (convert_to_obj)
- **Request body fields:**
  - `table_def`: `object` (optional) — POST body optional
- **Response (object):**
  - `concept_ids`: `array[str]` (non-null) — Unique concept ids
- **Source:** `chiron/api_v2/viewsets/table_def.py:15-25`, `chiron/api/viewsets/table_def.py:161-172`

#### GET `/api/v2/{dataset_string}/table_def/{pk}/` — retrieve

OVERRIDDEN in v2. Retrieve a specific snapshot, but scoped to request.chironuser (TableDefSnapshot.objects.filter(chironuser=...)). Optionally set active.

- **Permissions:** IsAuthenticated, DatasetUrlPermission, SubjectLevelAccess, CanViewWorkspacePermission. Snapshot filtered by chironuser (differs from v1)
- **Query params:**
  - `set_to_active`: `bool/str` (optional) — Default False; truthy sets active
- **Response (object):**
  - `table_def`: `object` (non-null) — 
  - `extended_table_def`: `object` (non-null) — 
  - `warnings`: `array[str]` (non-null) — 
  - `errors`: `array[str]` (non-null) — 
  - `snapshot_id`: `int` (non-null) — 
  - `previous_snapshot_id`: `int` (nullable) — 
  - `next_snapshot_id`: `int` (nullable) — 
- **Source:** `chiron/api_v2/viewsets/table_def.py:27-59`


### v1 · `analysis_def`

#### GET `/api/analysis_def/` — list

Returns the current ACTIVE analysis_def for chironuser (not a list). Empty dict {} if no active snapshot. Supports content negotiation (JSON / text-plain template / browsable).

- **Permissions:** IsAuthenticated, DatasetSelector, AnalysisViewOn, CanViewWorkspacePermission. renderers: JSON, AnalysisDefTemplateRenderer(text/plain -> analysis_metadata.html), BrowsableAPI. auth CsrfExemptSessionAuthentication
- **Response (object):**
  - `analysis_def`: `object` (non-null) — {rows:[{entry_id,concept_id}], cols:[{entry_id,concept_id}]}. clean_analysis_def. Absent entirely when no active snapshot (response={})
  - `extended_analysis_def`: `object` (non-null) — {rows:[...+label], cols:[...+label]} where label=Concept.name. Entries with missing concept dropped. Src analysis_def_functions.py:26-56
  - `warnings`: `array[str]` (non-null) — Currently always [] in clean_analysis_def
  - `errors`: `array[str]` (non-null) — Currently always []
  - `snapshot_id`: `int` (non-null) — AnalysisDefSnapshot.id; absent if no active snapshot
  - `previous_snapshot_id`: `int` (nullable) — 
  - `next_snapshot_id`: `int` (nullable) — 
- **Source:** `chiron/api/viewsets/analysis_def.py:40-75`, `chiron/query_definition/analysis_def_functions.py:26-56`

#### POST `/api/analysis_def/` — create

Applies a transformation to an analysis_def and returns the new analysis_def; persists as active snapshot on success. Reads raw request.body JSON.

- **Permissions:** IsAuthenticated, DatasetSelector, AnalysisViewOn, CanViewWorkspacePermission
- **Request body fields:**
  - `transformation`: `object` (required) — Required (400 if missing). 'type' selects from analysis transformation_function_lookup: add_entry\|move_entry\|delete_entry\|clear_all\|swap_rows_and_cols. Keys: add_entry(concept_id, role='rows', index?), move_entry(entry_id, role, index), delete_entry(entry_id). Src api/utils/analysis_def.py
  - `analysis_def`: `object` (optional) — Optional list/dict; if omitted uses active analysis def
- **Response (object):**
  - `transformation_successful`: `bool` (non-null) — 
  - `analysis_def`: `object` (non-null) — Original on fail, transformed {rows,cols} on success
  - `transformation_errors`: `array[str]` (non-null) — On failure (e.g. duplicate concept, missing args)
  - `extended_analysis_def`: `object` (non-null) — On success only
  - `warnings`: `array[str]` (non-null) — On success only
  - `errors`: `array[str]` (non-null) — On success only
  - `snapshot_id`: `int` (non-null) — On success only
  - `previous_snapshot_id`: `int` (nullable) — On success only
  - `next_snapshot_id`: `int` (nullable) — On success only
- **Source:** `chiron/api/viewsets/analysis_def.py:111-162`, `chiron/api/utils/analysis_def.py:126-133`

#### GET/POST `/api/analysis_def/associated_concept_ids/` — associated_concept_ids

Return all concept_ids referenced in an analysis def (rows+cols). Uses provided or active analysis def.

- **Permissions:** IsAuthenticated, DatasetSelector, AnalysisViewOn, CanViewWorkspacePermission
- **Query params:**
  - `analysis_def`: `str(json)` (optional) — GET param optional (convert_to_obj)
- **Request body fields:**
  - `analysis_def`: `object` (optional) — POST body optional
- **Response (object):**
  - `concept_ids`: `array[str]` (non-null) — Unique concept ids from rows+cols (analysis_def_functions.get_analysis_def_concept_ids:62)
- **Source:** `chiron/api/viewsets/analysis_def.py:176-187`

#### GET `/api/analysis_def/{pk}/` — retrieve

Retrieve a specific AnalysisDefSnapshot by pk (404 if not found). Optionally sets active.

- **Permissions:** IsAuthenticated, DatasetSelector, AnalysisViewOn, CanViewWorkspacePermission. NOTE v1 does NOT filter snapshot by chironuser
- **Query params:**
  - `set_to_active`: `bool/str` (optional) — Default False; truthy sets active
- **Response (object):**
  - `analysis_def`: `object` (non-null) — {rows,cols}
  - `extended_analysis_def`: `object` (non-null) — {rows,cols} with label
  - `warnings`: `array[str]` (non-null) — 
  - `errors`: `array[str]` (non-null) — 
  - `snapshot_id`: `int` (non-null) — 
  - `previous_snapshot_id`: `int` (nullable) — 
  - `next_snapshot_id`: `int` (nullable) — 
- **Source:** `chiron/api/viewsets/analysis_def.py:77-109`


### v1 · `analysis_tools`

#### GET `/api/analysis_tools/` — list

Returns a dict of hyperlinks to the analysis_tools sub-actions (discovery/index endpoint).

- **Permissions:** IsAuthenticated, DatasetSelector, AnalysisViewOn, CanViewWorkspacePermission. renderers JSON/AnalysisToolsTemplateRenderer/BrowsableAPI
- **Response (object):**
  - `run_analysis`: `str(url)` (non-null) — Absolute URL string. BUG: constructed as <viewset-list-url>+'preview_metadata' but the actual action route is 'run_analysis'; the emitted URL does not match a real route. Src analysis_tools.py:37-43
  - `export_csv`: `str(url)` (non-null) — Absolute URL: <viewset-list-url>+'export_csv'
- **Source:** `chiron/api/viewsets/analysis_tools.py:37-43`

#### GET/POST `/api/analysis_tools/export_csv/` — export_csv

Return a CSV file (attachment) of the full pivottable dataset. @action(detail=False, methods=[GET,POST]).

- **Permissions:** IsAuthenticated, DatasetSelector, AnalysisViewOn, CanViewWorkspacePermission
- **Query params:**
  - `use_active_cohort`: `bool/str` (optional) — GET; default True via string_to_bool
  - `cohort_def`: `str(json)` (optional) — GET; convert_to_obj; else active
  - `analysis_def`: `str(json)` (optional) — GET; else active
- **Request body fields:**
  - `cohort_def`: `array/object` (optional) — POST body; used only if use_active_cohort truthy; else []
  - `analysis_def`: `object` (optional) — POST body; else active
  - `use_active_cohort`: `bool/str` (optional) — POST body; default True (string_to_bool). If false, cohort_def forced to []
  - `table_def`: `object` (optional) — Documented in docstring but code uses analysis_def; likely vestigial
- **Response (csv):**
  - `(body)`: `text/csv` (non-null) — HttpResponse content_type text/csv, Content-Disposition attachment filename 'results_YYYY-MM-DD.csv'. Raises PermissionDenied if cohort_def has validation errors. Src api/utils/export.py:110-144
- **Source:** `chiron/api/viewsets/analysis_tools.py:97-127`, `chiron/api/utils/export.py:110-144`

#### GET/POST `/api/analysis_tools/run_analysis/` — run_analysis

Run the pivottable analysis and return the resulting dataset. @action(detail=False, methods=[GET,POST]). POST allows long params. Returns empty dataset if analysis_def has no rows and no cols.

- **Permissions:** IsAuthenticated, DatasetSelector, AnalysisViewOn, CanViewWorkspacePermission. template_name pivottable.html for text/plain renderer
- **Query params:**
  - `data_view_mode`: `str` (optional) — GET; default 'active'; 'all' => empty cohort_def
  - `cohort_def`: `str(json)` (optional) — GET; parsed via convert_to_obj; else active
  - `analysis_def`: `str(json)` (optional) — GET; NOTE _get_analysis_def keys on 'table_def' presence but parses request.GET['analysis_def'] (see open questions); else active
- **Request body fields:**
  - `cohort_def`: `array/object` (optional) — POST body request.data['cohort_def']; if omitted uses active cohort_def
  - `analysis_def`: `object` (optional) — POST body request.data['analysis_def']; if omitted uses active analysis_def
  - `data_view_mode`: `str` (optional) — POST body; default 'active'. If 'all', cohort_def forced to [] (no filter)
- **Response (object):**
  - `dataset`: `object` (nullable) — pandas df.to_json(orient='split') parsed => {columns:[], index:[], data:[[]]}, OR null when analysis_def has neither rows nor cols
  - `cohort_def`: `array/object` (non-null) — The cohort_def actually used (echoed)
  - `analysis_def`: `object` (non-null) — The analysis_def actually used (echoed)
  - `pivot_table_html`: `str` (non-null) — df.to_html(...) or '' when empty; HTML table markup
- **Source:** `chiron/api/viewsets/analysis_tools.py:45-95`, `chiron/api/viewsets/analysis_tools.py:140-149`


### v1 · `chiron_users`

#### GET `/api/chiron_users/` — list

List ChironUsers (per-dataset user permission records), ordered by user.last_name, with optional name/email search and active filter. Used e.g. for share-with pickers.

- **Permissions:** IsAuthenticated + DatasetSelector (chiron_user.py:16). DatasetSelector requires an active/selected dataset. queryset=ChironUser.objects.all() but get_queryset does NOT filter by dataset — returns ChironUsers across all datasets (chiron_user.py:18-33). Possible over-broad exposure — flagged as open question.
- **Query params:**
  - `term`: `str` (optional) — Case-insensitive contains match against user.first_name OR last_name OR email (chiron_user.py:20,22-27).
  - `active`: `str` (optional) — Filters on user.is_active. Value is truthy-string logic: 'false' => is_active=False; ANY other non-empty value => is_active=True (chiron_user.py:21,29-31). Inferred from string comparison, not a real bool param.
  - `page`: `int` (optional) — Present only when the host project configures a default pagination class (see notes). Not set by the viewset itself.
- **Response (paginated):**
  - `count`: `int` (non-null) — Pagination wrapper — present only when a default pagination class is active (reference test settings use PageNumberPagination PAGE_SIZE=10, test_settings.py:109-115). If host has no default pagination, response is a bare JSON array of the item objects below.
  - `next`: `str\|null` (nullable) — Next page URL or null (pagination wrapper).
  - `previous`: `str\|null` (nullable) — Previous page URL or null (pagination wrapper).
  - `results`: `array<object>` (non-null) — Array of ChironUser objects (fields below). Bare array if not paginated.
  - `results[].id`: `int` (non-null) — ChironUser.id. ChironUserSerializer fields (serializers.py:45-50).
  - `results[].user`: `object` (non-null) — Nested Django User via UserSerializer: {id:int, username:str, first_name:str, last_name:str, email:str} (serializers.py:24-27,41).
  - `results[].access_level`: `str` (non-null) — 'phi'\|'deid'\|'agg'. serializers.py:48.
  - `results[].permission_groups`: `array<int>` (non-null) — M2M rendered as list of PermissionGroup PKs (ModelSerializer PrimaryKeyRelatedField many). serializers.py:49. Inferred type from M2M default rendering.
- **Source:** `chiron/api/viewsets/chiron_user.py:11-33`, `chiron/api/serializers.py:24-27,30-50`, `chiron/api/urls.py:7`, `test_project/test_settings.py:109-115`

#### GET `/api/chiron_users/{id}/` — retrieve

Retrieve a single ChironUser by ChironUser id.

- **Permissions:** IsAuthenticated + DatasetSelector. lookup_field defaults to pk (ReadOnlyModelViewSet). Only list+retrieve enabled (no create/update/destroy).
- **Response (object):**
  - `id`: `int` (non-null) — ChironUser.id.
  - `user`: `object` (non-null) — {id:int, username:str, first_name:str, last_name:str, email:str} (UserSerializer, serializers.py:24-27).
  - `access_level`: `str` (non-null) — 'phi'\|'deid'\|'agg'.
  - `permission_groups`: `array<int>` (non-null) — List of PermissionGroup PKs.
- **Source:** `chiron/api/viewsets/chiron_user.py:11-16`, `chiron/api/serializers.py:30-50`, `chiron/api/urls.py:7`


### v1 · `cohort_def`

#### GET `/api/cohort_def/` — list

Despite the name, returns the CURRENT ACTIVE cohort def from the user's active CohortDefSnapshot (not a list). Builds a qdef.Cohort to compute extended def, warnings, errors.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission. Auth: CsrfExemptSessionAuthentication (session).
- **Response (object):**
  - `cohort_def`: `array` (non-null) — List of criteria_set JSON dicts (see CohortDefCriteriaSet model). Empty list [] if no active snapshot.
  - `extended_cohort_def`: `array` (non-null) — Criteria sets with display fields added (see ExtendedCriteriaSet model).
  - `describe`: `string` (non-null) — HTML summary joined by <br>. Present in code but omitted from the docstring.
  - `warnings`: `array[string]` (non-null) — User-friendly warnings; cohort still queryable.
  - `errors`: `array[string]` (non-null) — User-friendly errors; cohort not queryable.
  - `snapshot_id`: `integer` (nullable) — CohortDefSnapshot.id; None when no active snapshot.
  - `previous_snapshot_id`: `integer` (nullable) — None if no active snapshot or no previous.
  - `next_snapshot_id`: `integer` (nullable) — None if no active snapshot or no next.
- **Source:** `chiron/api/viewsets/cohort_def.py:39`, `chiron/api/urls.py:14`, `chiron/query_definition/cohort.py:7`, `chiron/models/user_models.py:212`

#### POST `/api/cohort_def/` — create

Applies a transformation to a cohort def and (on success) saves the result as the new active CohortDefSnapshot. Body parsed via json.loads(request.body), not a DRF serializer.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission.
- **Request body fields:**
  - `transformation`: `object` (required) — Required (missing -> HTTP 400 with {}). Must include 'type'; type-specific keys vary. Valid types (transformation_function_lookup): add_entry, delete_entry, add_criteria_set, delete_criteria_set, change_to_boolean_or, change_to_boolean_and, sort_cd_entries, clear_all, add_criteria_set_count_rule, set_criteria_set_alias, create_event_rule, modify_event_rule, delete_event_rule. E.g. add_entry needs concept_id (str), optional entry_id, prefilter_value, validate_only(bool), ignore_warnings(bool); add_criteria_set needs collection_id; add_criteria_set_count_rule needs rule_operator(str)+rule_count(int); set_criteria_set_alias needs entry_id+alias; sort_cd_entries needs entry_id+child_ids(array); modify_event_rule needs entry_id+option_type+form fields.
  - `cohort_def`: `array` (optional) — Optional. If omitted, the active cohort def is used as the input.
- **Response (object):**
  - `transformation_successful`: `boolean` (non-null) — Success flag from the transformation function.
  - `cohort_def`: `array` (non-null) — On failure: unchanged input def. On success: new def with transformation applied.
  - `transformation_errors`: `array[string]` (non-null) — Failure only; form/event-option error messages.
  - `transformation_warnings`: `array[string]` (non-null) — Failure only (present for add_entry failures; not all transforms include it).
  - `entry_id`: `string` (nullable) — Present on add_entry success (new/edited cd_entry id). Inferred from transformation func return.
  - `extended_cohort_def`: `array` (non-null) — Success only; see ExtendedCriteriaSet.
  - `warnings`: `array[string]` (non-null) — Success only.
  - `errors`: `array[string]` (non-null) — Success only.
  - `describe`: `string` (non-null) — Success only; HTML summary.
  - `snapshot_id`: `integer` (non-null) — Success only; id of the newly saved active snapshot.
  - `previous_snapshot_id`: `integer` (nullable) — Success only.
  - `next_snapshot_id`: `integer` (nullable) — Success only (typically None since new snapshot is latest).
- **Source:** `chiron/api/viewsets/cohort_def.py:109`, `chiron/api/utils/cohort_def.py:329`, `chiron/api/utils/cohort_def.py:10`, `chiron/query_definition/cohort_def_functions.py:10`

#### GET `/api/cohort_def/{pk}/` — retrieve

Retrieve a specific CohortDefSnapshot by pk and return its cohort def (extended, warnings, errors). Optionally sets it active.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `set_to_active`: `boolean` (optional) — Default False. If truthy and the snapshot is not active, calls CohortDefSnapshot.set_active. Read via request.query_params.get.
- **Response (object):**
  - `cohort_def`: `array` (non-null) — Criteria_set JSON dicts (see CohortDefCriteriaSet).
  - `extended_cohort_def`: `array` (non-null) — See ExtendedCriteriaSet model.
  - `describe`: `string` (non-null) — HTML summary joined by <br>. Not documented in docstring.
  - `warnings`: `array[string]` (non-null) — 
  - `errors`: `array[string]` (non-null) — 
  - `snapshot_id`: `integer` (non-null) — oSnapshot.id (get_object_or_404 -> 404 if missing, so non-null).
  - `previous_snapshot_id`: `integer` (nullable) — None if no previous snapshot.
  - `next_snapshot_id`: `integer` (nullable) — None if no next snapshot.
- **Source:** `chiron/api/viewsets/cohort_def.py:76`, `chiron/models/user_models.py:224`


### v1 · `collections`

#### GET `/api/collections/` — list

List collections in the session-selected dataset, ordered by name. Optional filtering by parent collection or event-based only.

- **Permissions:** IsAuthenticated + DatasetSelector. Dataset resolved from session via get_request_dataset; requires a ChironUser for that dataset. chiron/api/viewsets/collection.py:24
- **Query params:**
  - `collection`: `string` (optional) — A collection permanent_id. Looks up that collection then filters queryset with .filter(collection=selected_collection). NOTE: Collection model has no 'collection' field, so this filter is likely dead/buggy code (would raise FieldError). chiron/api/viewsets/collection.py:43-64
  - `show`: `string` (optional) — If ='event', filter to collections where event_date_field is not null (event-based collections). chiron/api/viewsets/collection.py:66-68
- **Response (paginated):**
  - `count`: `integer` (non-null) — DRF PageNumberPagination wrapper. Viewset does not set pagination_class, so it uses project DEFAULT_PAGINATION_CLASS (PageNumberPagination, PAGE_SIZE=10 in shipped settings). Wrapper present only if project configures pagination.
  - `next`: `string(url)` (nullable) — Pagination next-page URL.
  - `previous`: `string(url)` (nullable) — Pagination previous-page URL.
  - `results`: `array` (non-null) — Array of CollectionSerializer objects (see response_fields of retrieve). Each: permanent_id, name, get_name_plural, is_root_collection, has_event.
- **Source:** `chiron/api/viewsets/collection.py:15`, `chiron/api/viewsets/collection.py:33`, `chiron/api/urls.py:9`, `chiron/urls.py:101`, `chiron/api/serializers.py:142`

#### GET `/api/collections/{permanent_id}/` — retrieve

Retrieve one collection by permanent_id (lookup_field). Optionally augment with cohort-definition criteria-set options and/or criteria-set event options for the cohort-def editor.

- **Permissions:** IsAuthenticated + DatasetSelector (dataset from session). Falls back to unscoped Collection lookup by permanent_id if request.dataset unavailable. chiron/api/viewsets/collection.py:83-88
- **Query params:**
  - `include_criteria_set_options`: `boolean` (optional) — Default False; parsed via string_to_bool. If truthy, adds 'criteria_set_options' to response and requires criteria_set_entry_id. chiron/api/viewsets/collection.py:89
  - `include_criteria_set_event_options`: `boolean` (optional) — Default False; parsed via string_to_bool. If truthy, adds 'criteria_set_event_options' and requires criteria_set_entry_id. chiron/api/viewsets/collection.py:90-92
  - `criteria_set_entry_id`: `string` (optional) — entry_id of the criteria set being edited in the active cohort def. Required (else raises ValueError) when either include_criteria_set_options or include_criteria_set_event_options is truthy. chiron/api/viewsets/collection.py:98-100
- **Response (object):**
  - `permanent_id`: `string` (non-null) — Collection.permanent_id (SlugField, max 120). CollectionSerializer. chiron/api/serializers.py:153
  - `name`: `string` (non-null) — Collection.name (CharField max 120). Display name.
  - `get_name_plural`: `string` (non-null) — Model method get_name_plural(): name_plural if set else name+'s'. Serialized as read-only string via ModelSerializer. chiron/models/data_definition_models.py:462
  - `is_root_collection`: `boolean` (non-null) — Model @property: self == dataset.root_collection. chiron/models/data_definition_models.py:458
  - `has_event`: `boolean` (non-null) — SerializerMethodField calculate_has_event: event_date_field is not None. chiron/api/serializers.py:147,160
  - `criteria_set_options`: `array` (non-null) — Present ONLY if include_criteria_set_options truthy. List of 2 dicts. Dict1: transformation='add_criteria_set_count_rule'(str), label(str), allowed(bool); if disallowed -> disallowed_reason(str), else type(str default 'at least') + value(int default 1). Dict2: transformation='set_criteria_set_alias'(str), label(str), allowed(bool)=True, alias(str). chiron/api/viewsets/collection.py:114-146
  - `criteria_set_event_options`: `object` (non-null) — Present ONLY if include_criteria_set_event_options truthy. {event_options: array of dicts (each: option_id(str), label(str), django_template(str), allowed(bool), plus option-subclass-specific fields), selected_event_option: str}. Built from qdef.EventOptionCollection. chiron/api/viewsets/collection.py:148-156; chiron/query_definition/event_options/__init__.py:137,148; _abstract.py:51
  - `criteria_set_entry_id`: `string` (non-null) — Echoed back. Present ONLY if either options flag truthy. chiron/api/viewsets/collection.py:110
- **Source:** `chiron/api/viewsets/collection.py:69`, `chiron/api/serializers.py:142`, `chiron/api/renderers.py`


### v1 · `concept_categories`

#### GET `/api/concept_categories/` — list

Return top-level categories (parent null) and category-less published concepts for request.dataset, filtered by concept_type and user permissions. ReadOnlyModelViewSet. Not paginated.

- **Permissions:** IsAuthenticated, DatasetSelector
- **Query params:**
  - `concept_type`: `string` (optional) — cohort\|table\|analysis; default None
- **Response (object):**
  - `category_id`: `string` (non-null) — Literal 'top'
  - `categories`: `array<CategorySerializer>` (non-null) — id, name, parent_id(int\|null), get_level(int)
  - `concepts`: `array<ConceptSerializer>` (non-null) — v1 ConceptSerializer
- **Source:** `chiron/api/viewsets/concept_category.py:13`, `chiron/api/viewsets/concept_category.py:112`, `chiron/api/urls.py:11`

#### GET `/api/concept_categories/{id}/` — retrieve

Return direct child categories and concepts of the given Category pk for request.dataset. {id} = Category pk (DRF default pk lookup). Not paginated.

- **Permissions:** IsAuthenticated, DatasetSelector
- **Query params:**
  - `concept_type`: `string` (optional) — cohort\|table\|analysis; default None
- **Response (object):**
  - `category_id`: `int` (non-null) — The provided Category pk
  - `categories`: `array<CategorySerializer>` (non-null) — Direct child categories
  - `concepts`: `array<ConceptSerializer>` (non-null) — Concepts in this category (published, permission-filtered)
- **Source:** `chiron/api/viewsets/concept_category.py:128`


### v1 · `concepts`

#### GET `/api/concepts/` — list

List concepts across all datasets (queryset = Concept.objects.all()), filtered by query params and per-object user_can_view_concept_stats. Paginated. Not dataset-scoped (uses DatasetSelector, no URL dataset).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `collection`: `string` (optional) — Collection permanent_id
  - `category`: `int` (optional) — Category id
  - `search`: `string` (optional) — Search term
  - `show_unpublished`: `boolean` (optional) — default False
  - `concept_type`: `string` (optional) — cohort\|table
  - `page`: `int` (optional) — pagination
  - `page_size`: `int` (optional) — default 100, max 1000
- **Response (paginated):**
  - `count`: `int` (non-null) — pagination wrapper
  - `next`: `string(url)` (nullable) — pagination
  - `previous`: `string(url)` (nullable) — pagination
  - `results`: `array<ConceptSerializer>` (non-null) — v1 ConceptSerializer (no pk field); otherwise same fields as v2
- **Source:** `chiron/api/viewsets/concept.py:34`, `chiron/api/viewsets/concept.py:55`, `chiron/api/viewsets/concept.py:114`, `chiron/api/serializers.py:83`, `chiron/api/urls.py:10`

#### GET `/api/concepts/{permanent_id}/` — retrieve

Retrieve one concept by permanent_id (any dataset); optional cohort_def_options/table_def_options/statistics/callback_data. Bare object.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `prefilter_value`: `string` (optional) — Required when concept_for_prefilter set; echoed back
  - `include_cohort_def_options`: `boolean` (optional) — default False
  - `include_table_def_options`: `boolean` (optional) — default False
  - `include_statistics`: `boolean` (optional) — default False
  - `callback`: `boolean` (optional) — default False
  - `cohort_def`: `string(JSON)` (optional) — Used by table/callback helpers; statistics/cohort_def helpers use active snapshot (v1 does NOT read cohort_def in _get_concept_statistics/_get_cohort_def_options)
  - `show_all_data`: `boolean` (optional) — Compute over all subjects
  - `cohort_def_entry_id`: `int` (optional) — Edit existing cohort def entry
  - `table_def_entry_id`: `int` (optional) — Edit existing table def entry
- **Response (object):**
  - `<ConceptSerializer fields>`: `object` (non-null) — All v1 ConceptSerializer fields (no pk)
  - `cohort_def_options`: `object` (non-null) — Only if include_cohort_def_options; dynamic
  - `table_def_options`: `object` (non-null) — Only if include_table_def_options; dynamic incl criteria_set_options
  - `statistics`: `object` (non-null) — Only if include_statistics; dynamic or {error:...}
  - `callback_data`: `object` (non-null) — Only if callback; dynamic or {error:...}
  - `prefilter_value`: `string` (nullable) — Always added
- **Source:** `chiron/api/viewsets/concept.py:134`, `chiron/api/viewsets/concept.py:217`, `chiron/api/viewsets/concept.py:238`, `chiron/api/viewsets/concept.py:273`

#### PUT `/api/concepts/{permanent_id}/` — update

Same as retrieve but reads flags from request body (PUT) to allow long params. Not a real write.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `(helper params)`: `mixed` (optional) — Helpers read request.query_params for cohort_def/show_all_data/*_entry_id
- **Request body fields:**
  - `include_statistics`: `boolean` (optional) — If truthy, adds statistics
  - `include_cohort_def_options`: `boolean` (optional) — If truthy, adds cohort_def_options
  - `prefilter_value`: `string` (optional) — Read from body when include_cohort_def_options set
  - `callback`: `boolean` (optional) — If truthy, adds callback_data
- **Response (object):**
  - `<ConceptSerializer fields>`: `object` (non-null) — All v1 ConceptSerializer fields
  - `statistics`: `object` (non-null) — Only if include_statistics truthy
  - `cohort_def_options`: `object` (non-null) — Only if include_cohort_def_options truthy
  - `callback_data`: `object` (non-null) — Only if callback truthy; no prefilter_value / table_def_options added
- **Source:** `chiron/api/viewsets/concept.py:53`, `chiron/api/viewsets/concept.py:186`

#### GET `/api/concepts/{permanent_id}/cohort_def_callback/` — cohort_def_callback

Run processor.form_callback and return its data. @action(detail=True). Declares GET+POST, POST blocked.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `show_all_data`: `boolean` (optional) — cohort_def uses active snapshot (v1 does not read cohort_def param here)
  - `prefilter_value`: `string` (optional) — 404 if prefilter_required() and missing
  - `(processor params)`: `mixed` (optional) — processor.form_callback(request.GET,...) processor-specific
- **Response (object):**
  - `<processor form_callback data>`: `object` (non-null) — Dynamic
  - `is_callback`: `boolean` (non-null) — Always True
  - `permanent_id`: `string` (non-null) — Echoes concept id
- **Source:** `chiron/api/viewsets/concept.py:204`, `chiron/api/viewsets/concept.py:304`

#### GET `/api/concepts/{permanent_id}/cohort_def_callback_streaming/` — cohort_def_callback_streaming

Streaming variant; StreamingHttpResponse of JSON chunks separated by '**split**'. @action(detail=True). Declares GET+POST, POST blocked.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `show_all_data`: `boolean` (optional) — cohort_def uses active snapshot
  - `(processor params)`: `mixed` (optional) — processor.form_callback_streaming(request.GET,...)
- **Response (other):**
  - `(stream)`: `text/stream` (non-null) — json chunks with is_callback=True + permanent_id + processor data, joined by '**split**'
- **Source:** `chiron/api/viewsets/concept.py:211`, `chiron/api/viewsets/concept.py:335`


### v1 · `me`

#### GET `/api/me/` — list

Return the current logged-in user's identity plus their ChironUser id and access level for the active dataset. Custom list (single object, not a collection).

- **Permissions:** IsAuthenticated (chiron_user.py:39). Not paginated (custom list returns a plain dict). Note: uses ChironUser.objects.get(user=user) with no dataset filter — raises DoesNotExist(500)/MultipleObjectsReturned(500) if the user has zero or >1 ChironUser rows (chiron_user.py:56).
- **Response (object):**
  - `id`: `int` (non-null) — Django User.id. MeSerializer.id IntegerField (serializers.py:15).
  - `username`: `str` (non-null) — serializers.py:16.
  - `is_staff`: `bool` (non-null) — serializers.py:17.
  - `name`: `str` (non-null) — user.get_full_name(); may be empty string. serializers.py:18.
  - `email`: `str` (non-null) — serializers.py:19.
  - `access_level`: `str` (non-null) — chiron_user.access_level; one of 'phi'\|'deid'\|'agg'. serializers.py:20.
  - `chiron_user_id`: `int` (non-null) — ChironUser.id for the active dataset. serializers.py:21.
- **Source:** `chiron/api/viewsets/chiron_user.py:36-68`, `chiron/api/serializers.py:14-21`, `chiron/api/urls.py:8`


### v1 · `project`

#### GET `/api/project/` — list

List projects (named groups of reports) for the active dataset. Always paginated via LargeResultsSetPagination.

- **Permissions:** IsAuthenticated + DatasetSelector + SubjectLevelAccess (project.py:16). CsrfExemptSessionAuthentication (project.py:15). Paginated always (LargeResultsSetPagination).
- **Query params:**
  - `page`: `int` (optional) — PageNumberPagination page number (LargeResultsSetPagination, pagination.py:6-12).
  - `page_size`: `int` (optional) — Client-overridable page size; default 1000, max 10000 (page_size_query_param='page_size', pagination.py:10-12).
- **Response (paginated):**
  - `count`: `int` (non-null) — Total project count. LargeResultsSetPagination wrapper (page_size 1000).
  - `next`: `str\|null` (nullable) — Next page URL or null.
  - `previous`: `str\|null` (nullable) — Previous page URL or null.
  - `results`: `array<object>` (non-null) — Array of Project objects (fields below).
  - `results[].id`: `int` (non-null) — Project.id. ProjectSerializer (serializers.py:173).
  - `results[].name`: `str` (non-null) — Project.name, max_length 255. serializers.py:173.
  - `results[].viewable_report_count`: `int` (non-null) — SerializerMethodField: count of reports (UserCreatedContent type=table) in this project viewable by request.chironuser (serializers.py:169,175-177 -> Project.get_report_count, user_models.py:565-571). Read-only.
- **Source:** `chiron/api/viewsets/project.py:12-28`, `chiron/api/serializers.py:164-177`, `chiron/api/utils/pagination.py:6-12`, `chiron/api/urls.py:19`

#### POST `/api/project/` — create

Create a new project.

- **Permissions:** IsAuthenticated + DatasetSelector + SubjectLevelAccess. CAVEAT: ProjectSerializer does NOT include the required Project.dataset FK and there is no perform_create override to inject it, so serializer.save() would attempt to insert with dataset=NULL -> IntegrityError. Likely latent bug — flagged as open question.
- **Request body fields:**
  - `name`: `str` (required) — Project name, max_length 255. Only writable serializer field (id and viewable_report_count are read-only). serializers.py:173.
- **Response (object):**
  - `id`: `int` (non-null) — New Project.id.
  - `name`: `str` (non-null) — Echoed name.
  - `viewable_report_count`: `int` (non-null) — 0 for a new project.
- **Source:** `chiron/api/viewsets/project.py:43-50`, `chiron/api/serializers.py:164-177`, `chiron/models/user_models.py:546-555`

#### DELETE `/api/project/{id}/` — destroy

Delete a project by id. Uses ModelViewSet's inherited destroy (returns 204). Note: the viewset defines a def delete(...) (project.py:63-70) which is dead code — DRF routes DELETE to destroy, not delete — so the inherited destroy runs.

- **Permissions:** IsAuthenticated + DatasetSelector + SubjectLevelAccess.
- **Response (other):**
  - `(none)`: `empty` (nullable) — 204 No Content on success (inherited destroy).
- **Source:** `chiron/api/viewsets/project.py:12-19,63-70`

#### GET `/api/project/{id}/` — retrieve

Retrieve a single project by id.

- **Permissions:** IsAuthenticated + DatasetSelector + SubjectLevelAccess.
- **Response (object):**
  - `id`: `int` (non-null) — Project.id.
  - `name`: `str` (non-null) — Project.name.
  - `viewable_report_count`: `int` (non-null) — Reports in project viewable by current chironuser (read-only method field).
- **Source:** `chiron/api/viewsets/project.py:30-41`, `chiron/api/serializers.py:164-177`, `chiron/api/urls.py:19`

#### PATCH `/api/project/{id}/` — partial_update

Partially update a project. Inherited from ModelViewSet (NOT overridden in the viewset), so behaves as a normal partial update.

- **Permissions:** IsAuthenticated + DatasetSelector + SubjectLevelAccess. Enabled via ModelViewSet default (no override).
- **Request body fields:**
  - `name`: `str` (optional) — Optional on PATCH. Only writable field.
- **Response (object):**
  - `id`: `int` (non-null) — Project.id.
  - `name`: `str` (non-null) — Updated name.
  - `viewable_report_count`: `int` (non-null) — Read-only method field.
- **Source:** `chiron/api/viewsets/project.py:12-19`

#### PUT `/api/project/{id}/` — update

Intended to edit an existing project. BUG: the overridden update() calls super().create() instead of super().update(), so a PUT creates a NEW project from the body rather than updating the {id} record (returns 201, id in URL ignored).

- **Permissions:** IsAuthenticated + DatasetSelector + SubjectLevelAccess. Bug at project.py:61 (return super().create(...)). Also shares the missing-dataset create caveat.
- **Request body fields:**
  - `name`: `str` (required) — Project name. serializers.py:173.
- **Response (object):**
  - `id`: `int` (non-null) — Due to the bug this is the id of a NEWLY created project, not {id}.
  - `name`: `str` (non-null) — Echoed name.
  - `viewable_report_count`: `int` (non-null) — Read-only method field.
- **Source:** `chiron/api/viewsets/project.py:52-61`


### v1 · `query_tools`

#### GET `/api/query_tools/` — list

Discovery endpoint returning absolute URLs for the query_tools sub-actions.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission.
- **Response (object):**
  - `count`: `string` (non-null) — Absolute URL to the count action (built from reverse('chiron:api:query_tools-list') + 'count').
  - `preview_metadata`: `string` (non-null) — Absolute URL to preview_metadata.
  - `preview`: `string` (non-null) — Absolute URL to preview.
  - `export_csv`: `string` (non-null) — Absolute URL to export_csv.
- **Source:** `chiron/api/viewsets/query_tools.py:34`, `chiron/api/urls.py:17`

#### GET, POST `/api/query_tools/count/` — count

Return the subject count for the active cohort. @action(detail=False, methods=[GET,POST]). POST exists only to allow long params.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `cohort_def`: `array` (optional) — Documented but ignored (see request_fields note).
- **Request body fields:**
  - `cohort_def`: `array` (optional) — DOCUMENTED as optional (POST body) but NOT actually read: _get_cohort_def ignores request params and always uses the active CohortDefSnapshot via qdef.get_active_cohort_def.
- **Response (object):**
  - `count`: `string` (non-null) — Subject count as a string: str(data_tool.get_cohort_count()).
  - `cohort_def`: `array` (non-null) — The active cohort def that was actually used.
- **Source:** `chiron/api/viewsets/query_tools.py:44`, `chiron/api/viewsets/query_tools.py:200`

#### GET, POST `/api/query_tools/export_csv/` — export_csv

Stream a CSV of the full dataset for the active cohort + active table def. @action(detail=False, methods=[GET,POST]).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
  - `table_def`: `object` (optional) — Documented but ignored.
- **Request body fields:**
  - `cohort_def`: `array` (optional) — Documented but ignored; active cohort snapshot used (_get_cohort_def).
  - `table_def`: `object` (optional) — Documented but ignored; active table snapshot used (_get_table_def -> get_active_table_def, shape {fields: []}).
- **Response (csv):**
  - `(file)`: `text/csv` (non-null) — HTTP response containing the CSV (export_utils.generate_cohort_csv). Header row derived from table.extended_table_def fields. Raises PermissionDenied (403) if the cohort has errors.
- **Source:** `chiron/api/viewsets/query_tools.py:73`, `chiron/api/utils/export.py:68`

#### GET, POST `/api/query_tools/preview/` — preview

Return a paginated preview of the report data for the active cohort + table def. @action(detail=False, methods=[GET,POST]). Uses a custom ReportPaginator (NOT DRF pagination wrapper).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `page`: `integer` (optional) — Default 1 (GET path reads request.GET).
  - `records_per_page`: `integer` (optional) — Default 10.
  - `output_type`: `string` (optional) — Default 'json'; html/json/csv.
- **Request body fields:**
  - `cohort_def`: `array` (optional) — Documented but ignored; active cohort snapshot used.
  - `table_def`: `object` (optional) — Documented but ignored; active table snapshot used.
  - `page`: `integer` (optional) — Default 1. Read from request.data on POST (or GET query string).
  - `records_per_page`: `integer` (optional) — Default 10.
  - `output_type`: `string` (optional) — Default 'json'; options 'html','json','csv'.
- **Response (object):**
  - `warnings`: `array[string]` (non-null) — cohort.warnings + table.warnings.
  - `errors`: `array[string]` (non-null) — cohort.errors + table.errors.
  - `preview_failed`: `boolean` (non-null) — Present (True) ONLY when errors is non-empty.
  - `extended_table_def`: `array` (non-null) — Always present; table.extended_table_def.
  - `record_count`: `integer` (non-null) — Success only; paginator.collection_count.
  - `subject_count`: `integer` (non-null) — Success only; number of subjects.
  - `paginator`: `object` (non-null) — Success only. Keys (ReportPaginator.json): first_index(int), last_index(int), current_page(int), previous_page(int\|null), next_page(int\|null), last_page(int), total_records(int).
  - `data`: `array` (non-null) — Success only. 2D array (rows x columns); each cell is a string, or a {link, value} object when a value has an associated link.
  - `perf`: `object` (nullable) — Only when settings.CHIRON_GET_QUERY_PERFORMANCE is true; querytool.time_analysis.
  - `cache_mode`: `string` (nullable) — Only when CHIRON_GET_QUERY_PERFORMANCE is true.
- **Source:** `chiron/api/viewsets/query_tools.py:144`, `chiron/api/utils/export.py:14`, `chiron/paginator.py:64`

#### GET, POST `/api/query_tools/preview_metadata/` — preview_metadata

Return preview metadata (warnings/errors/extended_table_def) WITHOUT running the data query, so it is faster than preview. @action(detail=False, methods=[GET,POST]).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission.
- **Query params:**
  - `cohort_def`: `array` (optional) — Documented but ignored.
  - `table_def`: `object` (optional) — Documented but ignored.
- **Request body fields:**
  - `cohort_def`: `array` (optional) — Documented but ignored; active cohort snapshot used.
  - `table_def`: `object` (optional) — Documented but ignored; active table snapshot used.
- **Response (object):**
  - `warnings`: `array[string]` (non-null) — cohort.warnings + table.warnings.
  - `errors`: `array[string]` (non-null) — cohort.errors + table.errors.
  - `extended_table_def`: `array` (non-null) — table.extended_table_def (list of field dicts).
  - `preview_failed`: `boolean` (non-null) — Present (True) ONLY when errors is non-empty.
  - `pipeline`: `string` (non-null) — Present ONLY on success. DEPRECATED: literal 'no longer using mongo to generate report'.
- **Source:** `chiron/api/viewsets/query_tools.py:98`, `chiron/api/utils/export.py:49`


### v1 · `report_tools`

#### GET `/api/report_tools/` — list

Return a map of report_tools action URL templates.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess
- **Response (object):**
  - `share`: `string` (non-null) — '.../report_tools/[pk]/share'.
  - `load_as_active`: `string` (non-null) — URL template.
  - `preview`: `string` (non-null) — URL template.
  - `export_csv`: `string` (non-null) — URL template.
  - `export_json`: `string` (non-null) — URL template.
- **Source:** `chiron/api/viewsets/report_tools.py:38`

#### GET `/api/report_tools/{pk}/` — retrieve

Return action URL templates for a report pk (omits export_json).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess
- **Response (object):**
  - `share`: `string` (non-null) — '.../{pk}/share'.
  - `load_as_active`: `string` (non-null) — '.../{pk}/load_as_active'.
  - `preview`: `string` (non-null) — '.../{pk}/preview'.
  - `export_csv`: `string` (non-null) — '.../{pk}/export_csv'.
- **Source:** `chiron/api/viewsets/report_tools.py:49`

#### GET `/api/report_tools/{pk}/export_csv/` — export_csv

Stream full-dataset CSV for the report.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess
- **Response (csv):**
  - `(file)`: `text/csv` (non-null) — generate_cohort_csv HttpResponse; filename slug(name)_YYYY-MM-DD.
- **Source:** `chiron/api/viewsets/report_tools.py:132`

#### GET `/api/report_tools/{pk}/export_json/` — export_json

Return full-dataset export as JSON (shape depends on output_type).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess
- **Query params:**
  - `output_type`: `string` (optional) — 'html'\|'json'\|'csv', default 'json'.
- **Response (other):**
  - `(payload)`: `object/array` (non-null) — generate_cohort_json output; structure varies. Inferred.
- **Source:** `chiron/api/viewsets/report_tools.py:151`

#### POST `/api/report_tools/{pk}/load_as_active/` — load_as_active

Set report's cohort_def/table_def as active snapshots for the user, clearing history.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess
- **Response (object):**
  - `(empty)`: `object` (non-null) — Response({}).
- **Source:** `chiron/api/viewsets/report_tools.py:107`

#### GET `/api/report_tools/{pk}/preview/` — preview

Paginated preview of the report dataset with optional sort override.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess
- **Query params:**
  - `sort_field`: `string` (optional) — table_def entry_id to sort by.
  - `sort_direction`: `integer` (optional) — Default 1.
  - `output_type`: `string` (optional) — 'html'\|'json'\|'csv', default 'json'.
  - `records_per_page`: `integer` (optional) — Default 10.
  - `page`: `integer` (optional) — Default 1.
- **Response (object):**
  - `record_count`: `integer` (non-null) — Success (docstring types).
  - `subject_count`: `integer` (non-null) — Success.
  - `page_number_current`: `integer` (non-null) — Success.
  - `page_number_max`: `integer` (non-null) — Success.
  - `page_first_index`: `integer` (non-null) — Success.
  - `page_last_index`: `integer` (non-null) — Success.
  - `extended_table_def`: `array` (non-null) — Success and fail.
  - `data`: `array<array<string>>` (nullable) — Success only.
  - `warnings`: `array<string>` (non-null) — Success and fail.
  - `preview_failed`: `boolean` (nullable) — Fail only (True).
  - `errors`: `array<string>` (nullable) — Fail only.
  - `report_id`: `integer` (non-null) — Added by viewset (report_tools.py:223).
- **Source:** `chiron/api/viewsets/report_tools.py:172`

#### POST `/api/report_tools/{pk}/share/` — share

Replace all sharing with supplied ChironUser id list; creator-only. Emails new sharees. V1 looks up UserCreatedContent unscoped (no dataset filter).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess; plus PermissionDenied unless requester is creator
- **Request body fields:**
  - `(request body)`: `array<integer>` (required) — Raw JSON array of ChironUser ids via json.loads(request.body). ContentSharing rows deleted then recreated.
- **Response (object):**
  - `(empty)`: `object` (non-null) — Response({}).
- **Source:** `chiron/api/viewsets/report_tools.py:59`


### v1 · `reports`

#### GET `/api/reports/` — list

List reports viewable by the ChironUser (dataset chosen via DatasetSelector, not URL). Paginated. Same serializer/queryset logic as v2.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Query params:**
  - `state`: `string` (optional) — shared_only\|public_only\|mine\|starred; else 404.
  - `project_id`: `integer` (optional) — Filter by project.
  - `search`: `string` (optional) — icontains name/description.
  - `page_size`: `integer` (optional) — Default 1000, max 10000.
  - `page`: `integer` (optional) — Page number.
- **Response (paginated):**
  - `count`: `integer` (non-null) — Pagination wrapper.
  - `next`: `string` (nullable) — Next page URL.
  - `previous`: `string` (nullable) — Previous page URL.
  - `results`: `array<object>` (non-null) — UserCreatedContentSerializer objects (same fields as v2 retrieve).
- **Source:** `chiron/api/viewsets/report.py:47`, `chiron/api/viewsets/report.py:76`

#### POST `/api/reports/` — create

Create a report; creator_id/dataset_id forced in serializer.validate().

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (required) — Required.
  - `type`: `string` (required) — cohort\|table validated.
  - `project`: `integer` (optional) — FK pk nullable.
  - `description`: `string` (optional) — Nullable.
  - `definition`: `string` (optional) — JSON string; cohort_def normalized.
  - `public`: `boolean` (optional) — Default True.
- **Response (object):**
  - `(serializer)`: `object` (non-null) — Full UserCreatedContentSerializer.
- **Source:** `chiron/api/serializers.py:180`

#### GET/POST `/api/reports/create_form/` — create_form

Detail-false. GET returns rendered HTML form; POST validates ReportForm and creates a type=table report from active snapshots. V1 returns HTML (v2 returns JSON data). Uses request.POST (v2 uses request.data->QueryDict).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (required) — ReportForm.
  - `description`: `string` (optional) — ReportForm.
  - `project`: `integer` (optional) — Project pk.
  - `project_other`: `string` (optional) — New project name.
  - `public`: `boolean` (optional) — Checkbox.
  - `share_with`: `array<integer>` (optional) — ChironUser ids.
  - `dataset`: `integer` (optional) — Hidden; from initial.
- **Response (form-json):**
  - `status`: `string` (non-null) — 'complete' on POST success else 'incomplete'.
  - `title`: `string` (nullable) — 'Save Current Results View as a Report' (incomplete).
  - `html`: `string` (nullable) — Rendered save_report.html (incomplete).
  - `onLoad`: `string` (nullable) — 'attachReportFormEvents' (incomplete).
  - `onSuccess`: `string` (nullable) — 'chiron.manager.reportCreated' (POST success).
- **Source:** `chiron/api/viewsets/report.py:159`

#### DELETE `/api/reports/{id}/` — destroy

Delete a report.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Response (other):**
  - `(none)`: `empty` (nullable) — 204 No Content.
- **Source:** `chiron/api/viewsets/report.py:26`

#### GET `/api/reports/{id}/` — retrieve

Retrieve one report via UserCreatedContentSerializer.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Response (object):**
  - `(serializer)`: `object` (non-null) — Identical field set to v2 retrieve: id,name,project,project_name,description,creator,created,type,definition,creator_name,public,starred,share_with,sharing_description.
- **Source:** `chiron/api/viewsets/report.py:26`, `chiron/api/serializers.py:180`

#### PATCH `/api/reports/{id}/` — partial_update

Partial update of report fields.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (optional) — Optional.
  - `type`: `string` (optional) — validate() references data['type'] unconditionally (serializers.py:242) -> omitting may KeyError (inferred).
  - `project`: `integer` (optional) — Nullable.
  - `description`: `string` (optional) — Nullable.
  - `definition`: `string` (optional) — JSON string.
  - `public`: `boolean` (optional) — bool.
- **Response (object):**
  - `(serializer)`: `object` (non-null) — Full UserCreatedContentSerializer.
- **Source:** `chiron/api/serializers.py:216`

#### PUT `/api/reports/{id}/` — update

Full update via custom serializer.update().

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `name`: `string` (required) — Required.
  - `type`: `string` (required) — cohort\|table validated.
  - `project`: `integer` (optional) — Nullable FK pk.
  - `description`: `string` (optional) — Nullable.
  - `definition`: `string` (optional) — JSON string.
  - `public`: `boolean` (optional) — bool.
- **Response (object):**
  - `(serializer)`: `object` (non-null) — Full UserCreatedContentSerializer.
- **Source:** `chiron/api/serializers.py:286`

#### GET/POST `/api/reports/{id}/delete_form/` — delete_form

GET returns confirmation HTML; POST deletes the report.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Response (form-json):**
  - `status`: `string` (non-null) — 'complete' after POST; 'incomplete' on GET.
  - `title`: `string` (nullable) — 'Delete Report' (GET).
  - `html`: `string` (nullable) — Rendered delete_report.html (GET).
- **Source:** `chiron/api/viewsets/report.py:284`

#### GET/POST `/api/reports/{id}/edit_form/` — edit_form

Edit report via ReportForm (request.POST). POST saves; overwrite_query_def_with_active=='yes' replaces defs with active snapshots. Returns rendered HTML (no JSON branch, unlike v2).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Query params:**
  - `overwrite_query_def_with_active`: `boolean` (optional) — GET echo, default False.
- **Request body fields:**
  - `name`: `string` (required) — ReportForm.
  - `description`: `string` (optional) — ReportForm.
  - `project`: `integer` (optional) — Project pk.
  - `project_other`: `string` (optional) — New project name.
  - `public`: `boolean` (optional) — Checkbox.
  - `share_with`: `array<integer>` (optional) — ChironUser ids.
  - `overwrite_query_def_with_active`: `string` (optional) — POST body; 'yes' overwrites defs (report.py:218).
- **Response (form-json):**
  - `status`: `string` (non-null) — 'complete' on POST success else 'incomplete'.
  - `title`: `string` (nullable) — 'Edit Report'.
  - `html`: `string` (nullable) — Rendered edit_report.html.
  - `onLoad`: `string` (nullable) — 'attachReportFormEvents'.
- **Source:** `chiron/api/viewsets/report.py:204`

#### POST `/api/reports/{id}/flag/` — flag

Add/remove a flag (default STAR) on a report. NOTE v1 uses UserCreatedContent.objects.get (no queryset scoping/404) unlike v2's get_object_or_404 on scoped queryset.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Query params:**
  - `chiron_user_id`: `integer` (optional) — Target ChironUser; default request.chironuser.
- **Request body fields:**
  - `flag_type`: `string` (optional) — request.POST; default 'star'.
  - `add_or_remove`: `string` (optional) — request.POST; 'add'(default)\|'remove'.
- **Response (object):**
  - `status`: `string` (non-null) — 'complete'.
- **Source:** `chiron/api/viewsets/report.py:119`

#### GET/POST `/api/reports/{id}/share_form/` — share_form

Update sharing via ReportSharingForm (request.POST). POST saves and emails new sharees. Returns rendered HTML (no JSON branch, unlike v2).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, UserCreatedContentPermission
- **Request body fields:**
  - `share_with`: `array<integer>` (optional) — ChironUser ids (only ReportSharingForm field).
- **Response (form-json):**
  - `status`: `string` (non-null) — 'complete' on POST success else 'incomplete'.
  - `title`: `string` (nullable) — 'Share Report' (GET).
  - `html`: `string` (nullable) — Rendered share_report.html (GET).
- **Source:** `chiron/api/viewsets/report.py:250`


### v1 · `table_def`

#### GET `/api/table_def/` — list

Returns the CURRENT ACTIVE table_def for the request.chironuser (not a list despite the name). Loads active TableDefSnapshot, cleans/validates via qdef.Table.

- **Permissions:** IsAuthenticated, DatasetSelector (dataset from Django session dataset_id, not query param), SubjectLevelAccess, CanViewWorkspacePermission. auth: CsrfExemptSessionAuthentication
- **Response (object):**
  - `table_def`: `object` (non-null) — Validated table def JSON: {fields:[entry...], sort:[{entry_id, direction}], table_type:'subject'}. Entry has entry_id(str), concept_id(str), aggregate(bool), optional aggregation_method/aggregation_settings/aggregation_criteria_set/alias/categorize. See table_def_functions._clean_table_def.
  - `extended_table_def`: `object` (non-null) — table_def plus per-field display metadata; each field: entry_id, concept_id, concept_name, collection{collection_id,event_date_field,event_end_date_field}, categories[str], label, can_delete(bool), can_sort(bool), has_errors(bool), aggregate(bool), alias, categorize (+aggregation_* if aggregate). Src table_def_functions.py:150-212
  - `warnings`: `array[str]` (non-null) — User-friendly warnings; table def still queryable
  - `errors`: `array[str]` (non-null) — User-friendly errors; table def not queryable
  - `snapshot_id`: `int` (non-null) — TableDefSnapshot.id
  - `previous_snapshot_id`: `int` (nullable) — Prior snapshot id or null
  - `next_snapshot_id`: `int` (nullable) — Next snapshot id or null
- **Source:** `chiron/api/viewsets/table_def.py:33-67`, `chiron/query_definition/table.py:8-27`, `chiron/query_definition/table_def_functions.py:49-212`

#### POST `/api/table_def/` — create

Applies a transformation to a table_def and returns the new table_def; persists it as a new active TableDefSnapshot on success. Reads raw request.body JSON.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission
- **Request body fields:**
  - `transformation`: `object` (required) — Required (400 if missing). Must contain 'type' selecting func from table_def transformation_function_lookup: add_entry\|bulk_add_entries\|duplicate_entry\|delete_entry\|resort_columns\|add_sort_entry\|clear_sort_entries\|add_category. Per-type keys: add_entry(concept_id,entry_id?,position?,aggregate?,aggregation_method?), bulk_add_entries(concept_id_list[]), add_category(category_id), duplicate_entry/delete_entry/add_sort_entry(entry_id), resort_columns(entry_ids[]). Src api/utils/table_def.py
  - `table_def`: `object` (optional) — Optional; if omitted uses active table def (qdef.get_active_table_def)
- **Response (object):**
  - `transformation_successful`: `bool` (non-null) — True on success, False on failure
  - `table_def`: `object` (non-null) — On failure: original input table_def. On success: new transformed table_def
  - `transformation_errors`: `array[str]` (non-null) — Only present on failure (transformation_successful False); from display_processor.errors or util messages
  - `extended_table_def`: `object` (non-null) — Only on success; same shape as list.extended_table_def
  - `warnings`: `array[str]` (non-null) — Only on success
  - `errors`: `array[str]` (non-null) — Only on success
  - `snapshot_id`: `int` (non-null) — Only on success; new snapshot id
  - `previous_snapshot_id`: `int` (nullable) — Only on success
  - `next_snapshot_id`: `int` (nullable) — Only on success
- **Source:** `chiron/api/viewsets/table_def.py:101-148`, `chiron/api/utils/table_def.py:201-211`

#### GET/POST `/api/table_def/associated_concept_ids/` — associated_concept_ids

Return all concept_ids referenced in a table def. Uses provided table_def or active one. @action(detail=False, methods=[get,post]).

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission
- **Query params:**
  - `table_def`: `str(json)` (optional) — GET only: parsed via convert_to_obj. If absent, active table def used
- **Request body fields:**
  - `table_def`: `object` (optional) — POST only: request.data['table_def']. If absent, active table def used
- **Response (object):**
  - `concept_ids`: `array[str]` (non-null) — Unique concept_ids from table_def.fields (table_def_functions.get_table_def_concept_ids:215)
- **Source:** `chiron/api/viewsets/table_def.py:150-172`

#### GET `/api/table_def/{pk}/` — retrieve

Retrieve a specific TableDefSnapshot by pk (404 if not found). Optionally sets it active via set_to_active query param.

- **Permissions:** IsAuthenticated, DatasetSelector, SubjectLevelAccess, CanViewWorkspacePermission. NOTE v1 does NOT filter snapshot by chironuser (get_object_or_404 on any pk)
- **Query params:**
  - `set_to_active`: `bool/str` (optional) — Default False. Truthy (any non-empty string) sets this snapshot active if not already. Inferred: query_params.get returns string; treated as truthy
- **Response (object):**
  - `table_def`: `object` (non-null) — Same as list; qdef.Table run with empty cohort_def
  - `extended_table_def`: `object` (non-null) — Same shape as list
  - `warnings`: `array[str]` (non-null) — 
  - `errors`: `array[str]` (non-null) — 
  - `snapshot_id`: `int` (non-null) — 
  - `previous_snapshot_id`: `int` (nullable) — 
  - `next_snapshot_id`: `int` (nullable) — 
- **Source:** `chiron/api/viewsets/table_def.py:69-99`


### v1 · `version`

#### GET `/api/version/` — list

Report the installed Chiron package version. Public.

- **Permissions:** AllowAny (version.py:12). GenericViewSet with only custom list — no other routes. Not paginated.
- **Response (object):**
  - `chiron`: `str` (non-null) — Installed chiron version string (e.g. '1.2.3'); literal 'Unknown' if version lookup raises (version.py:15-18). NOTE: no 'v' prefix here, unlike the v2 auth endpoint's chironVersion.
- **Source:** `chiron/api/viewsets/version.py:7-18`, `chiron/api/urls.py:22`


### Non-API / server-rendered views (Django template & AJAX)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/ajax/export_data/get_add_id_field_form` | AJAX endpoint returning HTML of the add-id-field form, listing collections that have an event_id_field. |
| GET | `/ajax/export_data/get_td_resort_form` | AJAX endpoint returning HTML of the table-definition resort form, built from the current chironuser's active Table def. |
| GET | `/ajax/set_data_view_mode` | AJAX endpoint to switch the session data view mode (all patients vs active cohort). Validates the value, stores in session, returns the re-rendered widget HTML. |
| GET | `/ajax/get_view_mode_selector` | AJAX endpoint returning the HTML for the data-view-mode selector widget plus the current mode. URL name is 'ajax_view_mode_widget'; path is /ajax/get_view_mode_selector. |
| GET | `/backend/data_dictionary` | Metadata page for published concepts (chiron/backend/data_dictionary.html). Lists published concepts included in cohort/table defs and annotates each with summary_statistics and data_type. Marked BROKEN and hidden in the UI (TODO in source). |
| GET | `/backend/etl_logs/<int:log_id>` | Detail view for one ETL run (chiron/backend/etl_log_details.html). |
| GET | `/backend/etl_logs` | Paginated list of EtlLog records (ETL run history) — chiron/backend/etl_logs.html. 10 per page. |
| GET | `/` | Landing/home page. Renders chiron/home.html with a data-summary snippet (HTML string produced by CHIRON_DATA_SUMMARY_FUNCTION_PATH or dataset.override_data_summary_function_path) and the list of all datasets for dataset switching. |
| GET | `/backend/query_troubleshooting` | Staff troubleshooting landing page (chiron/backend/query_troubleshooting.html). Shows the validated/cleaned active cohort, table, and analysis definitions for the current chironuser, each value JSON-serialized (indent=4). |
| GET | `/backend/etl_logs/<int:log_id>/subject/<str:subject_id>` | Paginated subject-record ETL logs for a specific subject within one ETL run (chiron/backend/record_logs_for_subject.html). 100 per page. |
| GET | `/report/<int:report_id>` | Single report view (chiron/report.html). Resolves the UserCreatedContent, ensures/creates the ChironUser for its dataset, sets it on the request, switches session dataset_id to the report's dataset, builds Cohort + Table query-definition objects and renders cohort/table descriptions. |
| GET | `/reports` | Reports listing page (chiron/reports.html). Builds custom_report_categories (Starred/All/My Reports counts) from the user's viewable reports and lists Projects for the dataset with per-project report counts. |
| GET, POST | `/select_dataset` | Choose the active dataset. GET renders chiron/select_dataset.html listing datasets each annotated with .selectable (True if user has a ChironUser or dataset.autocreate_chiron_user). POST stores dataset_id in session and redirects to chiron:workspace. |
| GET | `/backend/source_logs/<int:source_log_id>/data_issues` | Per-source ETL data issues (chiron/backend/source_data_issues.html). |
| GET | `/backend/source_logs/<int:source_log_id>/subject_matching` | Paginated per-record subject-matching log for one source (chiron/backend/source_record_subject_matching.html). 100 per page. Optional filter by whether the subject was created. |
| GET | `/backend/stop_viewing_as_user` | Ends the impersonation session: sets session['override_user_id']=None and redirects to chiron:workspace. Deliberately NOT staff-restricted so the impersonated (override) user can exit. |
| GET, POST | `/backend/user_report` | Admin view of all ChironUsers' access/activity (chiron/backend/user_report.html). POST is the START of the view-as-other-user (impersonation) flow: stores the chosen user id in session['override_user_id'] then redirects to chiron:workspace. |
| GET, POST | `/backend/view_schema` | Renders a Mermaid ER diagram of the dataset schema plus data-dictionary validation errors (chiron/backend/view_schema.html). POST selects which subcollections to include and whether to show related collections. |
| GET | `/workspace` | Main React-hosting workspace page. Renders chiron/workspace.html. Loads the session's active cohort UserCreatedContent (active_cohort_id) if set, and the session data_view_mode. |


## 5. Data model dictionary (type backbone)

**41** persisted/serialized models. Django field types mapped to wire types: CharField/Text/Slug→`string`, IntegerField→`integer`, FloatField→`number`, BooleanField→`boolean`, DateTimeField→`string(iso8601)`, ForeignKey→`integer(id)`, ManyToMany→`array<integer(id)>`, JSONField/JSON-TextField→`object`.

### `AnalysisDefSnapshot`
_Source: `chiron/models/user_models.py:398`_  
History of a chironuser's analysis defs. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `chironuser` | `integer(id)` | no | FK->ChironUser, on_delete=CASCADE |
| `is_active` | `boolean` | no | default True |
| `analysis_def` | `string` | no | TextField; JSON-serialized; get_active_analysis_def default {"fields": []} |

### `AuthSerializer (v2 output DTO)`
_Source: `chiron/api_v2/serializers/auth.py:4-9,35-37`_  
Response shape of GET /api/v2/auth/. Composed of AuthUserSerializer (user) + chironVersion. Deliberately minimal: identity + version only.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `user` | `object` | yes | AuthUserSerializer: id:int, username:str, isStaff:bool, name:str, email:str. Replaced by null for anonymous requests in the viewset. |
| `chironVersion` | `str` | no | CharField; 'v'+package version. |

### `AutocreatedField`
_Source: `chiron/models/data_definition_models.py:838`_  
Tracks which Django fields were already autocreated so chiron_autocreate_dd doesn't recreate them. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) from TimeStampedModel |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) from TimeStampedModel |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=CASCADE; unique_together with app,model,field,unique_source_id |
| `app` | `string` | yes | CharField(max_length=1000, blank,null) |
| `model` | `string` | yes | CharField(max_length=1000, blank,null) |
| `field` | `string` | yes | CharField(max_length=1000, blank,null) |
| `unique_source_id` | `string` | yes | CharField(max_length=1000, blank,null) |
| `associated_concept` | `integer(id)` | yes | FK->Concept, on_delete=SET_NULL, blank,null |

### `CachedCohort`
_Source: `chiron/models/cache_models.py:45`_  
Cache of user-defined cohort info (subject count). Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `dataset` | `string` | no | SlugField(max_length=60) - NOT a FK; dataset slug string; unique_together with hashes |
| `cohort_def_hash` | `string` | no | CharField(max_length=32), db_index; unique_together |
| `subject_permission_hash` | `string` | no | CharField(max_length=32), db_index; unique_together |
| `count` | `integer` | no | IntegerField, no default |

### `CachedConceptStats`
_Source: `chiron/models/cache_models.py:20`_  
Cache of concept stats keyed by cohort_def_hash, subject_permission_hash, concept_id, prefilter_value. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `dataset` | `string` | no | SlugField(max_length=60) - NOT a FK; dataset slug string |
| `cohort_def_hash` | `string` | no | CharField(max_length=32), db_index |
| `subject_permission_hash` | `string` | no | CharField(max_length=32), db_index |
| `concept_id` | `string` | no | SlugField(max_length=120), db_index |
| `prefilter_value` | `string` | yes | CharField(max_length=1000, db_index, blank,null) |
| `stats` | `string` | no | TextField; JSON-serialized (get/set_stats json) |

### `Category`
_Source: `chiron/models/data_definition_models.py:746`_  
Hierarchical grouping of concepts for UI display; no effect on storage/queries.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=CASCADE; unique_together with unique_id |
| `parent` | `integer(id)` | yes | FK->self, on_delete=CASCADE, blank,null, related_name=child_set; null=top-level |
| `unique_id` | `string` | no | SlugField(max_length=255); unique_together with dataset |
| `name` | `string` | no | CharField(max_length=120) |
| `order` | `number` | no | FloatField, default 100.0; sort low->high among siblings |

### `ChironUser`
_Source: `chiron/models/user_models.py:76`_  
Defines a Django user's access to a single Chiron dataset (permissions + access level).

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=CASCADE; unique_together with user |
| `user` | `integer(id)` | no | FK->settings.AUTH_USER_MODEL (Django user), on_delete=CASCADE |
| `access_level` | `string` | no | CharField(max_length=4), choices AccessLevel phi\|deid\|agg, default deid |
| `can_view_workspace` | `boolean` | no | default True |
| `can_view_subject_details` | `boolean` | no | default True |
| `permission_groups` | `array<integer(id)>` | yes | M2M->PermissionGroup, blank; only effective if USE_PERMISSION_GROUPS setting True |

### `ChironUserSerializer (nested in report share_with)`
_Source: `chiron/api/serializers.py:30`_  
Read-only nested representation of each ChironUser in a report's share_with list.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | ChironUser id. |
| `user` | `object` | no | UserSerializer: {id:int, username:str, first_name:str, last_name:str, email:str}. |
| `access_level` | `string` | no | phi\|deid\|agg. |
| `permission_groups` | `array<integer>` | no | PermissionGroup ids. |

### `CohortDefCriteriaSet (JSON structure, NOT an ORM model)`
_Source: `chiron/query_definition/cohort.py:29`_  
The 'criteria set' the task referred to. It is a JSON dict inside the cohort_def list (each element = one criteria set), not a Django model. This is the request/response shape for the cohort_def field throughout cohort_def and query_tools.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `entry_type` | `string` | no | e.g. 'criteria_set'. |
| `entry_id` | `string` | no | Client-generated unique id for the criteria set. |
| `collection_id` | `string` | no | permanent_id of the Collection this criteria set targets. |
| `alias` | `string` | yes | Optional user label for the criteria set. |
| `list` | `array` | no | Array of cd_entry dicts and/or or_group dicts (the filter rules). |
| `event_rule` | `object` | yes | Optional; e.g. {type: 'no_restriction'} or option-specific rule. Present only when a date/event rule is set. |
| `subcol_count_restriction` | `object` | yes | Optional {type: 'at least'\|'at most'\|'exactly', value: int} count rule for subcollection criteria sets. |

### `CohortDefEntry / or_group (JSON structure, NOT an ORM model)`
_Source: `chiron/query_definition/cohort_def_functions.py:189`_  
Elements of a criteria set's 'list'. A cd_entry is a single concept filter rule; an or_group nests multiple cd_entries under boolean OR. Shape derived from cohort_def processors.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `entry_id` | `string` | no | Unique id of the filter rule / group. |
| `concept_id` | `string` | yes | cd_entry only: permanent_id of the Concept being filtered. Absent for or_group. |
| `entry_type` | `string` | yes | 'or_group' for OR groups; concept entries key on concept_id instead. |
| `list` | `array` | yes | or_group only: array of child cd_entry dicts. |
| `prefilter_value` | `any` | yes | Optional prefilter selection (e.g. lab name) for concepts requiring a prefilter. |
| `exclude_selected` | `boolean` | yes | cd_entry; defaults True when absent (per _cd_entry_to_extended_cd_entry). |
| `categories` | `array` | yes | Processor-specific selected values (surfaced as 'values' in extended entry). |

### `CohortDefSnapshot`
_Source: `chiron/models/user_models.py:172`_  
History of a chironuser's cohort defs (undo/redo, restore session). Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `chironuser` | `integer(id)` | no | FK->ChironUser, on_delete=CASCADE |
| `is_active` | `boolean` | no | default True; only one active per chironuser |
| `cohort_def` | `string` | no | TextField; JSON-serialized (get/set_cohort_def json) |

### `Collection`
_Source: `chiron/models/data_definition_models.py:357`_  
A group of related concepts stored in the same DB table; each dataset has one root (subject) collection plus subcollections.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=CASCADE |
| `permanent_id` | `string` | no | SlugField(max_length=120); unique_together with dataset |
| `name` | `string` | no | CharField(max_length=120); unique_together with dataset |
| `name_plural` | `string` | yes | CharField(max_length=120, null,blank); defaults to name+'s' via get_name_plural |
| `many_to_many_with_subject` | `boolean` | no | default False |
| `collection_id_is_integer` | `boolean` | no | default False; DEPRECATED, unused |
| `event_id_field` | `integer(id)` | yes | FK->Concept, SET_NULL, blank,null, related_name=collection_event_id; limit_choices_to published=True |
| `event_name_field` | `integer(id)` | yes | FK->Concept, SET_NULL, blank,null, related_name=collection_event_name |
| `event_date_field` | `integer(id)` | yes | FK->Concept, SET_NULL, blank,null, related_name=collection_event_date |
| `event_end_date_field` | `integer(id)` | yes | FK->Concept, SET_NULL, blank,null, related_name=collection_event_end_date |

### `CollectionRelationship`
_Source: `chiron/models/data_definition_models.py:588`_  
Defines a pk/fk relationship between two subcollection concepts.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `pk_concept` | `integer(id)` | no | FK->Concept, on_delete=PROTECT, related_name=relationships_as_pk; limit_choices_to published=True |
| `fk_concept` | `integer(id)` | no | FK->Concept, on_delete=PROTECT, related_name=relationships_as_fk; limit_choices_to published=True |

### `Concept`
_Source: `chiron/models/data_definition_models.py:872`_  
Defines a single data field / menu item in the cohort-def view; the core data-dictionary entry.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `permanent_id` | `string` | no | SlugField(max_length=120), unique globally |
| `name` | `string` | no | CharField(max_length=120) |
| `name_plural` | `string` | yes | CharField(max_length=120, null,blank); defaults to name+'s' |
| `description` | `string` | yes | TextField(blank,null) |
| `source` | `integer(id)` | yes | FK->Source, on_delete=PROTECT, null,blank |
| `concept_handler` | `integer(id)` | yes | FK->ConceptHandler, on_delete=PROTECT, blank,null |
| `collection` | `integer(id)` | no | FK->Collection, on_delete=PROTECT |
| `category` | `integer(id)` | yes | FK->Category, on_delete=SET_NULL, blank,null, related_name=concepts |
| `order` | `number` | no | FloatField, default 100.0 |
| `multivalue` | `boolean` | no | default True |
| `published` | `boolean` | no | default True; unpublished are hidden from UI/ETL |
| `include_in_cohort_def` | `boolean` | no | default True |
| `include_in_table_def` | `boolean` | no | default True |
| `include_in_analysis_def` | `boolean` | no | default True |
| `has_phi` | `boolean` | no | default False; verbose_name 'contains PHI' |
| `exclude_from_aggregated` | `boolean` | no | default False; verbose_name 'not aggregatable' |
| `concept_for_prefilter` | `integer(id)` | yes | FK->Concept(self), on_delete=SET_NULL, blank,null; limit_choices_to published=True |
| `prefilter_mode` | `string` | no | CharField(max_length=20), choices PrefilterMode required\|optional, default required |

### `ConceptConceptDependency`
_Source: `chiron/models/data_definition_models.py:1321`_  
Tracks that a concept must be loaded before another concept during ETL.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `concept` | `integer(id)` | no | FK->Concept, on_delete=CASCADE, related_name=depends_on_concepts |
| `depends_on_concept` | `integer(id)` | no | FK->Concept, on_delete=PROTECT, related_name=dependent_concepts |
| `description` | `string` | yes | TextField(blank,null) |

### `ConceptHandler`
_Source: `chiron/models/processor_models.py:128`_  
Wrapper abstraction bundling ETL, cohort_def, and display processors for a concept.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `name` | `string` | no | CharField(max_length=120) |
| `python_path` | `string` | no | TextField; full python path to handler class |
| `description` | `string` | yes | TextField(blank,null) |

### `ConceptHandlerArg`
_Source: `chiron/models/processor_models.py:162`_  
An init argument passed to a ConceptHandler (stored as string, cast via get_value).

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `concept` | `integer(id)` | no | FK->Concept, on_delete=CASCADE |
| `name` | `string` | no | CharField(max_length=120); arg variable name |
| `data_type` | `string` | no | CharField(max_length=20), choices DataType string\|float\|integer\|boolean, default string |
| `value` | `string` | no | TextField; stored as string, cast per data_type |

### `ConceptIssueEtlLog`
_Source: `chiron/models/log_models.py:135`_  
Tracks a specific action/problem about a concept during ETL (e.g. count of whitespace-stripped strings).

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `source_log` | `integer(id)` | no | FK->SourceEtlLog, on_delete=CASCADE |
| `concept_id` | `string` | no | SlugField(max_length=120) |
| `issue` | `string` | no | CharField(max_length=120) |
| `issue_description` | `string` | yes | TextField(blank,null) |
| `count` | `integer` | no | IntegerField, no default |

### `ConceptIssueExampleEtlLog`
_Source: `chiron/models/log_models.py:148`_  
Stores specific example input values that had issues during ETL.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `concept_issue` | `integer(id)` | no | FK->ConceptIssueEtlLog, on_delete=CASCADE |
| `input_datatype` | `string` | yes | TextField(blank,null) |
| `input_value` | `string` | yes | TextField(blank,null) |
| `stored_datatype` | `string` | yes | TextField(blank,null) |
| `stored_value` | `string` | yes | TextField(blank,null) |

### `ConceptSourceDependency`
_Source: `chiron/models/data_definition_models.py:1342`_  
Tracks that a source must be loaded before a concept during ETL.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `concept` | `integer(id)` | no | FK->Concept, on_delete=CASCADE, related_name=depends_on_sources |
| `depends_on_source` | `integer(id)` | no | FK->Source, on_delete=PROTECT, related_name=dependent_concepts |
| `description` | `string` | yes | TextField(blank,null) |

### `ContentFlag`
_Source: `chiron/models/user_models.py:529`_  
A per-user flag (e.g. star) on UserCreatedContent. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `content` | `integer(id)` | no | FK->UserCreatedContent, on_delete=CASCADE |
| `chironuser` | `integer(id)` | no | FK->ChironUser, on_delete=CASCADE |
| `flag_type` | `string` | no | CharField(max_length=10), choices FlagType: star |

### `ContentSharing`
_Source: `chiron/models/user_models.py:524`_  
Through model linking UserCreatedContent shared with a ChironUser. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `content` | `integer(id)` | no | FK->UserCreatedContent, on_delete=CASCADE |
| `chironuser` | `integer(id)` | no | FK->ChironUser, on_delete=CASCADE |

### `Dataset`
_Source: `chiron/models/data_definition_models.py:38`_  
A related group of data collections all sharing the same subject (root) collection; one dataset stored per DB/schema.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `unique_id` | `string` | no | SlugField(max_length=60), unique; slug ID used in v2 URL routing |
| `display_name` | `string` | no | CharField(max_length=120), unique |
| `database_name` | `string` | no | SlugField(max_length=30), unique; DB/schema name, may get CHIRON_POSTGRES_SCHEMA_NAME_PREPEND prefix |
| `description` | `string` | yes | TextField(blank,null) |
| `root_collection` | `integer(id)` | yes | FK->Collection, on_delete=SET_NULL, related_name=is_root_for_datasets |
| `subject_id_fields_to_index` | `string` | yes | TextField(blank,null), default='id'; comma-separated list of _ids field names |
| `autocreate_chiron_user` | `boolean` | no | default False |
| `auto_access_level` | `string` | no | CharField(max_length=4), choices AccessLevel phi\|deid\|agg, default deid |
| `auto_can_view_workspace` | `boolean` | no | default True |
| `auto_can_view_subject_details` | `boolean` | no | default True |
| `list_visible` | `boolean` | no | default True; whether shown in api v2 dataset list view |
| `contact_email` | `string(email)` | yes | EmailField(blank=True) only, no null=True; DB stores '' not NULL |
| `override_site_title` | `string` | yes | CharField(max_length=120, blank,null) |
| `override_footer_template` | `string` | yes | TextField(blank,null) |
| `override_data_summary_function_path` | `string` | yes | TextField(blank,null) |
| `override_infobar` | `string` | yes | TextField(blank,null) |
| `override_infobar_type` | `string` | yes | CharField(max_length=12, blank,null), choices InfobarType info\|warning\|danger |
| `logo_url` | `string(url)` | yes | URLField(blank,null) |
| `extra_header_links` | `object` | yes | JSONField(blank,null); object mapping header text -> url |

### `Dataset (subset exposed via v2 DatasetSerializer)`
_Source: `chiron/models/data_definition_models.py:38-174; chiron/api_v2/serializers/auth.py:12-28`_  
The dataset access/permission/feature-flag DTO. DatasetSerializer/DatasetListSerializers live in the v2 AUTH serializers module but are populated by DatasetViewSetV2 (out of this agent's endpoint scope). This is where the React UI actually gets permissions, dataset access, and feature flags — NOT from /api/v2/auth/.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `int` | no | Dataset.id (serializer IntegerField, auth.py:13). |
| `name` | `str` | no | Maps to Dataset.display_name (datasets.py:37,64). Serializer CharField (auth.py:14). |
| `unique_id` | `str` | no | Dataset.unique_id slug; the <dataset_string> used in v2 URLs (data_definition_models.py:53). CharField (auth.py:15). |
| `description` | `str` | yes | required=False (auth.py:16). Dataset.description (nullable in model). |
| `siteTitle` | `str` | yes | required=False. Maps to Dataset.override_site_title (datasets.py:38; data_definition_models.py:131). Feature/branding flag. |
| `lastImport` | `str` | yes | required=False. From get_summary_data()['Date of last import'] (datasets.py:65). Only on retrieve. |
| `subjectCount` | `str` | yes | required=False. From get_summary_data()['Total subjects in system'] (datasets.py:66). String, not int (inferred from serializer CharField). |
| `accessLevel` | `str` | yes | required=False. oChironUser.access_level 'phi'\|'deid'\|'agg' (datasets.py:68). PERMISSION. |
| `accessLevelLabel` | `str` | yes | required=False. Human-readable label from get_summary_data()['Your Access Level'] (datasets.py:67). PERMISSION. |
| `canViewWorkspace` | `bool` | yes | required=False. oChironUser.can_view_workspace (datasets.py:69). PERMISSION FLAG. |
| `canViewSubjectDetails` | `bool` | yes | required=False. oChironUser.can_view_subject_details (datasets.py:70). PERMISSION FLAG. |
| `selectable` | `bool` | yes | required=False. Set in list view: True if user has a ChironUser or dataset.autocreate_chiron_user, else False (datasets.py:25-32). Governs whether UI lets user enter the dataset. |
| `contactEmail` | `email-str` | yes | required=False. Dataset.contact_email; if unset the React UI shows a disabled 'no access' button (data_definition_models.py:124-129; datasets.py:41). |
| `logoUrl` | `str` | yes | required=False. Dataset.logo_url (data_definition_models.py:164; datasets.py:71). Branding feature flag. Only on retrieve. |
| `chironUserId` | `int` | yes | required=False. oChironUser.pk (datasets.py:72). Only on retrieve. |
| `extraHeaderLinks` | `json` | yes | required=False. Dataset.extra_header_links JSONField — object of {header text: url} (data_definition_models.py:170-174; datasets.py:73). FEATURE/CONFIG flag. Only on retrieve. |

### `DefaultPermissionGroup`
_Source: `chiron/models/data_definition_models.py:215`_  
PermissionGroups auto-applied to chironusers autocreated by the system.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=CASCADE |
| `permission_group` | `integer(id)` | no | FK->PermissionGroup, on_delete=CASCADE |

### `DefaultTableDefConcept`
_Source: `chiron/models/data_definition_models.py:197`_  
Concepts that appear as default fields in the results table (removable by user).

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=CASCADE |
| `concept` | `integer(id)` | yes | FK->Concept, on_delete=CASCADE, blank,null; limit_choices_to published=True |

### `EtlLog`
_Source: `chiron/models/log_models.py:6`_  
Tracks an entire ETL event (chiron_run_etl management command).

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `dataset` | `string` | yes | SlugField(max_length=60, blank,null) - NOT a FK; stores dataset slug string |
| `start_date` | `string(iso8601)` | no | DateTimeField |
| `end_date` | `string(iso8601)` | yes | DateTimeField(blank,null) |
| `status` | `string` | no | CharField(max_length=20), choices Status: 'ETL started'\|'ETL completed' |
| `tracking_subject_matching` | `boolean` | no | BooleanField, no default |
| `using_staging` | `boolean` | no | BooleanField, no default |
| `abbreviated_load` | `boolean` | no | BooleanField, no default |
| `comment` | `string` | yes | TextField(blank,null) |

### `ExtendedCdEntry (JSON, NOT an ORM model)`
_Source: `chiron/query_definition/cohort_def_functions.py:212`_  
Display-enriched filter rule inside ExtendedCriteriaSet.entries. Concept variant carries HTML labels; or_group variant nests concept entries.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `entry_id` | `string` | no |  |
| `concept_id` | `string` | yes | Concept variant only. |
| `entry_type` | `string` | yes | 'or_group' for the group variant. |
| `prefilter_value` | `any` | yes | None when absent. |
| `label` | `string` | no | HTML full label from the concept's cohort_def processor (fallback text on error). |
| `abbreviated_label` | `string` | yes | HTML abbreviated label. |
| `exclude_selected` | `boolean` | yes | Defaults True when the source entry omits it. |
| `values` | `array` | yes | From cd_entry.categories. |
| `entries` | `array` | yes | or_group variant only: nested concept extended entries. |
| `has_errors / can_not_edit` | `boolean` | yes | Set when the concept is missing or the user lacks permission. |

### `ExtendedCriteriaSet (JSON output of clean_cohort_def, NOT an ORM model)`
_Source: `chiron/query_definition/cohort_def_functions.py:87`_  
Display-enriched criteria set returned in extended_cohort_def by cohort_def list/retrieve/create. Built per criteria set with labels, permission/error flags, and nested extended entries.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `entry_type` | `string` | no | Copied from criteria set. |
| `entry_id` | `string` | no |  |
| `collection_id` | `string` | no |  |
| `alias` | `string` | no | '' when unset. |
| `label` | `string` | no | Display title, e.g. '<Collection> Criteria'. |
| `is_root_collection` | `boolean` | yes | Present/True for the root (subject) collection criteria set; such sets are inserted at index 0. |
| `collection_name` | `string` | yes | Title-cased collection name (present when collection resolves). |
| `criteria_set_name` | `string` | yes | Non-root only; alias or '<collection_name> N'. |
| `subcol_count_restriction` | `object` | yes | {} when none. |
| `has_event_field` | `boolean` | yes | Whether user may use event/date rules on this collection. |
| `event_rule_label` | `string` | yes | Human-readable event rule; present when event_rule set. |
| `referenced_by_other_event` | `boolean` | yes | True if another criteria set's relative date rule references this one. |
| `entries` | `array` | no | Array of extended cd_entry / or_group dicts (see ExtendedCdEntry). |
| `has_errors / can_not_edit / event_rule_error / can_edit_event_rule` | `boolean` | yes | Error/permission flags added conditionally (missing collection, PHI event rule, etc.). |

### `PermissionGroup`
_Source: `chiron/models/data_definition_models.py:633`_  
Grants users access to groups of subjects and concepts; if none exist, all access is unrestricted.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=PROTECT; unique_together with name |
| `name` | `string` | no | CharField(max_length=255); unique_together with dataset |
| `description` | `string` | yes | TextField(blank,null) |
| `concept_for_allowed_subjects` | `integer(id)` | yes | FK->Concept, on_delete=PROTECT, blank,null; subject included if truthy for this concept |
| `allow_all_subjects_override` | `boolean` | no | default False; if True grants all subjects |
| `allowed_concepts` | `array<integer(id)>` | yes | M2M->Concept, blank, related_name=permissiongroup_allowedconcept_set; limit_choices_to category__isnull=True,published=True |
| `allowed_data_categories` | `array<integer(id)>` | yes | M2M->Category, blank; limit_choices_to parent__isnull=True (top-level only) |
| `allowed_collections` | `array<integer(id)>` | yes | M2M->Collection, blank |

### `Processor`
_Source: `chiron/models/processor_models.py:20`_  
Registry of processor classes (source/etl/cohort_def/display) used during ETL and on the site.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `name` | `string` | no | CharField(max_length=255), unique; Python class name |
| `required_args` | `string` | yes | TextField(blank,null); comma-separated arg names |
| `optional_args` | `string` | yes | TextField(blank,null); comma-separated arg names |
| `is_source_processor` | `boolean` | no | default False |
| `is_etl_processor` | `boolean` | no | default False |
| `is_cohort_def_processor` | `boolean` | no | default False |
| `is_display_processor` | `boolean` | no | default False |
| `is_permission_processor` | `boolean` | no | default False; DEPRECATED |
| `python_path` | `string` | no | TextField; full python path e.g. path.to.MyProcessorClass |
| `description` | `string` | yes | TextField(blank,null) |

### `ProcessorHandlerCombo`
_Source: `chiron/models/processor_models.py:157`_  
Join between a Processor and a ConceptHandler.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `processor` | `integer(id)` | no | FK->Processor, on_delete=CASCADE |
| `handler` | `integer(id)` | no | FK->ConceptHandler, on_delete=CASCADE |

### `Project`
_Source: `chiron/models/user_models.py:546`_  
Grouping of UserCreatedContent for display organization. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=CASCADE |
| `name` | `string` | no | CharField(max_length=255) |

### `Source`
_Source: `chiron/models/data_definition_models.py:235`_  
A data source loaded into a collection during the ETL via a source processor.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `name` | `string` | no | CharField(max_length=120) |
| `collection` | `integer(id)` | no | FK->Collection, on_delete=PROTECT |
| `processor` | `integer(id)` | no | FK->Processor, on_delete=PROTECT; limit_choices_to is_source_processor=True |
| `execution_order` | `integer` | no | default 100; ETL loads low->high |
| `exclude_from_etl` | `boolean` | no | default False |

### `SourceEtlLog`
_Source: `chiron/models/log_models.py:47`_  
Tracks the ETL event for a specific source, with load statistics.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `etl_log` | `integer(id)` | no | FK->EtlLog, on_delete=CASCADE |
| `source` | `string` | no | CharField(max_length=120) |
| `destination_collection` | `string` | no | SlugField(max_length=120) |
| `load_start_date` | `string(iso8601)` | no | DateTimeField |
| `load_end_date` | `string(iso8601)` | yes | DateTimeField(null=True) |
| `data_last_updated_date` | `string(iso8601)` | no | DateTimeField |
| `count_source_records_read` | `integer` | yes | IntegerField(blank,null) |
| `count_source_records_loaded` | `integer` | yes | IntegerField(blank,null) |
| `count_subjects_updated` | `integer` | yes | IntegerField(blank,null) |
| `count_subjects_created` | `integer` | yes | IntegerField(blank,null) |
| `count_subject_docs_start` | `integer` | yes | IntegerField(blank,null) |
| `count_subject_docs_end` | `integer` | yes | IntegerField(blank,null) |
| `count_collection_docs_updated` | `integer` | yes | IntegerField(blank,null) |
| `count_collection_docs_created` | `integer` | yes | IntegerField(blank,null) |
| `count_collection_docs_start` | `integer` | yes | IntegerField(blank,null) |
| `count_collection_docs_end` | `integer` | yes | IntegerField(blank,null) |

### `SourceProcessorArg`
_Source: `chiron/models/processor_models.py:85`_  
An init argument passed to a source processor (stored as string, cast via get_value).

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `source` | `integer(id)` | no | FK->Source, on_delete=CASCADE |
| `name` | `string` | no | CharField(max_length=120); arg variable name |
| `data_type` | `string` | no | CharField(max_length=20), choices DataType string\|float\|integer\|boolean, default string |
| `value` | `string` | no | TextField; stored as string, cast per data_type |

### `SourceRecordEtlLog`
_Source: `chiron/models/log_models.py:108`_  
Tracks ETL of a single source record (only populated when --track-subject-matching is set).

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `source_log` | `integer(id)` | no | FK->SourceEtlLog, on_delete=CASCADE |
| `match_def` | `string` | yes | TextField(blank,null) |
| `add_ids` | `string` | yes | TextField(blank,null) |
| `if_no_match` | `string` | no | CharField(max_length=20) |
| `subject_created` | `boolean` | no | BooleanField, no default |
| `subject_id` | `string` | yes | CharField(max_length=120, blank,null) |
| `subject_start_ids` | `string` | yes | TextField(blank,null) |
| `subject_final_ids` | `string` | yes | TextField(blank,null) |
| `iterations` | `integer` | no | IntegerField, default 1 |

### `SourceSourceDependency`
_Source: `chiron/models/data_definition_models.py:1302`_  
Tracks that a source must be loaded before another source during ETL.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `source` | `integer(id)` | no | FK->Source, on_delete=CASCADE, related_name=depends_on_sources |
| `depends_on_source` | `integer(id)` | no | FK->Source, on_delete=PROTECT, related_name=dependent_sources |
| `description` | `string` | yes | TextField(blank,null) |

### `SystemChironUser`
_Source: `chiron/models/user_models.py:37`_  
Non-DB stand-in ChironUser for system/management contexts (no request). Grants everything: permission_groups=all, access_level=PHI, list_concepts_for_allowed_subjects()=None (all subjects). Used e.g. in home view to count total subjects.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `dataset` | `Dataset (instance attr)` | no | set in __init__ |
| `permission_groups` | `property -> QuerySet[PermissionGroup]` | no | all groups |
| `access_level` | `property -> AccessLevel.PHI` | no | highest |

### `TableDefSnapshot`
_Source: `chiron/models/user_models.py:283`_  
History of a chironuser's table/sort defs. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `chironuser` | `integer(id)` | no | FK->ChironUser, on_delete=CASCADE |
| `is_active` | `boolean` | no | default True |
| `table_def` | `string` | no | TextField; JSON-serialized; get_active_table_def default {"fields": []} |

### `UserCreatedContent`
_Source: `chiron/models/user_models.py:582`_  
User-saved cohorts and tables (reports); definition stored as JSON. Inherits TimeStampedModel.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | `integer` | no | auto PK |
| `created` | `string(iso8601)` | no | DateTimeField(auto_now_add) |
| `modified` | `string(iso8601)` | no | DateTimeField(auto_now) |
| `dataset` | `integer(id)` | no | FK->Dataset, on_delete=PROTECT |
| `name` | `string` | no | CharField(max_length=255) |
| `project` | `integer(id)` | yes | FK->Project, on_delete=SET_NULL, blank,null |
| `description` | `string` | yes | TextField(blank,null) |
| `creator` | `integer(id)` | no | FK->ChironUser, on_delete=PROTECT |
| `type` | `string` | no | CharField(max_length=60), choices Type cohort\|table\|cohort_auto |
| `definition` | `string` | no | TextField, default '{}'; JSON-serialized; get_definition injects records_per_page=500 default |
| `public` | `boolean` | no | default True |
| `share_with` | `array<integer(id)>` | yes | M2M->ChironUser through ContentSharing, related_name=shared_content_set, blank |

## 6. Authentication & authorization model

**Request authentication is standard Django** — there is no custom auth backend
in the `chiron` app. The demo project uses `ModelBackend` + session auth, with
`django.contrib.auth.urls` at `/accounts/` and admin at `/admin/`. DRF has **no
`REST_FRAMEWORK` settings block**, so the API relies on DRF defaults:
`SessionAuthentication` + `BasicAuthentication`. Each viewset declares its own
`permission_classes`.

**Two-layer identity (Django `User` → `ChironUser`).** Every access decision
resolves a `ChironUser` for the `(Django user, Dataset)` pair
(`authorization.py::get_request_chironuser`). The active dataset is resolved
from the session (v1, `DatasetSelector`) or the URL (`v2`,
`DatasetUrlPermission`); if only one dataset exists it is auto-selected.
`ChironUser` carries the **subject-level access level** — e.g. `phi` (see all
detail incl. PHI), de-identified, or aggregate-only — and `PermissionGroup`
membership that gates which concepts/collections are viewable.

**Object-level permission** is enforced per resource: concepts filter on
`user_can_view_concept_stats`; reports start from
`chironuser.get_viewable_reports()` (creator OR shared OR public).

**Impersonation.** `middleware/view_as_other_user.ViewAsOtherUser` lets a staff
user "view as" another user (backed by `backend/user_report` and
`stop_viewing_as_user`). It subclasses `RemoteUserMiddleware` but fully
overrides `process_request`, so REMOTE_USER header auth is effectively unused in
the demo (production SSO deployments may wire it differently).

**Access-level policy relevant to the clinical context:** aggregate views
enforce a minimum subject-count floor (`CHIRON_AGG_SUBJECT_COUNT_MIN_LIMIT = 5`)
to reduce re-identification risk. This is a small-cell-suppression control and
is a good candidate for the validator/benchmark to assert.

## 7. Open questions & notable findings

These came out of the deep read and are carried into Tasks 3–5. Several are
**latent bug candidates** — flagged here, verified/triaged later.

**Correctness / potential bugs (→ Task 5, some → Task 4):**
1. **v1 snapshot retrieve is not scoped by user.** `table_def`/`analysis_def`
   v1 `retrieve` does not filter the snapshot queryset by `chironuser`, so a v1
   client can fetch another user's snapshot by pk (v2 overrides tighten this).
   Potential **IDOR** — flag for security review.
2. **`ProjectViewSet.update()` calls `super().create()`** (`project.py:61`) —
   PUT behaves as create; `ProjectSerializer` also omits the required
   `Project.dataset` FK, so create likely can't set dataset. Confirm whether the
   UI ever exercises this.
3. **`analysis_tools` GET param bugs:** `_get_analysis_def` checks
   `'table_def' in request.GET` but then reads `request.GET['analysis_def']`
   (copy-paste from the table_def viewset); `list` advertises the `run_analysis`
   hyperlink as `…/preview_metadata`, a route that does not exist on that viewset
   (likely 404). Confirm.
4. **`UserCreatedContentSerializer.validate()` reads `data['type']`
   unconditionally** — a `PATCH` omitting `type` appears to `KeyError` before the
   choice check (inferred, not runtime-verified).
5. **v1 `report_tools` flag/share look up `UserCreatedContent` without dataset
   scoping** (v2 scopes to `request.dataset`) — possible cross-dataset access
   depending on permission classes.
6. **`concepts` `cohort_def_callback`/`…_streaming`** declare `methods=["GET","POST"]`
   but the viewset's `http_method_names` omits `post`, so POST → 405. Effectively
   GET-only; the advertised POST is dead.
7. **`ChironUserViewSet.get_queryset()` returns users across ALL datasets** with
   no dataset filter — confirm cross-dataset exposure is intended.
8. **`?collection=` list filter on collections references a `Collection.collection`
   field that does not exist** — likely dead/erroring code.

**Type-contract ambiguities the validator must handle (→ Task 3):**
- Pagination shape is **settings-dependent**. v1 `collections`/`chiron_users`
  use the project's `DEFAULT_PAGINATION_CLASS`; the shipped test/perf settings
  use `PageNumberPagination` (`count/next/previous/results`), but a deploying
  project could set it to `None` (bare array). v2 concepts `list` is explicitly
  `PageNumberPagination` (page_size 100, max 1000); most other v2 resources
  return **bare hand-built dicts** and are not paginated.
- Several payloads are **dynamic processor output** (`statistics`,
  `cohort_def_options`, `table_def_options`, `callback_data`) whose inner shape
  depends on the concept's processor type — the validator asserts presence/type
  of the envelope, not the processor-specific innards.
- `table_def`/`analysis_def`/`cohort_def` bodies are **untyped JSON TextFields**;
  their internal schema is derived from `query_definition/*` usage, not a
  serializer.
- Two `ConceptSerializer` definitions exist: v2 includes a `pk` field, v1 does
  not — otherwise identical.

**Environment / config unknowns:**
- No canonical production settings module is in-repo; only the test/performance
  project settings were available. DRF auth classes, pagination, and throttling
  in production may differ from what was observed.
- `chironVersion`/`version` return placeholder values (`v0.0.0`, `Unknown`) in
  the demo build.

## 8. How to run Chiron locally (Task 2)

Verified working on macOS (Darwin 24.6.0), Python 3.12 venv, Node 20.17,
PostgreSQL 14 (Homebrew). Local/sandbox only — no production infra touched.

### 8.1 Prerequisites (already present in this workspace)
- **PostgreSQL 14** running on `localhost:5432` (`brew services start postgresql@14`).
  A `chiron` database exists with three populated schemas
  (`dataset1_stored`, `dataset2_stored`, `dataset3_stored`) — 69/51/57 tables.
- **Python venv** at `is4r-chiron-develop/.venv` with Django 5.2, DRF 3.17,
  SQLAlchemy 2.0, psycopg2, pandas installed (`pip install -r requirements/dev.txt`).
- **UI deps** installed under `is4r-chiron-ui-develop/node_modules` (`pnpm install`).
- **Django metadata** already migrated & seeded in `test_project/db.sqlite3`
  (165 concepts, 5 ChironUsers, 3 Django users).

### 8.2 Backend
```bash
cd is4r-chiron-develop/test_project
../.venv/bin/python manage.py check          # 0 errors (3 ontology warnings — expected)
# If starting from scratch, seed metadata + ETL into the datasetN_stored schemas:
#   ../.venv/bin/python manage.py restore_test_project_state
../.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
```
`--noreload` is used because the autoreloader orphaned a child process when
backgrounded; a single process is stable.

### 8.3 Frontend
```bash
cd is4r-chiron-ui-develop
node_modules/.bin/vite --port 3000
# Vite proxies /api, /admin, /accounts, /backend, /ajax, /static → 127.0.0.1:8000
# (proxy block already added to vite.config.ts; overrideConfig.apiBaseUrl left "")
```
UI serves on `http://localhost:3000`.

### 8.4 Auth for local testing
DRF defaults = Session + Basic auth. The three demo users (`admin`,
`demouser`, `agguser`) had unknown passwords; I set a known **local-only** dev
password on the SQLite users so the API and validator can authenticate:
```bash
../.venv/bin/python manage.py shell -c "from django.contrib.auth import get_user_model as U; \
[ (lambda u:(u.set_password('demo1234'),u.save()))(U().objects.get(username=n)) \
  for n in ['admin','demouser','agguser'] ]"
```
- **API (validator, curl):** HTTP Basic — `-u admin:demo1234`.
- **Browser/UI:** log in at `/admin/login/` (or `/accounts/login/`), which sets
  a `sessionid` cookie shared with `:3000` (cookies are port-agnostic on
  `localhost`). The custom dev-login buttons on `/accounts/login/` did **not**
  establish a session in testing — use the standard form.

> **Assumption logged:** setting a dev password on local SQLite users is a safe
> sandbox action and the only change made to the seeded metadata DB.

### 8.5 What was verified end-to-end
| Check | Result |
|-------|--------|
| `GET /api/version/` (public) | `200 {"chiron":"Unknown"}` |
| `GET /api/v2/dataset/` (Basic auth) | `200` — 3 datasets returned |
| `GET /api/v2/dataset1_stored/concept_categories/` | `200` — real category tree |
| `GET /api/v2/auth/` (session, logged in) | `200 {"user":{"id":1,"username":"admin","isStaff":true,…}}` |
| UI SPA loads at `:3000` | Renders shell, calls `/api/v2/auth/` + `/api/v2/dataset/` |
| UI authenticated flow | "Select a Dataset" lists all 3; dataset home shows _6 subjects, last import 07/15/2026, access level `phi`_; nav = Query/Results/Reports/Aggregate |

**Issues hit & resolutions**
- *Orphaned dev-server child when backgrounded* → run with `--noreload`.
- *Transient "Invalid username/password" right after setting the dev password*
  → SQLite write lock from the `manage.py shell`; resolved once the shell exited.
- *`/query` deep-link showed "Could not load the page" + logged-out header* →
  the Query route needs an **active dataset** selected via the normal flow
  (VIEW DATASET) rather than a cold deep-link; drive it via navigation, not URL.
- *Node 20.17 < Vite's recommended 20.19* → warning only; Vite 7 runs fine.
