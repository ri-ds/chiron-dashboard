# Chiron — Inefficiencies & Code Quality (Task 5)

Performance + code-quality review of both Chiron repos. Same find→adversarially-verify method as the security pass (rejected/false-positive items excluded). Each finding has a location, evidence, impact, and a concrete fix. Several corroborate the Task-7 benchmark (the concepts-list and reports-list throughput misses).

## Summary

**25 findings** (adversarially verified — false positives dropped). Counts by severity:

| 🟥 HIGH | 🟧 MEDIUM | 🟨 LOW | Total |
|---|---|---|---|
| 5 | 9 | 11 | 25 |

| # | Sev | Finding | Location |
|---|-----|---------|----------|
| 1 | high | Cache-hit path in get_statistics skips aggregate_stats, serving un-suppressed counts to AG | `chiron/processors/abstract/cohort_def_processor.py:84-95` |
| 2 | high | ConceptSerializer performs multiple related lookups per concept during serialization (coll | `chiron/api/serializers.py:83-139` |
| 3 | high | CSV export buffers the entire dataset in memory (no streaming, no row cap) | `chiron/api/utils/export.py:91-107` |
| 4 | high | Reports list default page_size=1000 (max 10000) returns heavy per-item payloads with N+1 q | `chiron/api/utils/pagination.py:6-13` |
| 5 | high | Concept list permission loop iterates the full queryset every request, defeating paginatio | `chiron/api_v2/viewsets/concept.py:27-31,106-115` |
| 6 | medium | ConceptViewSet.get_queryset runs an un-cached N+1 permission loop on the concept-list hot  | `chiron/api/viewsets/concept.py:104-109` |
| 7 | medium | Cohort/stats cache keys include random entry_ids and are order-sensitive, crushing hit rat | `chiron/cache/hashing.py:6-10` |
| 8 | medium | report.py and concept.py v2 viewsets copy-paste v1 instead of subclassing it | `chiron/api_v2/viewsets/report.py:29 (vs chiron/api/viewsets/report.py:` |
| 9 | medium | viewable_reports action recomputes the entire get_viewable_reports query once per project | `chiron/api_v2/viewsets/report.py:155-166` |
| 10 | medium | Category/Concept hierarchy helpers walk the parent chain with one query per level | `chiron/models/data_definition_models.py:778-812 (Category.get_ancestor` |
| 11 | medium | Preview endpoint has no upper bound on records_per_page (pagination is trivially bypassabl | `chiron/api/utils/export.py:14-42 (line 17)` |
| 12 | medium | JSON full-report export buffers all records in memory with no limit | `chiron/api/utils/export.py:146-171` |
| 13 | medium | Report record_count is recomputed from scratch on every preview/pagination call (only subj | `chiron/query_engine/postgres/querytool.py:66-74` |
| 14 | medium | create_indexes() builds a plain btree for EVERY published concept, including unbounded Tex | `chiron/query_engine/postgres/db_writer.py:419-481` |
| 15 | low | CachedConceptStats has no composite index, no unique constraint, and an unindexed dataset  | `chiron/models/cache_models.py:20-42` |
| 16 | low | Only caching layer for concept stats / cohort counts is off by default, with no short-TTL  | `chiron/chiron_settings.py:246` |
| 17 | low | Cache wrappers eagerly compute hashes (incl. a DB query) even when caching is disabled, tw | `chiron/cache/cached_concept_stats.py:15-24` |
| 18 | low | Dead DEPRECATED viewset + its dead test are never wired in but still shipped | `chiron/api/viewsets/user_created_content_DEPRECATED.py:1-95` |
| 19 | low | TimeStampedModel abstract base defined 4 times identically | `chiron/models/user_models.py:26` |
| 20 | low | Management command _chiron_clear_all_concepts.py is un-invokable (leading underscore) and  | `chiron/management/commands/_chiron_clear_all_concepts.py:1-45` |
| 21 | low | Seven commented-out URL routes referencing already-deleted view functions | `chiron/urls.py:30-34,66-79,88-98` |
| 22 | low | check_permission_group re-runs an identical PermissionGroup COUNT for every concept and ev | `chiron/models/data_definition_models.py:1048 (Concept.check_permission` |
| 23 | low | get_request_dataset issues two queries (count then index) on the single-dataset path, on e | `chiron/authorization.py:39-41` |
| 24 | low | No response compression (GZip) configured for large JSON/CSV payloads | `performance_project/project/settings.py:55-63` |
| 25 | low | No composite (subject_id, event_date) index for the subject-join + event-date-range access | `chiron/query_engine/postgres/sql_alchemy_queries/event_filters.py:28-4` |

## Findings (detail)

### 1. 🟥 HIGH — Cache-hit path in get_statistics skips aggregate_stats, serving un-suppressed counts to AGG users

- **Category:** caching-correctness  
- **Verification:** CONFIRMED  
- **Location:** `chiron/processors/abstract/cohort_def_processor.py:84-95`

**What it is.** get_statistics() stores RAW stats to the cache (save_new_cache_entry(stats) at line 92 is called BEFORE aggregate_stats), and applies small-cell suppression via aggregate_stats() only on the cache-MISS branch (lines 93-95). On a cache HIT (lines 84-89) it returns oCache.get_stats() directly with no aggregation. The cache key (CachedConceptStatsWrapper: subject_permission_hash + cohort_def_hash + concept_id + prefilter_value) does not include access_level, so the same row is shared across PHI/DEID/AGG users with identical subject permissions. An AGG user who reads a cache entry (populated by any such user, including themselves on the write path) receives raw, non-min-limited category/histogram/missing-value counts. This is a small-cell suppression bypass. It is latent while CHIRON_USE_CACHES=False (demo) but active in any deployment with caches enabled.

**Impact.** Aggregated-access users can see exact small-cell counts that should be suppressed (helpers.apply_min_limit) - a data-disclosure / re-identification risk in production, plus inconsistent stats depending on whether the value came from cache.

**Fix.** Apply the same access-level suppression on the cache-hit branch that already exists on the miss branch, keeping a single raw cache entry shared across access levels. In get_statistics(), after stats = oCache.get_stats() (line 87), add: if self.chironuser.access_level == self.chironuser.AccessLevel.AGG: stats = self.aggregate_stats(stats). This makes both branches consistent and applies suppression per-request based on the requesting user's access level. (Including access_level in the cache key would also work but wastes cache space, since the cache is designed to store raw data once and suppress at read time.)

> _Verifier note:_ Verified against /Users/pot95a/2026/new_chiron/is4r-chiron-develop/chiron/processors/abstract/cohort_def_processor.py:79-95 (the finding's path chiron/processors/abstract/... resolves here). get_statistics() on a cache MISS calls save_new_cache_entry(stats) at line 92 with the RAW output of preprocess_statistics, and only then applies aggregate_stats at lines 93-94 for AGG users. On a cache HIT (lines 85-89) it returns oCache.get_stats() directly with stats["perf"]={} and NO aggregation, regardless of access level. In cache/cached_concept_stats.py:40-72 the cache key is (dataset, cohort_def_ha


### 2. 🟥 HIGH — ConceptSerializer performs multiple related lookups per concept during serialization (collection, prefilter, category walk, and full concept-handler instantiation)

- **Category:** n+1  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/serializers.py:83-139; chiron/api_v2/serializers/concept.py:25-83; chiron/models/data_definition_models.py:1069-1087 (_instantiate_concept_handler), 1217-1229 (get_cohort_def_processor_without_user)`

**What it is.** For each concept in a page, ConceptSerializer resolves: `collection` (SlugRelatedField, line 88) + get_collection_name + get_collection_name_plural all touching `concept.collection` (1 query/concept, no select_related); `concept_for_prefilter = ConceptRelatedSerializer` touching `concept.concept_for_prefilter` (1 query/concept); `category_hierarchy` -> get_category_hierarchy() walking the category.parent chain (1 query per hierarchy level per concept), then re-serialized via CategorySerializer whose get_level walks parents again; and get_concept_type (line 134/77) -> get_cohort_def_processor_without_user() -> _instantiate_concept_handler which loads `self.concept_handler` (1 query), iterates `self.concepthandlerarg_set.all()` (1 query), and reads `self.collection.dataset` — all per concept. That is roughly 5+ queries per concept on top of the get_queryset loop, for a page of up to 1000 concepts.

**Impact.** Even after fixing the get_queryset loop, serialization alone costs ~5 queries x page_size (up to 5000 for a full page). get_concept_type instantiating a handler per row is pure redundant compute on a read endpoint.

**Fix.** On the ConceptViewSetV2.get_queryset queryset add select_related('collection__dataset', 'concept_for_prefilter', 'concept_handler', 'category') and prefetch_related('concepthandlerarg_set'). Note that category parent walking (get_category_hierarchy / get_level) is arbitrary-depth, so a fixed select_related('category__parent') only covers one level; prefer prefetching all categories for the dataset once and building the hierarchy in memory (or cache parent lookups) to fully eliminate the parent-chain N+1. For concept_type, avoid instantiating the full handler/processor per row on the list endpoint: derive concept_type directly from concept_handler (or the ConceptHandler metadata) without calling .instantiate()/get_cohort_def_processor(), or drop concept_type from the list serializer and expose it only on the retrieve endpoint. Apply the same optimization to the v1 ConceptSerializer usages (api/viewsets/concept.py, concept_category.py).

> _Verifier note:_ All three cited files exist in the sibling Chiron repo (is4r-chiron-develop) and match the finding. ConceptSerializer (api_v2/serializers/concept.py:25-83, identical v1 at api/serializers.py:83-139) resolves, per concept: `collection` via SlugRelatedField + get_collection_name + get_collection_name_plural (all touch concept.collection; Django FK caching makes this 1 query/concept, not 3, but still unprefetched); `concept_for_prefilter` nested serializer (1 query when non-null); `category_hierarchy` -> Concept.get_category_hierarchy() (models:989) which reads self.category then walks oCategory.


### 3. 🟥 HIGH — CSV export buffers the entire dataset in memory (no streaming, no row cap)

- **Category:** blocking-io-memory  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/utils/export.py:91-107; chiron/query_engine/postgres/querytool.py:81-98,32-35`

**What it is.** generate_cohort_csv() calls querytool.get_full_report(output_type="csv") (export.py:91), which runs the unbounded SQL statement (querytool.py:92 get_sql_statement() with no skip/limit) and materializes EVERY row into a Python list in QueryToolPostgres.run(): `response = []; for row in conn.execute(statement): response.append(list(row))` (querytool.py:33-35). That full list is then post-processed by get_display_values() and written row-by-row into a plain django.http.HttpResponse (export.py:101 `HttpResponse(content_type="text/csv")`, writer loop 103-106). HttpResponse buffers the whole body before sending, so at peak the process holds the full result set as a Python list AND the fully-rendered CSV bytes simultaneously (~2x the data). There is no LIMIT and no configurable cap; export_csv (report_tools.py:132-151, query_tools.py:72-95) exposes this on GET with only a cohort/table def. For a clinical dataset a report can be hundreds of thousands to millions of rows.

**Impact.** Large exports spike memory and can OOM/kill the worker; the client also waits for the entire CSV to be built before the first byte is sent (no time-to-first-byte, long-held worker, higher timeout risk). Concurrent large exports multiply the effect.

**Fix.** Return a StreamingHttpResponse driven by a generator, and use a SQLAlchemy server-side/streaming cursor: conn.execution_options(stream_results=True) and iterate the result with yield_per(batch) so rows are pulled in batches. Yield each CSV line via csv.writer writing to an Echo/pseudo-buffer (a class whose write() returns the value). Important caveat not stated in the finding: get_display_values() (querytool.py:95) currently transforms the whole list at once, so simply swapping the response class is insufficient for true O(batch) memory — the display-value/aggregation post-processing (run_after_query_aggregation_modification + get_display_values) must be refactored to run per batch, otherwise the full list is still materialized. Also add a sane configurable row cap / timeout guard for the export path.

> _Verifier note:_ All cited locations verified against source at /Users/pot95a/2026/new_chiron/is4r-chiron-develop. export.py:91 generate_cohort_csv calls querytool.get_full_report(output_type="csv"); export.py:101-106 builds a plain HttpResponse(content_type="text/csv"), wraps it in csv.writer, and writes rows in a loop (no StreamingHttpResponse). querytool.py:81-98 get_full_report calls builder2.get_sql_statement() with NO skip/limit (contrast get_report_preview line 73 which passes skip/limit). querytool.py:32-35 run() with default return_scope="all" materializes the ENTIRE result set into a Python list verb


### 4. 🟥 HIGH — Reports list default page_size=1000 (max 10000) returns heavy per-item payloads with N+1 queries

- **Category:** pagination-payload  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/utils/pagination.py:6-13; chiron/api_v2/viewsets/report.py:42; chiron/api/serializers.py:180-210,280-283; chiron/models/user_models.py:636-648`

**What it is.** ReportViewSetV2 uses LargeResultsSetPagination with page_size=1000 and max_page_size=10000 (pagination.py:11-13, report.py:42). A plain GET with no page_size returns up to 1000 reports. Each report is serialized by UserCreatedContentSerializer which (a) includes the full `definition` field (serializers.py:204) — that is the entire cohort_def + table_def JSON blob, often several KB per report; (b) nests `share_with = ChironUserSerializer(many=True)` (serializers.py:191); and (c) has SerializerMethodFields `starred`/`sharing_description` that each hit the DB per row: check_if_starred() runs `ContentFlag.objects.filter(...)` (user_models.py:644-648) and get_sharing_description() runs `self.share_with.all().count()` (user_models.py:636-642). With the 1000-default, one list call is ~1000 report rows x (definition blob + nested users + multiple extra queries) => multi-MB JSON plus thousands of SQL round-trips.

**Impact.** Default reports listing is both a large payload and an N+1 storm (thousands of queries per request), scaling linearly with report count up to 10000. Slow response, high DB load, large transfer — the opposite of what pagination should provide.

**Fix.** Highest-value, lowest-risk changes: (1) add .select_related('creator','project') and .prefetch_related('share_with__user','share_with__permission_groups') to get_viewable_reports() (or in ReportViewSetV2.get_queryset); (2) replace the per-row check_if_starred query with a single prefetch/annotation of the current user's STAR ContentFlags, and short-circuit get_sharing_description using the already-prefetched share_with; (3) use a lighter list serializer that omits the "definition" blob and the fully-nested share_with (retrieve/get_report can keep them). The page_size reduction (to ~25-50 with a smaller max) is reasonable but should be coordinated with the frontend, which appears to expect the full report set at once (see the sibling viewable_reports action computing whole-set category counts); lowering it blindly may break the reports UI. The N+1 and definition-exclusion fixes deliver most of the benefit without that risk.

> _Verifier note:_ All cited code verified in /Users/pot95a/2026/new_chiron/is4r-chiron-develop. pagination.py:11-13 has page_size=1000, max_page_size=10000. report.py:41-42 sets serializer_class=UserCreatedContentSerializer and pagination_class=LargeResultsSetPagination; list() (lines 50-66) simply calls super().list(), so a plain GET returns up to 1000 rows. serializers.py:180-210 uses ONE serializer for both list and retrieve: fields include "definition" (line 204, the full cohort_def+table_def JSON string), share_with=ChironUserSerializer(many=True) (line 191, which further nests UserSerializer + permission_


### 5. 🟥 HIGH — Concept list permission loop iterates the full queryset every request, defeating pagination and amplified by max_page_size=1000

- **Category:** pagination-compute  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api_v2/viewsets/concept.py:27-31,106-115; chiron/api_v2/serializers/concept.py:38,77-82,67-69,39`

**What it is.** ConceptViewSetV2.get_queryset() ends with a Python-level permission filter: `for oConcept in queryset: can_view,_ = oConcept.user_can_view_concept_stats(self.request.chironuser); ...` then `queryset.filter(id__in=allowed_concept_ids)` (concept.py:107-112). This loop evaluates and iterates the ENTIRE concept set (all concepts in the dataset) on every list call, before DRF pagination is applied — so StandardResultsSetPagination (page_size=100, max_page_size=1000) never bounds the expensive part; page 1 does the same full-scan work as page 50. On top of that, max_page_size=1000 lets a client request 1000 concepts, and each serialized concept is expensive: get_concept_type() instantiates a processor per concept via get_cohort_def_processor_without_user() (serializers concept.py:77-82), plus nested category_hierarchy (67-69) and concept_for_prefilter (39) per row.

**Impact.** Concept listing does O(all concepts) permission work regardless of page, so pagination gives no compute/DB savings; and a 1000-item page triggers 1000 processor instantiations + nested serialization, producing a large, slow response. Latency grows with total concept count, not page size.

**Fix.** Express the view-permission predicate as DB filters in get_queryset() for the common cases (published=True, collection__dataset==chironuser.dataset, permission-group membership via a subquery/exists, has_phi vs chironuser.access_level, exclude_from_aggregated for AGG), and only fall back to a Python check for the narrow PHI+DEID/AGG branch that requires handler instantiation to test deid-processor availability (models lines 1123-1129) — ideally restricting that fallback to the already-paginated page rather than the full set. Reduce max_page_size (e.g. 200). Add a lightweight list serializer that computes concept_type without instantiating a processor (e.g. read concept_handler/stored type) and drops per-row category-hierarchy/nested prefilter serialization, so per-request work is proportional to page size.

> _Verifier note:_ All cited locations verified in /Users/pot95a/2026/new_chiron/is4r-chiron-develop/. viewsets/concept.py:27-31 defines StandardResultsSetPagination(page_size=100, max_page_size=1000). get_queryset() (lines 107-112) ends with a Python loop `for oConcept in queryset: user_can_view_concept_stats(...)` then `queryset.filter(id__in=allowed_concept_ids)`. list() (135) just calls super().list(), so DRF's ListModelMixin evaluates get_queryset() — fully materializing the queryset via the for-loop — BEFORE paginate_queryset runs. Thus the permission scan is O(all filtered concepts) on every list request 


### 6. 🟧 MEDIUM — ConceptViewSet.get_queryset runs an un-cached N+1 permission loop on the concept-list hot path

- **Category:** efficiency  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/viewsets/concept.py:104-109`

**What it is.** After building the concept queryset, get_queryset iterates every concept in Python and calls oConcept.user_can_view_concept_stats(chironuser) per concept, then re-queries with Concept.objects.filter(id__in=allowed_concept_ids). user_can_view_concept_stats -> check_permission_group (chiron/models/data_definition_models.py:1043-1067) executes, PER CONCEPT: PermissionGroup.objects.filter(dataset=...).count() (line 1048), chironuser.permission_groups.all() (line 1053, and again 1062), and get_category_hierarchy() (data_definition_models.py:989-1002) which walks oCategory.parent in a while-loop (one query per hierarchy level because the queryset has no select_related/prefetch on category/parent), plus categories[0].permissiongroup_set.all(). For a collection of N concepts this is O(N x depth) queries every list request, and none of it is cached. Even datasets with no permission groups pay N count() queries (the early-return at line 1049 still runs the count first).

**Impact.** A concept sidebar/list with ~100 concepts issues several hundred DB queries per request; latency scales linearly with concept count and recurs on every list/search call.

**Fix.** Core, low-risk fix: (1) add select_related('collection__dataset', 'category', 'category__parent', ...) and prefetch_related for the permissiongroup_set / permission_groups relations on the base queryset so the collection/dataset/category/parent lookups stop hitting the DB per concept; (2) hoist the request-invariant work out of the per-concept loop — compute PermissionGroup.objects.filter(dataset=chironuser.dataset).count() once and fetch chironuser.permission_groups.all() once, passing them in rather than recomputing per concept. This alone collapses hundreds of queries to a handful. The suggested full ORM-side permission filter is harder than implied because of the recursive category-parent hierarchy walk and the top-level allowed_concepts branch, so treat it as optional. The TTL-cache of allowed-concept ids is also optional and introduces permission-change invalidation concerns; not needed to realize the main win.

> _Verifier note:_ Verified against the real codebase at /Users/pot95a/2026/new_chiron/is4r-chiron-develop/ (the working dir is only a benchmark wrapper; cited paths are relative to that repo). concept.py:104-109 matches exactly: get_queryset iterates the full queryset in Python calling oConcept.user_can_view_concept_stats(chironuser) per concept, then re-queries Concept.objects.filter(id__in=allowed_concept_ids). The base queryset (line 64) is Concept.objects.all() with no select_related/prefetch_related. check_permission_group (data_definition_models.py:1043-1067) runs PermissionGroup.objects.filter(dataset=..


### 7. 🟧 MEDIUM — Cohort/stats cache keys include random entry_ids and are order-sensitive, crushing hit rate

- **Category:** caching  
- **Verification:** CONFIRMED  
- **Location:** `chiron/cache/hashing.py:6-10`

**What it is.** cohort_def_hash is md5(to_json_string(cohort_def)) with no normalization (also duplicated in chiron/cache/cached_cohort.py:37-41). Each cohort_def entry carries an entry_id produced by helpers.generate_entry_id (chiron/helpers.py:41-49), a random 12-char string, so two logically identical cohorts built independently serialize to different JSON and never share a cache entry; reordering entries also changes the hash. The code's own TODOs at hashing.py:7 and cached_cohort.py:38 flag this. This directly limits reuse of CachedCohort (subject counts) and CachedConceptStats.

**Impact.** With caches enabled, cohort-count and concept-stat cache hit rates are far lower than they should be - shared/saved cohorts and repeat sessions re-run full research-DB queries that a normalized key would have served from cache.

**Fix.** Introduce one shared canonicalization helper and use it in all three call sites (hashing.create_cohort_def_hash, cached_cohort.set_cohort_def_hash, cached_concept_stats via hashing): deep-copy cohort_def, recursively strip or blank entry_id (and any relative-date target_entry_id references, remapping them consistently so referential semantics are preserved), sort entries deterministically, and serialize with json.dumps(sort_keys=True) before md5. Preserving relative-date references matters because entry_id is used as a link target (target_entry_id) in event/date rules, so naive stripping could conflate semantically different cohorts; normalize those references rather than dropping them. Add a unit test asserting two independently-built logically-identical cohorts produce the same hash and that reordering does not change it.

> _Verifier note:_ Read all cited locations and confirmed every mechanical claim. hashing.py:6-10: create_cohort_def_hash = md5(to_json_string(cohort_def)) with zero normalization, and line 7 carries the exact TODO 'try to give same hash for irrelevant changes like different order or entry_ids'. cached_cohort.py:37-41 duplicates this logic verbatim with the same TODO (line 38). helpers.py:41-49: generate_entry_id() returns a random 12-char alphanumeric string. Verified entry_id is a real per-entry field of cohort_def entries and is set from this random generator (cohort_def_processor.py:311 response['entry_id'] 


### 8. 🟧 MEDIUM — report.py and concept.py v2 viewsets copy-paste v1 instead of subclassing it

- **Category:** duplicated-code  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api_v2/viewsets/report.py:29 (vs chiron/api/viewsets/report.py:26); chiron/api_v2/viewsets/concept.py:33 (vs chiron/api/viewsets/concept.py:34)`

**What it is.** The v2 API's intended pattern is thin subclassing — analysis_def, analysis_tools, cohort_def, concept_category, query_tools, table_def, collection all do `class XViewSetV2(XViewSet)` and only override permission_classes (+ occasionally one method), so they are 15-89 lines. But the two largest viewsets break this pattern and re-inherit from scratch: ReportViewSetV2 is `class ReportViewSetV2(viewsets.ModelViewSet)` (529 lines) and re-implements all 8 v1 methods (list, get_serializer_context, get_queryset, flag, create_form, edit_form, share_form, delete_form) that v1's 301-line ReportViewSet already defines, plus adds get_report/viewable_reports/formatters. ConceptViewSetV2 is `class ConceptViewSetV2(viewsets.ModelViewSet)` (400 lines) duplicating v1's 351-line ConceptViewSet (get_queryset/list/retrieve/update/cohort_def_callback/_get_* helpers); diff shows only ~120 lines actually differ, the substantive difference being "use cohort_def/table_def from request params if present else active snapshot." StandardResultsSetPagination is even defined identically in both concept.py files (v1:28, v2:27). report_tools.py v2 does subclass v1 but then overrides every method (list/retrieve/share/load_as_active/export_csv/export_json/preview, ~200 lines) where the only real change is scoping querysets with `.filter(dataset=request.dataset)` and one URL string rewrite (54 diff lines of 230).

**Impact.** ~900+ lines of near-duplicated viewset logic across report.py/concept.py/report_tools.py. Any bug fix or behavior change to report/concept endpoints must be made in two places and is easy to miss; this is a live divergence risk (v1 and v2 can silently drift). v2 viewsets total 1619 lines, a large fraction of which is copied from v1.

**Fix.** Direction is correct but the collapse is partial, not total. For report.py: make ReportViewSetV2(ReportViewSet) so the identical list/get_serializer_context/get_queryset are inherited; still override permission_classes and add the v2-only get_report/viewable_reports; the *_form JSON-output branches and get_object_or_404(self.get_queryset()) differences must stay as overrides (or be folded into v1 via an output_type flag). For concept.py: make ConceptViewSetV2(ConceptViewSet), override get_queryset for dataset scoping, and lift the shared 'params-else-active-snapshot' resolution into a v1 base helper that the v1 helpers call with a flag so both versions share it. Hoist StandardResultsSetPagination to chiron/api/utils/pagination.py. For report_tools, push `dataset=request.dataset` scoping into a base get_object_or_404 helper and parameterize the base-URL prefix so list/retrieve/share/export_* overrides collapse. Do not expect the report/concept subclasses to reduce to 'only permission_classes' — the JSON branches and dataset scoping are genuine behavioral differences that need targeted overrides.

> _Verifier note:_ All cited lines verified. api_v2/viewsets/report.py:29 defines `class ReportViewSetV2(viewsets.ModelViewSet)` (529 lines) instead of subclassing v1's ReportViewSet (api/viewsets/report.py:26); it re-implements list, get_serializer_context, get_queryset, flag, create_form, edit_form, share_form, delete_form (all in v1's 301-line class) plus adds get_report/viewable_reports/_format_* helpers. get_queryset (v2:185-227) and get_serializer_context (v2:174-183) are near line-identical to v1; permission set differs only by DatasetUrlPermission vs DatasetSelector. api_v2/viewsets/concept.py:33 defines


### 9. 🟧 MEDIUM — viewable_reports action recomputes the entire get_viewable_reports query once per project

- **Category:** redundant-queries  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api_v2/viewsets/report.py:155-166; chiron/models/user_models.py:565-571 (Project.get_report_count) and 129-136 (get_viewable_reports)`

**What it is.** The viewable_reports action loops `for oProject in qProject: oProject.get_report_count(request.chironuser)`. get_report_count calls `oChironUser.get_viewable_reports()` — the full `UserCreatedContent.accessible(...).filter(type=TABLE).filter(Q(creator)\|Q(share_with)\|Q(public)).distinct()` query with joins — then `.filter(project=self).count()`. So the expensive viewable-reports query (with the m2m join + DISTINCT) is rebuilt and a COUNT executed once for every project. Combined with the standalone COUNTs at lines 141, 143 and 149, a dataset with P projects issues P+3 heavy COUNT queries.

**Impact.** The reports sidebar/category endpoint scales linearly with project count, each iteration running a non-trivial DISTINCT-join COUNT. Slows the reports landing page for datasets with many projects.

**Fix.** Compute per-project counts in one grouped query, accounting for the m2m DISTINCT and projects with zero reports: `qReport = request.chironuser.get_viewable_reports(); counts = dict(qReport.values('project').annotate(c=Count('id', distinct=True)).values_list('project', 'c'))`, then in the loop use `oProject.report_count = counts.get(oProject.pk, 0)`. Note the distinct=True (the source query uses .distinct() because of the share_with join) and the .get(pk, 0) default (projects with no viewable reports won't appear in the grouped result, so plain counts[pk] would KeyError). This collapses P+ heavy COUNTs to ~1 grouped query.

> _Verifier note:_ Read all three cited locations. report.py:157-158 loops over every Project in the dataset and calls oProject.get_report_count(request.chironuser) per iteration. user_models.py:565-571 shows get_report_count calls oChironUser.get_viewable_reports() (rebuilding the queryset fresh each call) then .filter(project=self).count(). user_models.py:129-136 shows get_viewable_reports builds UserCreatedContent.objects.accessible(dataset).filter(type=TABLE).filter(Q(creator=self)\|Q(share_with=self)\|Q(public=True)).distinct() — a query with an m2m join on share_with plus DISTINCT. So each loop iteration r


### 10. 🟧 MEDIUM — Category/Concept hierarchy helpers walk the parent chain with one query per level

- **Category:** n+1  
- **Verification:** CONFIRMED  
- **Location:** `chiron/models/data_definition_models.py:778-812 (Category.get_ancestors/get_ancestor_names/get_level/get_top_level_parent), 989-1002 (Concept.get_category_hierarchy); used in chiron/api/serializers.py:79 (CategorySerializer get_level) and 124-126 (get_category_hierarchy)`

**What it is.** get_category_hierarchy and get_level/get_ancestors follow `oCategory.parent` in a while-loop; each `.parent` access is a separate SELECT unless the chain was select_related/prefetched. During concept serialization get_category_hierarchy runs per concept (depth queries each), and CategorySerializer.get_level (serializers.py:79) walks the chain again for every category it renders. Category.__str__ (line 772) also calls get_ancestor_names, so any admin/serialized listing of categories walks parents per row.

**Impact.** Adds O(depth) queries per concept and per category rendered. For deep category trees and large concept pages this compounds the concept-list cost.

**Fix.** On the concept list querysets (ConceptViewSet.get_queryset and ConceptViewSetV2.get_queryset) add select_related for the category chain to a reasonable fixed depth, e.g. .select_related('collection', 'category', 'category__parent', 'category__parent__parent', ...), which collapses concept.category and the parent walk into the concept fetch (also fixes the get_collection_name N+1). For unbounded-depth trees, the cleaner fix is to fetch all categories for the dataset once (Category.objects.accessible(dataset)), build an id->category dict in memory, and resolve hierarchy/level from that map instead of ORM per-node traversal. Note: DRF `depth = 1` on CategorySerializer (line 80) does NOT help here because categories are serialized from in-memory lists, not a driving queryset; and in the concept path get_level does not add extra queries since get_category_hierarchy already caches the walked .parent chain on the same objects — so the incremental win is on get_category_hierarchy's own walk and the per-concept concept.category query, not on get_level.

> _Verifier note:_ Verified in the sibling backend repo is4r-chiron-develop (the cwd is the frontend UI repo; the chiron/... paths resolve there). Category.parent is a self-referential ForeignKey('self', ...) (data_definition_models.py:749-756), so each .parent access is a lazy SELECT unless select_related/prefetched. get_ancestors (778-784), get_ancestor_names (786-792), get_level (794-803), get_top_level_parent (805-812), and Concept.get_category_hierarchy (989-1002) all walk .parent in while-loops; __str__ (772-776) calls get_ancestor_names. CategorySerializer exposes get_level as a field (serializers.py:72-8


### 11. 🟧 MEDIUM — Preview endpoint has no upper bound on records_per_page (pagination is trivially bypassable)

- **Category:** pagination  
- **Verification:** CONFIRMED (severity adjusted from high)  
- **Location:** `chiron/api/utils/export.py:14-42 (line 17); chiron/api/viewsets/query_tools.py:143-198; chiron/api_v2/viewsets/report_tools.py:176-230`

**What it is.** get_paginated_preview() reads `records_per_page = int(query_params.get("records_per_page", 10))` (export.py:17) with no clamp and passes it straight through as the SQL LIMIT (paginator.limit -> get_report_preview(limit=...) -> get_sql_statement(limit=...)). A client can call the preview action (query_tools preview, report_tools preview) with e.g. `records_per_page=10000000` and receive the entire dataset in a single buffered DRF Response, completely defeating the intent of paginated preview. The default of 10 is safe, but nothing enforces a maximum.

**Impact.** Any authenticated user can pull an unbounded result set through the 'preview' path, causing the same in-memory materialization + buffered JSON serialization as a full export, on an endpoint that is supposed to be cheap/paginated. Effectively an accidental DoS / memory-pressure vector and negates pagination.

**Fix.** Clamp in get_paginated_preview (export.py) so the bound covers both the huge-value and the falsy-zero/negative cases. Because get_sql_statement treats limit=0 as "no LIMIT" (returns everything), coercing to a positive floor is essential:      DEFAULT_PREVIEW_PAGE_SIZE = 10     MAX_PREVIEW_PAGE_SIZE = 200  # tune 200-500     try:         records_per_page = int(query_params.get("records_per_page", DEFAULT_PREVIEW_PAGE_SIZE))     except (TypeError, ValueError):         records_per_page = DEFAULT_PREVIEW_PAGE_SIZE     records_per_page = max(1, min(records_per_page, MAX_PREVIEW_PAGE_SIZE))  This bounds the SQL LIMIT and the buffered response regardless of client input and closes the records_per_page=0 (no-LIMIT) bypass. Applying the clamp centrally in get_paginated_preview covers both the query_tools and report_tools preview actions at once.

> _Verifier note:_ Note the cited paths do not exist in the working directory (chiron-benchmark is a black-box HTTP tool with no Chiron source); I verified against the real source in the sibling checkout /Users/pot95a/2026/new_chiron/is4r-chiron-develop. The full chain is confirmed: (1) chiron/api/utils/export.py:17 reads `records_per_page = int(query_params.get("records_per_page", 10))` with no clamp and no positivity check, then builds `ReportPaginator(records_per_page, page_number)`. (2) chiron/paginator.py:6 stores `self.limit = int(limit)` unclamped. (3) export.py:34 calls `querytool.get_report_preview(skip


### 12. 🟧 MEDIUM — JSON full-report export buffers all records in memory with no limit

- **Category:** blocking-io-memory  
- **Verification:** CONFIRMED  
- **Location:** `chiron/api/utils/export.py:146-171; chiron/api_v2/viewsets/report_tools.py:153-174`

**What it is.** generate_cohort_json() calls querytool.get_full_report(output_type) (export.py:161), materializing the entire result set (same run() append-all path, querytool.py:33-35/93), and returns `{"header": [...], "records": data}` which report_tools.export_json wraps in a DRF Response (report_tools.py:171-174). DRF's JSONRenderer serializes the whole records list into a single in-memory bytes buffer before sending. Like the CSV path there is no row cap or streaming.

**Impact.** For large reports this buffers the full dataset twice (Python list of rows + rendered JSON bytes) and delays TTFB, with the same OOM risk as the CSV export but via the JSON export endpoint.

**Fix.** Enforce a configurable maximum export row count (fail fast or truncate with a clear signal when exceeded), and/or stream the response via StreamingHttpResponse that yields the header then records incrementally as a JSON array backed by a server-side/streaming cursor (avoid DRF's buffering JSONRenderer for this endpoint). Ideally share one streaming export implementation between the CSV and JSON paths.

> _Verifier note:_ All cited locations check out. export.py:146-171 generate_cohort_json() calls querytool.get_full_report(output_type=output_type) at line 161 and returns {"header": header_names, "records": data} (lines 162-165). querytool.py get_full_report() (lines 81-98) builds the statement via builder2.get_sql_statement() with NO skip/limit args; query_builder.py:52-68 confirms get_sql_statement(skip=0, limit=None) only applies .offset()/.limit() when those are truthy, so the full report query is unbounded. run(..., return_scope="all") at querytool.py:32-35 initializes response=[] and appends list(row) for


### 13. 🟧 MEDIUM — Report record_count is recomputed from scratch on every preview/pagination call (only subject_count is cached)

- **Category:** missing-caching  
- **Verification:** CONFIRMED  
- **Location:** `chiron/query_engine/postgres/querytool.py:66-74; chiron/query_engine/postgres/sql_alchemy_queries/query_builder.py:70-82`

**What it is.** get_report_preview() caches the subject count via CachedCohortWrapper (querytool.py:68 -> get_cohort_count, which reads/writes cache at lines 108-130), but the record count is computed fresh every call: `count_statement = builder2.get_sql_statement_record_count(); record_count = self.run('recordcount', ...)` (querytool.py:70-71). get_sql_statement_record_count wraps the ENTIRE report SELECT — all joins, WHERE filters, and GROUP BY — inside `SELECT count() FROM (<full report query>) subquery` (query_builder.py:77-82). Because preview is paginated (skip/limit params), navigating an N-page report re-executes this full-query aggregate N times even though the count is identical for every page of the same cohort+table.

**Impact.** Every page turn pays the cost of executing the full multi-join, multi-filter cohort query just to recount. For large cohorts with several joined collections/lookups this can be seconds per page and is duplicated on each pagination request, directly inflating report browsing latency.

**Fix.** Cache record_count keyed by (dataset, cohort_def_hash, table_def_hash, subject_permission_hash) — mirroring the existing subject-count cache but adding a table_def hash since record_count depends on the table def (fields/joins/group-by), which CachedCohortWrapper does not currently incorporate. Alternatively, since the paginated report query on line 73 already scans the full cohort per page, compute record_count only when skip==0 (first page) and pass it to the client so subsequent page requests omit it. Either approach reduces N full-query COUNT executions to 1 per report browse.

> _Verifier note:_ Verified against the real source at /Users/pot95a/2026/new_chiron/is4r-chiron-develop/. querytool.py:66-79: get_report_preview caches subject_count via get_cohort_count() (which reads/writes CachedCohortWrapper at lines 108-130), but record_count (lines 70-71) is computed fresh every call with no cache. query_builder.py:70-82: get_sql_statement_record_count builds the full report SELECT (fields with include_aggregated_fields=False), FROM (joins), WHERE (filters), and GROUP BY, then wraps it as select(func.count()).select_from(statement.subquery()) — a COUNT over the entire report query (ORDER 


### 14. 🟧 MEDIUM — create_indexes() builds a plain btree for EVERY published concept, including unbounded Text columns, in one non-concurrent transaction

- **Category:** index-strategy  
- **Verification:** CONFIRMED  
- **Location:** `chiron/query_engine/postgres/db_writer.py:419-481`

**What it is.** create_indexes() loops over every published concept in the dataset (db_writer.py:426-429) and unconditionally issues `CREATE INDEX IF NOT EXISTS idx_<concept> ... (<concept>)` as a default btree (db_writer.py:447-453), plus one per subfield for complex types (455-467). Three concerns: (1) It indexes ALL concept columns, including free-text/notes and display-only fields that are never used in a WHERE/JOIN, causing large index bloat and slower ETL finalize for wide datasets (thousands of concepts -> thousands of indexes). (2) A btree over an unbounded Text column fails when a value exceeds Postgres's 2704-byte btree limit; here the failure path prints a warning and calls sys.exit(1) (db_writer.py:472-477), aborting the whole ETL. (3) All CREATE INDEX statements run in a single transaction committed only at the very end (db_writer.py:479-480) and are non-CONCURRENT; any mid-loop failure rolls back every index. Filter columns (in_/=) do benefit from these btrees (see cohort_def/text.py:326 column.in_()), so the btrees are useful for equality/range filtering — the problem is indexing indiscriminately and the text/size failure mode.

**Impact.** On wide datasets the index set inflates storage and lengthens ETL; a single long free-text concept can abort the entire index build (and thus the ETL) via sys.exit(1). Non-concurrent single-transaction builds hold locks and consume memory proportional to concept count.

**Fix.** Scope indexing to columns actually queried: event_date_field/event_end_date_field, CollectionRelationship pk/fk concepts, and concepts with include_in_cohort_def=True (already the established filter in cache_utils.py). For text/ontology concepts, avoid a raw btree over unbounded Text — use CREATE INDEX ... USING gin (col gin_trgm_ops) (which also serves the regexp_match path) or an expression index on left(col, N) so long values cannot error. Replace the bare sys.exit(1) with per-index error handling that logs and skips (or fails fast with context) rather than rolling back the entire build; commit periodically instead of one giant transaction, and consider CREATE INDEX CONCURRENTLY for non-staging rebuilds.

> _Verifier note:_ Read db_writer.py:419-481 and confirmed every claim. create_indexes() iterates Concept.objects.filter(published=True, collection__dataset=self.dataset) (line 426) with no filter/join relevance filter — the only skip is the only_text early-continue (433-436). Lines 447-453 emit CREATE INDEX IF NOT EXISTS with no USING clause (default btree), plus one per subfield for dict types (455-467). Lines 469-477 catch any exception, print a warning, and call sys.exit(1) (sys imported line 4), aborting the whole ETL mid-loop. Line 480 is a single conn.commit() at the end (one transaction, non-CONCURRENT).


### 15. 🟨 LOW — CachedConceptStats has no composite index, no unique constraint, and an unindexed dataset column; save is non-atomic

- **Category:** missing-index  
- **Verification:** CONFIRMED (severity adjusted from medium)  
- **Location:** `chiron/models/cache_models.py:20-42`

**What it is.** find_matching_cache_entry (chiron/cache/cached_concept_stats.py:46-52) filters on (dataset, cohort_def_hash, subject_permission_hash, concept_id, prefilter_value), but the model only declares single-column db_index on cohort_def_hash/subject_permission_hash/concept_id/prefilter_value; `dataset` (SlugField, line 26) has no index, and there is no Meta.unique_together/indexes (contrast CachedCohort at lines 55-60 which has unique_together giving a composite index). Postgres must pick/intersect single-column indexes for a 5-column equality lookup, and the dataset predicate is unindexed. Additionally save_new_cache_entry (cached_concept_stats.py:55-75) does find->delete->create with no transaction and no unique constraint (unlike CachedCohort which wraps its save in transaction.atomic), so concurrent identical requests can accumulate duplicate rows that .first() silently masks. The prefilter_value db_index is on a 1000-char CharField that is NULL for most rows - an expensive, low-value index.

**Impact.** When caches are enabled and the table grows (users x concepts x cohort_defs), lookups on the hot stats path degrade and duplicate rows bloat the table.

**Fix.** Two legitimate, independent improvements: (1) Correctness/bloat: wrap save_new_cache_entry in transaction.atomic() to match CachedCohort, and prefer update_or_create over find->delete->create. Note that adding unique_together over these columns will NOT prevent duplicates when prefilter_value is NULL under Postgres default NULL semantics; if a true uniqueness guarantee is wanted, use a UniqueConstraint with a functional expression (e.g. COALESCE(prefilter_value,'')) or Postgres 15+ NULLS NOT DISTINCT. (2) Performance: optionally add a composite Meta.indexes on (dataset, cohort_def_hash, subject_permission_hash, concept_id, prefilter_value) to serve the 5-column equality lookup with one index instead of relying on bitmap intersection of the existing single-column indexes. Do NOT justify this by 'dataset is unindexed' — it is indexed (SlugField default db_index=True). Dropping the standalone prefilter_value index is reasonable only after the composite index exists.

> _Verifier note:_ I opened both cited files in /Users/pot95a/2026/new_chiron/is4r-chiron-develop. The finding's substantive core is real and verifiable: CachedConceptStats.Meta (cache_models.py:34-35) has only verbose_name_plural — no unique_together and no composite indexes; find_matching_cache_entry (cached_concept_stats.py:46-52) filters on 5 columns and uses .first(); and save_new_cache_entry (cached_concept_stats.py:55-75) performs find->delete->create with NO transaction.atomic. The contrast to CachedCohort is accurate: CachedCohortWrapper.save_new_cache_entry wraps the identical pattern in transaction.at


### 16. 🟨 LOW — Only caching layer for concept stats / cohort counts is off by default, with no short-TTL fallback on hot paths

- **Category:** caching  
- **Verification:** CONFIRMED (severity adjusted from medium)  
- **Location:** `chiron/chiron_settings.py:246`

**What it is.** CHIRON_USE_CACHES defaults False (line 246). Both persistent caches gate on it: CachedConceptStatsWrapper.find_matching_cache_entry returns None (cached_concept_stats.py:44-45) and save no-ops (55-60); same for CachedCohortWrapper (cached_cohort.py:47-48). With it off, every concept-stats request fully recomputes preprocess_statistics, which issues multiple separate research-DB queries - e.g. CohortDefCategory.preprocess_statistics runs get_subjects_with_missing_values_count + get_missing_values_count + get_unique_values_with_counts (chiron/processors/cohort_def/category.py:44-47), and CohortDefNumber runs ~8 (chiron/processors/cohort_def/number.py:44-57: min/max/avg/non-null count/subject count/histogram). Every cohort count re-runs a subject-count SQL (chiron/query_engine/postgres/querytool.py:100-130). The only active dedup is the per-instance in-memory StatTool.cache (abstract_stattool.py:55), which helps within one request but does nothing across requests, so identical repeat opens (same user re-opening a concept, or many users sharing the empty baseline cohort) pay full cost each time. The warm-cache machinery already exists (cache_concepts / cache_reports in chiron/cache/cache_utils.py) but is unused when the flag is off.

**Impact.** In the demo config the stats panel and cohort-count endpoints do N research-DB round-trips on every open with zero cross-request reuse; heavy pages feel slow and load the analytics DB unnecessarily.

**Fix.** Primary remedy is configuration, not code: set CHIRON_USE_CACHES=True in the demo/production project settings so the existing persistent caches (CachedConceptStats / CachedCohort) activate and the already-wired post-ETL warm-up (cache_utils.cache_concepts / cache_reports in chiron_etl.py:150-153) pre-populates the empty-baseline stats. Keep it False only in dev where the data dictionary changes. The short-TTL Django-cache fallback keyed on dataset+cohort_def_hash+subject_permission_hash+concept_id+prefilter_value is a reasonable optional enhancement for cases where the deployer wants some cross-request reuse without the full persistent cache, but it is net-new functionality and should be scoped as such.

> _Verifier note:_ Every cited line checks out. chiron_settings.py:246 sets CHIRON_USE_CACHES default False (with a docstring noting the dev-staleness rationale). Both persistent-cache wrappers short-circuit when off: cached_concept_stats.py:44-45 returns None and :55-60 no-ops; cached_cohort.py:47-48 / :56-61 same. cohort_def_processor.py:67-95 confirms the flow — with the flag off, find_matching_cache_entry returns None so get_statistics falls straight into preprocess_statistics(cd) and save_new_cache_entry is a no-op, meaning full recompute every request. category.py:44-47 issues 3 distinct research-DB querie


### 17. 🟨 LOW — Cache wrappers eagerly compute hashes (incl. a DB query) even when caching is disabled, twice on the cohort-count path

- **Category:** redundant-compute  
- **Verification:** CONFIRMED  
- **Location:** `chiron/cache/cached_concept_stats.py:15-24`

**What it is.** CachedConceptStatsWrapper.__init__ calls set_subject_permission_hash (line 23) and set_cohort_def_hash (line 24) unconditionally; set_subject_permission_hash -> hashing.create_subject_permission_hash -> chironuser.list_concepts_for_allowed_subjects() which runs PermissionGroup.dataset_uses_permission_groups (a query, data_definition_models.py:727-735) plus permission_groups.all(), and set_cohort_def_hash serializes the whole cohort_def to JSON + md5. The CHIRON_USE_CACHES check happens only later inside find_matching_cache_entry/save (lines 44, 56), so all of this runs and is discarded when caches are off. get_statistics constructs this wrapper on every call (cohort_def_processor.py:81). CachedCohortWrapper has the same pattern (cached_cohort.py:15-19), and QueryToolPostgres.get_cohort_count constructs it TWICE per count - once for read (querytool.py:114) and again for the write attempt (querytool.py:128) - doubling the wasted hashing/DB work when caches are disabled.

**Impact.** Each stats request and each cohort count performs 1-2 needless permission-group DB queries plus JSON serialization/hashing that is immediately thrown away in the default (caches-off) configuration.

**Fix.** Compute the hashes lazily (first access via a cached property) so nothing runs when caches are disabled, since find_matching_cache_entry/save_new_cache_entry short-circuit on CHIRON_USE_CACHES before touching them. That single change fixes both the eager-work-when-off problem and the double-construction cost in get_cohort_count (the second wrapper would never trigger hashing when caches are off). Alternatively, gate the whole cache read/write block in get_cohort_count on chiron_settings.CHIRON_USE_CACHES (and reuse one wrapper instance across the read/write branches) rather than early-returning inside the constructor, which would leave the hash attributes unset if CHIRON_USE_CACHES is later true within the same instance.

> _Verifier note:_ Every link in the claim verified against source. cached_concept_stats.py:15-24: __init__ unconditionally calls set_subject_permission_hash() (line 23) and set_cohort_def_hash() (line 24); the CHIRON_USE_CACHES guard exists only inside find_matching_cache_entry (line 44) and save_new_cache_entry (line 56), so the hashing always runs even when caches are off. set_subject_permission_hash -> hashing.create_subject_permission_hash (hashing.py:18) -> chironuser.list_concepts_for_allowed_subjects(); for a real ChironUser (user_models.py:148) this executes PermissionGroup.dataset_uses_permission_group


### 18. 🟨 LOW — Dead DEPRECATED viewset + its dead test are never wired in but still shipped

- **Category:** dead-code  
- **Verification:** CONFIRMED (severity adjusted from medium)  
- **Location:** `chiron/api/viewsets/user_created_content_DEPRECATED.py:1-95; chiron/api/tests/DEPRECATED_test_user_created_content.py:1-242; chiron/api/urls.py:24-26; chiron/api/viewsets/__init__.py`

**What it is.** user_created_content_DEPRECATED.py defines UserCreatedContentViewSet (95 lines) but it is NOT imported in chiron/api/viewsets/__init__.py (confirmed — __all__ lists 14 viewsets, none of them this one) and its router registration is commented out in api/urls.py:24-26. Its companion test file DEPRECATED_test_user_created_content.py (242 lines) is doubly dead: (a) pytest.ini sets `python_files = test_*.py`, and the filename starts with `DEPRECATED_`, so pytest never collects it; (b) it calls reverse("chiron:api:user_created_content-list") / "...-detail" (lines 127,136,151,157,192,213,227,236) but that route name is not registered in either api/urls.py or api_v2/urls.py, so every test would raise NoReverseMatch if it ever ran. The functionality was superseded by ReportViewSet (report.py) whose get_queryset reproduces the same type/state/search/public/share_with filtering. Total 337 lines of dead code.

**Impact.** 337 lines of dead, un-runnable code that misleads maintainers into thinking there is a UserCreatedContent endpoint and a passing test for it. Zero runtime cost but real cognitive/maintenance cost and false test-coverage impression.

**Fix.** Delete both files (chiron/api/viewsets/user_created_content_DEPRECATED.py and chiron/api/tests/DEPRECATED_test_user_created_content.py) and remove the commented router block at chiron/api/urls.py:24-26. No import or __all__ changes are needed since the viewset was never imported. Safe: repo-wide grep confirms no live references.

> _Verifier note:_ Verified every claim against source. (1) chiron/api/viewsets/user_created_content_DEPRECATED.py defines UserCreatedContentViewSet (a ModelViewSet, ~95 lines). (2) chiron/api/viewsets/__init__.py imports 14 viewsets and __all__ lists exactly 14, none being UserCreatedContentViewSet — so viewsets.UserCreatedContentViewSet isn't even an attribute. (3) api/urls.py:24-26 is the commented-out router.register block, verbatim as claimed. (4) A repo-wide grep for user_created_content / UserCreatedContentViewSet finds only the commented urls.py line, the viewset's own self-references, and the DEPRECATED


### 19. 🟨 LOW — TimeStampedModel abstract base defined 4 times identically

- **Category:** duplicated-code  
- **Verification:** CONFIRMED  
- **Location:** `chiron/models/user_models.py:26; chiron/models/cache_models.py:9; chiron/models/data_definition_models.py:27; chiron/models/processor_models.py:9`

**What it is.** The identical abstract model `class TimeStampedModel(models.Model): created = DateTimeField(auto_now_add=True); modified = DateTimeField(auto_now=True); class Meta: abstract=True` is copy-pasted byte-for-byte into four separate model modules. models/__init__.py does `from .user_models import *`, `from .data_definition_models import *`, etc., so the name TimeStampedModel is bound and then re-bound four times in the package namespace; models.TimeStampedModel currently resolves to whichever module is imported last (cache_models). It works only because all four definitions are identical — the moment one is edited (e.g. adding a field), the others silently diverge and which one 'wins' at models.TimeStampedModel depends on import order in __init__.py.

**Impact.** Fragile: an edit to one copy produces inconsistent inheritance and a subtle, hard-to-trace bug. Also confuses static analysis and readers. No runtime cost today, purely a correctness/maintenance hazard.

**Fix.** Define TimeStampedModel once in a new chiron/models/base.py, then `from .base import TimeStampedModel` in the four modules (place the base import first in __init__.py). Normalize line endings to LF while consolidating.

> _Verifier note:_ Read all four cited locations: chiron/models/user_models.py:26, cache_models.py:9, data_definition_models.py:27, processor_models.py:9 each define `class TimeStampedModel(models.Model)` with created=DateTimeField(auto_now_add=True), modified=DateTimeField(auto_now=True), and Meta.abstract=True. MD5 hashing showed the bodies split into two groups, but the ONLY difference is line endings (user_models/cache_models = LF, data_definition/processor = CRLF); they are semantically identical, so "byte-for-byte" is a minor overstatement. chiron/models/__init__.py does `from .X import *` for user_models,


### 20. 🟨 LOW — Management command _chiron_clear_all_concepts.py is un-invokable (leading underscore) and mislabeled

- **Category:** dead-code  
- **Verification:** CONFIRMED  
- **Location:** `chiron/management/commands/_chiron_clear_all_concepts.py:1-45`

**What it is.** Django's command discovery (django.core.management.find_commands) filters out module names that start with '_'. Because this file is named `_chiron_clear_all_concepts.py`, `manage.py` will never list or run it — it is effectively disabled dead code. No other file references it (grep of chiron/, docs/, test_project/ returns nothing). Additionally its `help` string is a wrong copy-paste: it reads "Populates tables for schema (Instrument and Event) but not Field definitions" while handle() actually does the opposite — it deletes ALL Concept, Category, Source, Collection and AutocreatedField rows (a destructive operation).

**Impact.** 45 lines of dead code. If someone renamed it to remove the underscore to 'fix' it, they would expose a highly destructive mass-delete command with a misleading help text. Better to remove or clearly quarantine it.

**Fix.** Delete the file. If it is intentionally retained as a manual dev utility, it does not belong under management/commands (it can never run there) — move it to a scripts/ directory or fold it into a normal command with an explicit confirmation prompt, and rewrite the help string to state that it deletes ALL Concept/Category/Source/Collection/AutocreatedField rows. Also drop the unused helpers (slug_to_name, random_string, print_out, print_err).

> _Verifier note:_ Every claim checks out against the actual code. (1) The file is literally named `_chiron_clear_all_concepts.py` (leading underscore). I confirmed the installed Django's find_commands at .venv/lib/python3.12/site-packages/django/core/management/__init__.py:38 filters with `if not is_pkg and not name.startswith("_")`, so this module is never listed or runnable via manage.py — it is genuinely un-invokable dead code. (2) grep for `chiron_clear_all_concepts` across the repo (chiron/, docs/, test_project/, scripts) returns nothing; the only `clear_all` hits are unrelated cohort/analysis transformati


### 21. 🟨 LOW — Seven commented-out URL routes referencing already-deleted view functions

- **Category:** dead-code  
- **Verification:** CONFIRMED  
- **Location:** `chiron/urls.py:30-34,66-79,88-98; chiron/views/views_ajax_table_def.py:42-56`

**What it is.** chiron/urls.py carries 7 commented-out path() blocks: ajax_get_td_entry_form (30-34), three query_troubleshooting sub-routes results_table/cohort_count/analysis_output (66-79), and three single_subject routes single_subject_timeline / single_subject/<collection_name> / single_subject (88-98). Grepping views/ confirms these view callables no longer exist — query_troubleshooting_results_table/_cohort_count/_analysis_output and single_subject* are entirely gone, and ajax_get_td_entry_form is itself a commented-out block at views_ajax_table_def.py:42-56. So these comments reference code that cannot be uncommented without also rewriting the views.

**Impact.** Dead commented code in the primary URLConf implies routes/features that don't exist and cannot be trivially restored, misleading anyone reading the routing table. Cosmetic but a routine cleanup.

**Fix.** Delete the 4 commented path() blocks in chiron/urls.py (lines 29-33, 58-72, 90-100) and the commented ajax_get_td_entry_form body in views_ajax_table_def.py (lines 42-55), relying on git history. Note the related loose end: chiron/templates/chiron/backend/query_troubleshooting.html lines 19/24/29 still reference the removed URL names via {% url 'chiron:query_troubleshooting_*' %}, which would raise NoReverseMatch if that template path is rendered — worth cleaning up in the same pass.

> _Verifier note:_ I opened chiron/urls.py and confirmed 7 commented-out path() blocks: ajax_get_td_entry_form (lines 29-33), the three query_troubleshooting sub-routes results_table/cohort_count/analysis_output (lines 58-72), and the three single_subject routes single_subject_timeline / single_subject/<collection_name> / single_subject (lines 90-100). I opened views_ajax_table_def.py and confirmed ajax_get_td_entry_form exists only as a commented-out body at lines 42-55 (its def is `# def ajax_get_td_entry_form(request):`). A recursive grep for `def query_troubleshooting_results_table\|_cohort_count\|_analysis_


### 22. 🟨 LOW — check_permission_group re-runs an identical PermissionGroup COUNT for every concept and every category

- **Category:** redundant-queries  
- **Verification:** CONFIRMED (severity adjusted from medium)  
- **Location:** `chiron/models/data_definition_models.py:1048 (Concept.check_permission_group), 826 (Category.check_permission_group); called per-item in chiron/api/viewsets/concept_category.py:29-40 and both concept viewsets`

**What it is.** Both Concept.check_permission_group and Category.check_permission_group begin with `PermissionGroup.objects.filter(dataset=chironuser.dataset).count()` to decide whether permission filtering applies. This value is constant for the whole request but is queried once per concept and once per category. In the concept-category tree endpoint, _filter_categories_on_user_permissions (concept_category.py:35-40) loops all categories calling check_permission_group (one COUNT each) and _filter_concepts_on_user_permissions (lines 27-33) loops all concepts calling user_can_use_concept_in_table_def -> check_permission_group (one COUNT each), then both re-query the surviving ids. This endpoint is hit repeatedly as the user expands the category tree.

**Impact.** Every tree-drill request pays one redundant PermissionGroup COUNT per node in that level, plus the throw-away-and-requery pattern. Multiplies DB round-trips on the most interactive part of the query builder.

**Fix.** Compute the flag once per request and thread it through, or memoize on the chironuser/request object: `uses_pg = PermissionGroup.dataset_uses_permission_groups(chironuser.dataset)` computed once in _fetch_concepts_and_categories and passed into check_permission_group / user_can_use_concept_in_table_def so the count is not re-run per node. Note the existing dataset_uses_permission_groups helper itself runs an uncached query, so the caching must happen at the request level, not by simply swapping in that helper. For larger wins also address the other per-node queries (prefetch permissiongroup_set and avoid the get_top_level_parent parent-walk), since those dominate over the COUNT.

> _Verifier note:_ Verified all cited lines. Concept.check_permission_group (line 1048) and Category.check_permission_group (line 826) both begin with the identical `PermissionGroup.objects.filter(dataset=chironuser.dataset).count()`. In concept_category.py, _filter_categories_on_user_permissions (lines 35-40) calls check_permission_group once per category and then re-queries survivors with Category.objects.filter(pk__in=...), and _filter_concepts_on_user_permissions (lines 27-33) calls user_can_use_concept_in_table_def per concept, which invokes check_permission_group at line 1171, then re-queries with Concept.


### 23. 🟨 LOW — get_request_dataset issues two queries (count then index) on the single-dataset path, on every request

- **Category:** redundant-queries  
- **Verification:** CONFIRMED  
- **Location:** `chiron/authorization.py:39-41`

**What it is.** When no dataset_id is in the session, get_request_dataset does `qDataset = Dataset.objects.all(); if qDataset.count() == 1: oDataset = qDataset[0]` — a COUNT query followed by a separate LIMIT query. get_request_dataset runs on every request via the DatasetSelector permission (chiron/api/permissions.py:16) and the dataset_selector decorator, so it is a hot path.

**Impact.** One redundant query per request in single-dataset deployments (the common case). Small per-request cost but universal.

**Fix.** datasets = list(models.Dataset.objects.all()[:2]); if len(datasets) == 1: oDataset = datasets[0] — one LIMIT 2 query, still distinguishing exactly-one from more-than-one. Equivalent to the proposed fix.

> _Verifier note:_ Read chiron/authorization.py:39-41 in the backend repo (/Users/pot95a/2026/new_chiron/is4r-chiron-develop; the UI cwd has no such file, but line numbers match exactly). The else-branch runs `qDataset = Dataset.objects.all(); if qDataset.count() == 1: oDataset = qDataset[0]`. Django's QuerySet.count() emits SELECT COUNT(*) and does not cache result rows, so the subsequent qDataset[0] on the unevaluated queryset issues a second SELECT ... LIMIT 1 — two queries confirmed. Verified the hot path: get_request_dataset is called by DatasetSelector (api/permissions.py:16), which is attached to ~12 API 


### 24. 🟨 LOW — No response compression (GZip) configured for large JSON/CSV payloads

- **Category:** missing-compression  
- **Verification:** PLAUSIBLE  
- **Location:** `performance_project/project/settings.py:55-63; test_project/project/settings.py (MIDDLEWARE)`

**What it is.** Neither bundled project settings enables django.middleware.gzip.GZipMiddleware (MIDDLEWARE lists only security/session/common/csrf/auth/messages/clickjacking, plus ViewAsOtherUser in test_project). The endpoints in scope return highly compressible payloads (repetitive tabular JSON from concept lists up to 1000 items, reports lists up to 10000 items, and full JSON exports). Note: chiron is packaged as a reusable Django app, so the deploying project controls middleware — hence lower confidence that production lacks it.

**Impact.** Large JSON/CSV responses travel uncompressed; tabular/JSON data typically compresses 80-90%, so transfer size and client load times are several times larger than necessary over the wire.

**Fix.** This is a deployment recommendation, not an application-code defect. Prefer enabling gzip at the reverse proxy or CDN (e.g. nginx: gzip on; gzip_types application/json text/csv;), which is the standard place for a reusable Django app. Alternatively add django.middleware.gzip.GZipMiddleware near the top of MIDDLEWARE in the actual production settings (note the BREACH consideration for authenticated responses). Confirm the real production settings before treating this as an outstanding issue, since the bundled performance_project/test_project are only examples.

> _Verifier note:_ Verified both cited settings files directly. performance_project/project/settings.py:55-63 lists MIDDLEWARE as SecurityMiddleware, SessionMiddleware, CommonMiddleware, CsrfViewMiddleware, AuthenticationMiddleware, MessageMiddleware, XFrameOptionsMiddleware only. test_project/project/settings.py:54-63 has the same seven plus chiron.middleware.view_as_other_user.ViewAsOtherUser. Neither enables django.middleware.gzip.GZipMiddleware, and a repo-wide grep finds no GZip config outside site-packages. The large-payload premise also checks out: chiron/api_v2/viewsets/concept.py:28-30 sets max_page_siz


### 25. 🟨 LOW — No composite (subject_id, event_date) index for the subject-join + event-date-range access pattern

- **Category:** index-strategy  
- **Verification:** CONFIRMED  
- **Location:** `chiron/query_engine/postgres/sql_alchemy_queries/event_filters.py:28-49; chiron/query_engine/postgres/sql_alchemy_queries/sections/from_builder.py:96; chiron/query_engine/postgres/database.py:347-419`

**What it is.** Subcollection event tables are joined to subjects on `_subject_id` (from_builder.py:96) and then filtered by event-date range on the collection's event_date_field/event_end_date_field (event_filters.py get_clause_for_date_range etc., 28-49). `_subject_id` is btree-indexed at table creation (database.py:379) and the event-date concept gets its own single-column btree from create_indexes(), but there is no composite index on (_subject_id, <event_date_field>). For 'events for these subjects within date range' patterns Postgres must combine two separate indexes (bitmap AND) or pick one and filter the rest.

**Impact.** For event/encounter collections with high row counts, cohort-plus-date-window queries do more heap work than a covering composite index would require. This is an optimization opportunity rather than a correctness gap, since single-column indexes already exist.

**Fix.** The proposed fix (add composite (_subject_id, event_date_field) / (_subject_id, event_end_date_field) indexes in create_indexes() for collections defining an event_date_field) is sound and code-backed. Two caveats worth attaching, consistent with the low severity: (a) real speedup is planner- and data-dependent — the composite helps most in nested-loop cohort lookups; for hash/merge joins a single-column date index already suffices for pushdown, so the benefit is genuinely "modest but measurable" as stated, not guaranteed. (b) Apply selectively to the largest event/encounter collections only, since every added composite index adds write-amplification and storage on ingest; blanket-adding one per event collection could regress load performance.

> _Verifier note:_ I opened all cited code (files actually live under /Users/pot95a/2026/new_chiron/is4r-chiron-develop/, not chiron-benchmark/). Every factual claim checks out:  1. Access pattern exists. from_builder.py:96 (`_join_collection_table_by_subject_id`) joins the subcollection table to the subject via equality `subject_table.c._id == table.c._subject_id`. event_filters.py:28-49 (get_clause_for_date_range / age_in_days_range, and the interval variants 52-114) build `>=`/`<=` range predicates on start_column/end_column. where_builder.py:207-228 shows those columns are exactly `oCollection.event_date_fie

