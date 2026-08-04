# Chiron Data Validator

A standalone Python CLI that checks data quality in a Chiron research-data
platform by talking **only** to Chiron's existing REST API (`/api/v2/...`) -
no direct database access, ever.

It logs in as a real Chiron user (Django session + CSRF), discovers every
dataset visible to that user, pulls each concept's statistics, and runs four
checks: missing/null-rate, numeric outliers, category/text label
consistency, and category type-plausibility. Output is a grouped
human-readable console report plus, optionally, a structured JSON report.

Every API shape referenced below was verified against a live Chiron dev
instance at `http://127.0.0.1:8000` on 2026-07-15 (not guessed from source)
by calling the endpoints directly and inspecting the real JSON.

## Install

```bash
cd chiron-data-validator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Only dependency: `requests`. Everything else (`argparse`, `statistics`,
`unittest`, `dataclasses`, `re`) is Python stdlib.

## Usage

```bash
# Validate every dataset on the local dev server, using the default admin account
python chiron_validator.py

# Explicit subcommand form (equivalent to the above)
python chiron_validator.py validate

# Point at a different deployment (e.g. a future "HeartSmart" instance) with
# different credentials
python chiron_validator.py --base-url https://heartsmart.example.org \
    --username myuser --password 'hunter2'

# Only check specific datasets (repeatable), with a stricter missing-value
# threshold, and also write a machine-readable JSON report
python chiron_validator.py --dataset dataset1_stored --dataset dataset2_stored \
    --missing-threshold 0.15 --json-out report.json

# See exactly what HTTP calls are being made, and why any concept was skipped
python chiron_validator.py --verbose
```

Full `--help` output (also embeds the missing-rate limitation - see below)
is available via `python chiron_validator.py --help`.

### CLI arguments

| Flag | Default | Meaning |
|---|---|---|
| `--base-url` | `http://127.0.0.1:8000` | Chiron server root |
| `--username` | `admin` | Login username |
| `--password` | `demo1234` | Login password |
| `--dataset` | *(all datasets)* | Limit to this dataset's `unique_id`. Repeatable. |
| `--missing-threshold` | `0.3` | Flag `high_missingness` when `count_missing_values / total_subjects` exceeds this fraction |
| `--json-out` | *(none)* | Also write a structured JSON report to this path |
| `--verbose` | off | Print every HTTP request and every skip reason |
| `--page-size` | `100` | Concepts-list page size (DRF's server-side max is 1000) |
| `--timeout` | `30.0` | Per-request HTTP timeout, seconds |

### Exit codes

- `0` - ran cleanly, no issues found
- `1` - ran cleanly, one or more data-quality issues found
- `2` - could not complete the run (bad login, unreachable server, unknown
  `--dataset`, or a dataset that errored outright, e.g. a 403)

## Auth flow

Chiron uses plain Django session + CSRF auth; there is no separate token
endpoint. Verified empirically:

1. `GET  <base_url>/accounts/login/` - sets a `csrftoken` cookie.
2. `POST <base_url>/accounts/login/` with form data
   `username`, `password`, `csrfmiddlewaretoken=<csrftoken cookie value>`,
   and header `Referer: <base_url>/accounts/login/`.
3. **Success** = HTTP `302` **and** a `sessionid` cookie gets set. The demo
   server's login page re-renders as a plain `200` on failure with no
   reliably-scrapable error string, so this tool treats "302 + sessionid" as
   the sole success signal and anything else as a clean, reported failure
   (see `chironval/client.py::ChironClient.login`).
4. All subsequent calls reuse the same `requests.Session` (cookie jar).

Demo accounts on the reference server, password `demo1234` for all three:

- `admin` - full/PHI access
- `demouser` - de-identified access (some concepts return an in-band
  `{"statistics": {"error": "The user doesn't have permission..."}}` inside
  an HTTP 200 - handled as a graceful skip, not a crash)
- `agguser` - aggregate-only access (subject-level endpoints, including the
  concepts list itself, return a plain HTTP `403` - handled as a per-dataset
  error, not a crash of the whole run)

## API endpoints used

- `GET /api/v2/dataset/` - list datasets (`unique_id` is the dataset string
  used everywhere else)
- `GET /api/v2/dataset/<dataset_string>/` - one dataset's summary,
  specifically `subjectCount` (used as the denominator for missing-rate) and
  `accessLevel`
- `GET /api/v2/<dataset_string>/concepts/` - paginated concept list. This
  tool follows the DRF `next` link (a full absolute URL in this API) until
  it is `null`, so datasets with more than one page of concepts are not
  silently truncated.
- `GET /api/v2/<dataset_string>/concepts/<permanent_id>/?include_statistics=true`
  - concept detail + statistics. The **shape genuinely varies by
  `concept_type`** - confirmed by pulling real responses for `date`, `text`,
  `number`, `category`, `boolean`, `number_with_categories`, and `age`
  concepts from the live server:
  - `number` / `number_with_categories` / `age`: `stats.{count_non_null,
    min,max,avg,unique_patients}` (age uses `min_year/max_year/avg_year/
    min_day/max_day/avg_day` instead of a flat `avg`) plus `histogram_data`,
    an ordered list of `[bin_label, count]` pairs from lowest to highest bin.
  - `category` / `boolean`: `values` = list of
    `{"category": ..., "count": N, "uniquePatientCount": M}`.
  - `text`: `values` = flat list of **unique** raw strings, with **no**
    per-value counts.
  - `number_with_categories` concepts can carry **both** a `stats`/
    `histogram_data` block and a `values` block (numeric column with an
    optional free-text override) - this tool runs both the numeric and the
    label-consistency checks on it.
  - Concepts with `concept_for_prefilter` set return HTTP `200` with
    `{"statistics": {"error": "You must provide a prefilter value."}}` when
    no `prefilter_value` is supplied. This tool does not attempt to guess or
    enumerate prefilter values in v1 - it catches this, logs the concept as
    skipped (`reason_kind: "prefiltered"`), and moves on, per spec.

## Checks (v1)

1. **`high_missingness`** - `count_missing_values / total_subjects > --missing-threshold`.
   See **Limitations** below - this is the most important caveat in the
   whole tool.
2. **`numeric_outlier`** (+ fallback **`possible_skewed_distribution`**) -
   isolated extreme histogram bins, or a min/max/avg skew check when no
   histogram is available. The exact heuristic (documented in a code comment
   in `chironval/checks.py` right above `check_numeric_outliers`, for
   auditability) is:
   > A concept is flagged when, at the first or last histogram bin, that
   > bin's count is > 0, it is separated from the nearest non-empty bin by
   > at least one empty bin ("isolated"), **and** its count is <= 10% of
   > that nearest non-empty bin's count. This deliberately never parses bin
   > labels (which differ wildly by concept type: `"[1 - 2)"`, `"11y - 12y"`,
   > `"May 2019"`) - only bin position and count are used, so the same logic
   > applies uniformly across `number`/`age`/`date`-shaped histograms.
   >
   > When there's no histogram (rare, small-n concepts), the API only
   > exposes `count_non_null/min/max/avg` with no standard deviation, so a
   > real 3-sigma test isn't possible; instead a weak "mean sits far off
   > center" skew ratio is used and explicitly labeled low-severity.

   **False positives on real data are expected and systematic, not just
   theoretical:** an isolated extreme bin can just as easily be a small but
   genuinely real clinical subpopulation (e.g. a handful of
   extremely-preterm births sitting alone at the low edge of a
   gestational-age histogram, with a real gap before the term-birth bulk) as
   it can be a data error. This heuristic has no way to distinguish those two
   cases from bin counts alone, so `numeric_outlier` should be read the same
   way as `high_missingness` - a symptom worth a human look, never a verdict
   that the data is wrong. The issue message itself repeats this caveat.
3. **`label_inconsistency`** / **`possible_typo_or_rare_value`** - normalize
   every label (`lower().strip()`, collapse internal whitespace) and flag
   when 2+ *distinct raw* labels collide on one normalized string (e.g.
   `"Male"` / `"male"` / `" male"`). Singleton categories (`count == 1`) are
   flagged separately at lower severity. Text concepts (flat unique-value
   lists, no counts) get the collision check but not the singleton check -
   there is no count to check.
4. **`possible_metadata_mismatch`** - a `category` concept with implausibly
   many distinct values: more than 50 distinct values (absolute), or more
   than 20% of subjects distinct - the relative rule only applies once
   `total_subjects >= 20`, to avoid nonsense flags on tiny datasets (a
   4-subject dataset with 2 distinct values is already "50%"). High
   cardinality alone is not enough, though: a legitimate controlled
   vocabulary (ICD-10 codes, medication names, site codes, ...) can have
   dozens/hundreds of distinct values that each recur across many
   records/subjects, which is the opposite of what free text looks like (near
   -unique counts per distinct value). So this check also looks at the
   per-value `count` already present in the same statistics payload, and
   only fires when a real majority of the distinct values are themselves
   singletons (`count <= 1`) - i.e. the recurrence pattern actually looks
   free-text-like, not just "many labels". `values` shapes with no per-value
   counts fall back to the distinct-count-only thresholds.

All four check functions are pure (`chironval/checks.py`) - no HTTP calls -
specifically so they can be unit tested with constructed payloads that match
the real API shapes but bake in known issues. See **Testing** below.

## Limitations

**Missing/null-rate cannot distinguish "genuinely absent" from
"malformed-then-silently-nulled."** Chiron's ETL layer casts every incoming
value to its declared `concept_type` and **silently nulls anything that
fails that cast, before it is ever stored**. This means a concept this tool
flags as `high_missingness` might be:

- genuinely missing in the source data, or
- data that arrived malformed (wrong format, out-of-range, wrong type, ...)
  and was silently dropped by Chiron's ETL at import time.

The `/api/v2` statistics endpoints used by this tool report only the
post-ETL null count - they have no way to tell these two cases apart. The
only place that distinction actually exists is Chiron's internal
`ConceptIssueEtlLog` table, and **that table is not exposed by any current
Chiron API endpoint**, so this tool cannot read it, no matter how it's
called. This is stated deliberately in three places: this README, the CLI's
`--help` text, and the header of every generated report - so it is never
lost in a screenshot or a copy-paste of just the issue list.

If someone wants true ETL-cast-failure visibility (i.e. "show me the records
that were silently dropped, and why"), the correct fix is to add a new
read-only API endpoint to Chiron itself that exposes `ConceptIssueEtlLog` -
that is a change to the Chiron Django app, which is explicitly out of scope
for this tool (this tool is API-only, by design, and this repo does not
touch `is4r-chiron-develop/` or `is4r-chiron-ui-develop/` at all).

**Other known scope limits:**

- Numeric outlier detection is a cheap heuristic for a human to glance at,
  not a statistical test - see the exact rule under **Checks** above.
- `possible_typo_or_rare_value` naturally fires a lot on small datasets
  (every category value that happens to appear once looks like a
  "singleton") - this is expected on small demo/dev data and becomes a much
  more useful signal on real-sized production data.
- Concept types `date_deid`, `ontology`, and `undefined` were not present in
  the demo data used to build this tool, so their statistics shapes were
  never observed directly. The checks dispatch on the *shape* of the
  statistics payload (does it have `histogram_data`? is `values` a list of
  dicts or a list of strings?) rather than hardcoding on `concept_type`
  wherever practical, specifically so unfamiliar concept types degrade
  gracefully (skip, don't crash) instead of requiring foreknowledge of every
  possible shape.
- This tool does not attempt to supply `prefilter_value` for prefiltered
  concepts - it skips them and reports the skip. Enumerating and iterating
  every prefilter value for every prefiltered concept was judged out of
  scope for v1.

### Item 5 (cross-field consistency rules) - not implemented, here's why

The optional stretch goal (a user-supplied rule file like "concept A's value
must be <= concept B's value", evaluated over real rows) was investigated
but **deliberately not implemented** in this v1. What was confirmed
empirically against the live server:

- Setting the columns Chiron will return is a **stateful** operation: you
  `POST` to a `table_def` endpoint to change the dataset's *active*
  table-definition snapshot, and a later `GET` on the
  `query_tools/preview`-style endpoint reads that server-side active
  snapshot - there is no way to pass a `cohort_def`/`table_def` inline on
  the preview request itself.
- That statefulness means: (a) two concurrent validator runs against the
  same dataset could race and clobber each other's active table_def, (b) a
  crashed run could leave the dataset's active table_def in a
  validator-specific state that then leaks into the normal UI for other
  users of that dataset, and (c) the exact `table_def` request/response
  shape needs the same kind of empirical, response-in-hand verification the
  rest of this tool got, which didn't fit in the time available alongside
  making checks 1-4 solid and genuinely tested.

**Recommended approach for a v2**, if this is picked up:

1. Empirically capture the exact `POST` body Chiron's own UI sends to the
   `table_def` endpoint (browser dev tools against `is4r-chiron-ui-develop`
   while performing a manual "add column" action is the fastest way to get
   ground truth) for a couple of different concept-type combinations.
2. Snapshot-and-restore the dataset's *pre-existing* active `table_def`
   before the validator's own `POST`, and restore it in a `finally` block
   (or at minimum on any exception) so a validator run never leaves a
   dataset's UI in an altered state for other users - this is the main risk
   this stretch goal introduces that checks 1-4 don't have.
3. Only then implement the actual rule evaluation (row-by-row comparisons
   per a small JSON/YAML rule file) over whatever `query_tools/preview`
   returns.
4. Add an explicit `--allow-stateful` flag (opt-in, off by default) given
   the shared-state risk above, so nobody accidentally mutates a shared
   dataset's active view by just running the validator.

Shipping a half-working version of this (e.g. one that works against the
demo server's exact current state but is fragile to concurrent use, or that
doesn't restore the prior table_def) was judged worse than skipping it, per
the original task instructions.

## Testing

```bash
source venv/bin/activate
python -m unittest discover -v
```

`tests/test_checks.py` builds synthetic statistics payloads shaped exactly
like the real API responses (verified against the live server), with known
issues baked in on purpose - e.g. `"Male"`/`"male"`/`" male"` to prove the
label-consistency collision check fires, a histogram with a deliberately
isolated low/high bin to prove the outlier heuristic fires (and a smooth
histogram to prove it *doesn't* false-positive), a 40%-missing concept to
prove the threshold check fires at the default 0.3 threshold and a
10%-missing concept to prove it doesn't. This matters because the live demo
data is small and clean and does not exercise most of this logic by itself -
see the `--verbose` run against the live server, which fires only
`high_missingness` and `possible_typo_or_rare_value`, never
`numeric_outlier`, `label_inconsistency`, or `possible_metadata_mismatch`,
confirming these checks need the unit tests (not the demo data) to prove
they work. `tests/test_runner_helpers.py` covers the small pure helpers in
`chironval/runner.py` (skip-reason classification, `subjectCount` parsing).

## File layout

```
chiron-data-validator/
  chiron_validator.py       entry point: `python chiron_validator.py [validate] [options]`
  chironval/
    client.py               ChironClient: login + the 4 read endpoints, graceful per-concept error handling
    checks.py                the 4 pure check functions + documented heuristics
    runner.py                orchestrates client -> checks per dataset
    report.py                console + JSON report rendering
    cli.py                    argparse wiring
    models.py                 Issue / SkippedConcept / DatasetRunResult dataclasses
  tests/
    test_checks.py            unit tests for the 4 checks, synthetic payloads with known issues
    test_runner_helpers.py     unit tests for small runner helpers
  requirements.txt
  README.md
```
