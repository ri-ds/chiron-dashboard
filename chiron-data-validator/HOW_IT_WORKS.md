# How the Chiron Data Validator Works

This document explains **exactly what the tool does when you run it** — which API calls it
makes, in what order, what comes back, and what happens to that data. For install/usage
commands see [README.md](README.md); this file is the "what's actually happening under the
hood" companion to it.

The tool is a single Python process. It never touches a database directly — everything it
knows about your data comes from HTTP calls to Chiron's own REST API, exactly as if it were a
browser. It makes no write calls at all (no POST/PUT/DELETE to Chiron) — it only reads.

---

## 1. The end-to-end flow

```
 you run:  python chiron_validator.py [options]
      |
      v
 ┌────────────────────────────────────────────────────────────────────────┐
 │ STEP 1 — LOGIN (chironval/client.py: ChironClient.login)               │
 │   GET  <base-url>/accounts/login/                                      │
 │        -> just to receive a `csrftoken` cookie (Django's CSRF dance)   │
 │   POST <base-url>/accounts/login/                                      │
 │        body: username, password, csrfmiddlewaretoken                  │
 │        -> success = HTTP 302 + a `sessionid` cookie gets set           │
 │   Every request after this reuses the same cookie jar (one             │
 │   requests.Session object), so you only log in once per run.           │
 └────────────────────────────────────────────────────────────────────────┘
      |
      v
 ┌────────────────────────────────────────────────────────────────────────┐
 │ STEP 2 — DISCOVER DATASETS (client.get_datasets)                       │
 │   GET  /api/v2/dataset/                                                │
 │   <-   { "datasets": [ {unique_id, name, ...}, ... ] }                 │
 │   This becomes the list of dataset_string values ("dataset1_stored",   │
 │   etc.) the rest of the run will loop over. --dataset filters this     │
 │   list down; with no filter, every dataset your user account can see   │
 │   is used.                                                             │
 └────────────────────────────────────────────────────────────────────────┘
      |
      v   (this whole block repeats once per dataset — chironval/runner.py: run_dataset)
 ┌────────────────────────────────────────────────────────────────────────┐
 │ STEP 3 — DATASET DETAIL (client.get_dataset_detail)                    │
 │   GET  /api/v2/dataset/<dataset_string>/                               │
 │   <-   { subjectCount, accessLevel, ... }                              │
 │   subjectCount becomes the denominator for the missing-rate check      │
 │   later. If it's missing/unparseable, that check just skips (no crash).│
 └────────────────────────────────────────────────────────────────────────┘
      |
      v
 ┌────────────────────────────────────────────────────────────────────────┐
 │ STEP 4 — DISCOVER CONCEPTS (client.get_concepts)                       │
 │   GET  /api/v2/<dataset_string>/concepts/?page_size=100                │
 │   <-   { "results": [ {permanent_id, name, concept_type, ...}, ... ],  │
 │          "next": "<url-or-null>" }                                     │
 │   If "next" isn't null, the client follows it (and keeps following     │
 │   it) until it IS null — this is how it gets every concept on a        │
 │   dataset with more than one page, not just the first 100.             │
 │   A "concept" here = one field/variable in the dataset (e.g.           │
 │   "gestational_age_weeks", "primary_diagnosis_code").                  │
 └────────────────────────────────────────────────────────────────────────┘
      |
      v   (this block repeats once per concept discovered above)
 ┌────────────────────────────────────────────────────────────────────────┐
 │ STEP 5 — CONCEPT STATISTICS (client.get_concept_statistics)            │
 │   GET  /api/v2/<dataset_string>/concepts/<permanent_id>/               │
 │            ?include_statistics=true                                   │
 │   <-   { ..., "statistics": {                                         │
 │              count_missing_values, count_subjects_with_missing_values,│
 │              stats: {min, max, avg, count_non_null, ...},   (numbers) │
 │              histogram_data: [[bin_label, count], ...],     (numbers) │
 │              values: [{category, count, uniquePatientCount}, ...]     │
 │                        or ["val1","val2",...] for text                │
 │         } }                                                            │
 │   No raw patient rows are ever fetched — only these pre-computed,      │
 │   already-access-level-gated summary statistics. This is a            │
 │   deliberate design choice (see "Why statistics, not raw rows" below). │
 │                                                                          │
 │   Some responses aren't usable stats at all — these are NOT treated    │
 │   as crashes, just recorded as a "skipped concept" and the run         │
 │   continues:                                                           │
 │     - HTTP 403            -> your user isn't allowed to see this one   │
 │     - HTTP 404            -> bad id (shouldn't normally happen)        │
 │     - 200 with statistics.error -> Chiron's own in-band error, e.g.    │
 │       "prefiltered, needs a prefilter_value" or a permission message   │
 │     - a network error     -> one flaky call doesn't kill the whole run │
 └────────────────────────────────────────────────────────────────────────┘
      |
      v
 ┌────────────────────────────────────────────────────────────────────────┐
 │ STEP 6 — RUN THE 4 CHECKS (chironval/checks.py: run_all_checks)        │
 │   Pure, in-memory, no more network calls. Takes the concept's          │
 │   metadata + statistics from step 5 and returns zero or more Issue     │
 │   objects. See section 2 below for what each check actually does.      │
 └────────────────────────────────────────────────────────────────────────┘
      |
      v  (back up to STEP 3 for the next dataset, until all are done)
      |
      v
 ┌────────────────────────────────────────────────────────────────────────┐
 │ STEP 7 — REPORT (chironval/report.py)                                  │
 │   All Issues + skipped-concept records, grouped by dataset -> concept, │
 │   printed to the console. If --json-out was given, the same data is    │
 │   also written out as structured JSON (generated_at, server,           │
 │   limitation_notice, per-dataset issues/skipped, summary.issues_by_kind)│
 │   Process exit code: 0 = no issues, 1 = ran fine but found issues,     │
 │   2 = couldn't complete the run (bad login, unreachable server, a      │
 │   dataset that errored out, etc).                                     │
 └────────────────────────────────────────────────────────────────────────┘
```

**Where each piece of code lives**, matching the steps above:

| Step | File | Function |
|---|---|---|
| 1. Login | `chironval/client.py` | `ChironClient.login` |
| 2. List datasets | `chironval/client.py` | `ChironClient.get_datasets` |
| 3. Dataset detail | `chironval/client.py` | `ChironClient.get_dataset_detail` |
| 4. List concepts (paginated) | `chironval/client.py` | `ChironClient.get_concepts` |
| 5. Concept statistics | `chironval/client.py` | `ChironClient.get_concept_statistics` |
| 3–6 orchestration, per dataset | `chironval/runner.py` | `run_dataset`, `run_all` |
| 6. The 4 checks themselves | `chironval/checks.py` | `check_missing_rate`, `check_numeric_outliers`, `check_label_consistency`, `check_type_plausibility` |
| 7. Console + JSON report | `chironval/report.py` | `print_console_report`, `build_json_report`, `write_json_report` |
| CLI wiring / exit codes | `chironval/cli.py` | `main` |
| Data shapes passed between all of the above | `chironval/models.py` | `Issue`, `SkippedConcept`, `DatasetRunResult` |

---

## 2. The four checks — what actually fires, and on what

All four run against the **statistics payload from step 5**, not raw data. Each is documented
in detail (with the exact thresholds as code comments) in `chironval/checks.py`.

| # | Check | Fires when | Issue kind(s) | Severity |
|---|---|---|---|---|
| 1 | Missing/null rate | `count_missing_values / total_subjects` > `--missing-threshold` (default 30%) | `high_missingness` | medium |
| 2 | Numeric outliers | An extreme histogram bin is isolated (gap of empty bins) from the bulk, holding ≤10% of its nearest populated neighbor's count. Falls back to a min/avg/max skew check when no histogram is available. | `numeric_outlier` / `possible_skewed_distribution` (fallback) | medium / low |
| 3 | Label consistency | Two or more *distinct raw* category/text values normalize (lowercase+trim+collapse-whitespace) to the same string (e.g. "Male"/"male") → likely the same real value entered inconsistently. Separately, any category occurring exactly once is flagged as a possible typo/rare value. | `label_inconsistency` / `possible_typo_or_rare_value` | high / low |
| 4 | Type plausibility | A `category`-type concept has unusually many distinct values (>50 absolute, or >20% of subjects when there are ≥20 subjects) **and** most of those distinct values are singletons (i.e. it actually behaves like free text, not a real recurring vocabulary like ICD-10 codes) | `possible_metadata_mismatch` | low |

**Why "symptom, not diagnosis" language is everywhere:** none of these four checks can see a
raw source value. They only see numbers Chiron already computed. So they can tell you *where
to look*, not *what the original bad value was*.

---

## 3. Why statistics, not raw rows — the one thing to understand about scope

This tool deliberately reads the `?include_statistics=true` endpoint (pre-aggregated counts,
histograms, value distributions) rather than pulling every raw row. Two consequences fall out
of that choice, both worth knowing before you interpret a report:

1. **It's cheap and safe.** One HTTP call per concept, no matter how many subjects/records
   exist behind it, and it can never accidentally export a PHI dataset to disk.
2. **It inherits a real blind spot from Chiron itself.** Chiron's ETL layer casts every
   incoming value to its declared type and **silently converts anything that fails that cast
   to NULL, before it's ever stored.** So by the time this tool (or anyone using the API) sees
   a "missing" value, there is no way to tell whether it was genuinely blank in the source data
   or whether it arrived malformed and got quietly nulled during ETL. Chiron *does* keep a
   record of which happened (`ConceptIssueEtlLog`, internal to Chiron) — but that table isn't
   exposed by any current API endpoint, so this tool structurally cannot read it. Treat
   `high_missingness` as "go look here", not "here's what was wrong."

If you ever want the *actual* malformed-value records (not just an elevated missing-rate proxy
for them), that requires a new read-only endpoint added to Chiron itself — this tool can't get
there through the API as it exists today.

---

## 4. What's explicitly NOT implemented yet

- **Cross-field/row-level consistency rules** (e.g. "admission date ≤ discharge date") were
  scoped out. Getting real rows requires Chiron's `table_def` + `query_tools/preview` flow,
  which is *stateful* server-side (there's no way to pass the fields you want inline per
  request — you POST to set an "active" table definition, then GET reads whatever is currently
  active). Doing this safely without disturbing a shared live server needs more care than fit
  in v1. See README.md's own write-up for the recommended approach if this gets picked up next.
- Concept types `date_deid`, `ontology`, and `undefined` were never present in the local demo
  data, so their statistics shapes are unverified against a real payload (the code path is
  defensive/won't crash, per the label-consistency fix, but is untested on real data of those
  types).
- No retry/backoff on transient network errors — one failed request to a single concept becomes
  a skip, not a retry.

---

## 5. Getting started

```bash
cd chiron-data-validator
source venv/bin/activate        # dependencies are already installed here

# Validate everything on the local dev server (defaults: admin/demo1234, http://127.0.0.1:8000)
python chiron_validator.py

# Point it at a real deployment instead
python chiron_validator.py --base-url https://heartsmart.example.org \
    --username myuser --password 'hunter2'

# Narrow to specific datasets, tune the missing-value threshold, save a JSON report
python chiron_validator.py --dataset dataset1_stored --dataset dataset2_stored \
    --missing-threshold 0.15 --json-out report.json

python chiron_validator.py --help     # full option list + exit-code meanings
```

Run the test suite (pure, no server needed — these use constructed synthetic payloads with
known issues baked in, which is how the checks are actually proven correct since the local demo
data is too clean to exercise most of them):

```bash
python -m unittest discover -v
```
