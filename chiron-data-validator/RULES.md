# Validation Rules Reference

Every rule below is implemented as a pure function in [chironval/checks.py](chironval/checks.py)
— no rule makes network calls; each one takes a concept's metadata + statistics (already fetched
from Chiron's API) and returns zero or more issues. All four rules run for every concept, on
every dataset, every time you run the tool (there's no way to disable an individual rule yet —
only `--missing-threshold` is tunable).

## Quick reference

| # | Rule | Issue kind(s) | Severity | Applies to |
|---|---|---|---|---|
| 1 | Missing/null rate | `high_missingness` | medium | every concept |
| 2 | Numeric outliers | `numeric_outlier` (histogram) / `possible_skewed_distribution` (fallback) | medium / low | `number`, `age`, `date`, `number_with_categories` |
| 3a | Label consistency | `label_inconsistency` | **high** | `category`, `boolean`, `number_with_categories`, `text` |
| 3b | Rare/singleton value | `possible_typo_or_rare_value` | low | `category`, `boolean`, `number_with_categories` (not `text` — see below) |
| 4 | Type plausibility | `possible_metadata_mismatch` | low | `category` only |

---

## Rule 1 — Missing / null rate → `high_missingness`

**Triggers when:**
```
count_missing_values / total_subjects  >  --missing-threshold   (default 0.30, i.e. 30%)
```
`count_missing_values` and `total_subjects` both come straight from the API response — nothing
is computed from raw rows.

**Why the ratio can exceed 100%:** the numerator counts missing *values* (rows/records), the
denominator counts *subjects*. A concept with multiple records per subject (e.g. "reason for
visit" across several encounters) can rack up more missing values than there are subjects,
producing rates like 633%. That's expected, not a bug — it just means "a lot of individual
records are missing this," not "most subjects are missing this." The API's
`count_subjects_with_missing_values` (the subject-normalized alternative) is included in the
issue's `details` for the JSON/HTML report as context.

**The one caveat that matters most:** Chiron's ETL layer casts every incoming value to its
declared type and **silently nulls anything that fails that cast, before storing it.** So this
rule cannot tell "genuinely absent in the source" apart from "arrived malformed and got quietly
nulled." Treat a `high_missingness` flag as *"go look at this concept,"* not *"here's what was
wrong with it."*

**Configurable:** `--missing-threshold 0.15` (etc.)

---

## Rule 2 — Numeric outliers → `numeric_outlier` / `possible_skewed_distribution`

This rule only looks at the two extreme ends of a concept's value distribution (the lowest bin
and the highest bin) — it says nothing about gaps or clusters in the middle.

**Primary path (histogram-based), used when `histogram_data` has ≥2 bins:**
For the first bin (global minimum) and the last bin (global maximum) independently, flag
`numeric_outlier` when **all three** are true:
1. That extreme bin actually has values in it (count > 0).
2. Walking inward from that bin, there's at least one **empty** bin before the next populated
   one — i.e. the extreme value(s) sit in a real gap, isolated from the bulk of the data.
3. `extreme_bin_count ≤ 0.10 × nearest_populated_neighbor_count` — the isolated bin holds at
   most 10% as many values as the bin it's separated from.

**Fallback path**, used only when there's no usable histogram (very few data points, or a
concept type whose statistics don't include one): flags `possible_skewed_distribution`
(weaker signal, severity `low`) when
```
abs((max - avg) - (avg - min)) / (max - min)  >  0.80
```
i.e. the mean sits far closer to one bound than the other. Only runs for concept types with a
plain numeric `avg` (`number`, `number_with_categories`) — `age` and `date` statistics don't
have a directly comparable average and are deliberately left alone here.

**Known, systematic false-positive class (documented in the code, not just here):** an isolated
extreme bin is exactly what a real, small, clinically-valid subpopulation looks like too — e.g.
a handful of extremely-preterm births at the low edge of a gestational-age histogram. This rule
cannot distinguish "data error" from "genuine rare extreme" using bin counts alone. Read
`numeric_outlier` as *"worth a human look,"* never as *"wrong."*

**Not configurable from the CLI** — the 10% isolation ratio and 80% skew ratio are constants in
the code (`ISOLATION_RATIO`, `SKEW_RATIO` in checks.py) if you need to tune them.

---

## Rule 3a — Label consistency → `label_inconsistency` (severity: **high**, the only high-severity rule)

**Triggers when:** two or more *distinct raw* values, after normalizing (lowercase, trim,
collapse internal whitespace to a single space), collapse to the same normalized string.

Example: raw values `"Male"`, `"male"`, `" male"` all normalize to `"male"` → one
`label_inconsistency` issue naming all three raw variants and their combined record count.
This is the strongest signal the tool produces, because it's close to unambiguous: these are
almost certainly the same real-world value, entered inconsistently (different casing, stray
whitespace, etc.) — not three legitimately different categories.

Applies to both statistics shapes the API returns:
- **category/boolean/number_with_categories** (`values` = list of `{category, count, ...}`)
- **text** (`values` = flat list of distinct strings, no counts) — same collision check, just
  without the count information.

**Robustness note:** some concept types the tool has never seen in practice (ontology,
multi-value fields) can return list-shaped values inside the `values` array instead of plain
strings. Those specific entries are skipped rather than crashing the whole check — this was a
real bug found during review and fixed; see [HOW_IT_WORKS.md](HOW_IT_WORKS.md) if you want the
history.

## Rule 3b — Rare/singleton value → `possible_typo_or_rare_value` (severity: low)

**Triggers when:** a category's `count == 1` — i.e. exactly one record anywhere in the dataset
has that value.

Only available where the API gives per-value counts (category/boolean/number_with_categories) —
`text` concepts carry no counts at all, so this half of Rule 3 simply doesn't run for them.

This is a much weaker signal than 3a: a true one-off value is completely normal in real data
(rare diagnoses, one-off provider names, etc.). It's flagged at low severity specifically so it
reads as "worth a glance if you're already looking at this concept," not "action required."

---

## Rule 4 — Type plausibility → `possible_metadata_mismatch` (severity: low, `category` concepts only)

**Question this rule is trying to answer:** is this "category" concept actually a bounded set of
real categories, or is it free text that got mis-configured as a category type?

**Triggers when** the concept has unusually many distinct values —
```
distinct_values > 50                                              (absolute threshold)
   OR
distinct_values / total_subjects > 20%   (only once total_subjects ≥ 20)
```
**AND** those distinct values actually look like free text rather than a real vocabulary — measured
by `singleton_fraction`, the fraction of distinct values that each occur only once. If a real
majority (≥50%) of distinct values recur more than once, this rule does **not** fire, no matter
how many distinct values there are.

This second condition exists specifically so that legitimate high-cardinality controlled
vocabularies — ICD-10 diagnosis codes, medication names, site codes, all common and completely
valid in clinical data — don't get flagged just for having many distinct values. The tell for
*actual* free text is that almost every distinct value is unique (each patient's response
differs slightly), not the raw count of distinct values on its own. (This distinction was added
after a review caught the earlier version flagging legitimate coded vocabularies — see
HOW_IT_WORKS.md.)

**Not configurable from the CLI** — thresholds are `CATEGORY_DISTINCT_ABS_THRESHOLD` (50),
`CATEGORY_DISTINCT_PCT_THRESHOLD` (0.20), `CATEGORY_PCT_MIN_SUBJECTS` (20), and
`CATEGORY_SINGLETON_FRACTION_THRESHOLD` (0.5) in checks.py.

---

## What's explicitly *not* checked (yet)

- **Cross-field / row-level consistency** (e.g. "admission date ≤ discharge date") — needs raw
  row access via Chiron's stateful `table_def`/`query_tools` flow, deliberately not built in v1.
  See HOW_IT_WORKS.md §4 for the reasoning and a recommended approach.
- **The actual malformed source values that Chiron already caught and nulled at ETL time**
  (`ConceptIssueEtlLog`) — not reachable through any current Chiron API endpoint, so no rule here
  can see them directly. Rule 1 (`high_missingness`) is the closest proxy available.
- Any rule that needs a true declared range, unit, or allowed-value list per concept — Chiron's
  data dictionary doesn't expose one via the API (only the coarse `concept_type`), so there's
  nothing to validate against beyond what's inferred from the observed statistics.
