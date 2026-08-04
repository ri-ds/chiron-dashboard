# Chiron tools — how each one works & what its results mean

Plain-English guide to the five tools, and what each is showing right now (on the
local demo data). All of them talk to Chiron the normal way (over its API) and use
only synthetic data — never real patient data.

Quick mental model: **two of them check that Chiron is *built* right, two look for
*problems* in the code/data, and one measures *speed*.**

---

## 1. Chiron validator  ("is the API returning the right shapes?")

**What it checks:** every field the API sends back is the right *type* (a date looks
like a date, a number is a number, nothing that should be there is missing, no page
crashes).

**How it works:** it reads Chiron's own code to learn the expected shape of every
endpoint, saves those as rules, then calls the **live API** and compares every
response field-by-field against the rules.

**What the results show right now:**
- **63 of 65 endpoints pass** all their rules (about 97%).
- **2 fail** — both are the "export to CSV" endpoint for analyses (`analysis_tools/export_csv`),
  which **crashes with a 500 error** instead of returning data or a clean message when
  there's no active analysis. That's a real bug.
- **3 "unreached"** — they returned a normal "you need to set something up first" message
  (e.g. no active table selected), so there was nothing to type-check. Not failures.
- **40 skipped** — write/delete actions we don't fire off automatically for safety.

**One-liner:** the API is in good shape; there are 2 endpoints that genuinely crash.

---

## 2. Data quality  ("is the actual data clean?")

**What it checks:** the *data values* inside each concept — not the API shape. It looks
for lots of missing values, likely typos in categories, weird numeric outliers, and
fields that look mislabeled.

**How it works:** it logs into Chiron, pulls the statistics for **every concept**, and
runs four checks on each (missing-rate, outliers, label typos, category cardinality).

**What the results show right now:** **146 flags across 3 datasets**, on **165 concepts**
(71 flagged, 87 clean, 7 skipped). Broken down by rule:
- **97 "possible typo / rare value"** — a category value that appears exactly once (e.g. one
  provider named `"Bill Smith"`). On this tiny demo data almost everything appears once, so
  this is mostly noise here — it becomes useful on real, larger data.
- **49 "high missingness"** — a concept where a lot of values are empty. Important caveat: this
  can mean genuinely-missing *or* data that was dropped during import; Chiron's API can't tell
  the two apart, so it's a "worth a look," not a verdict.

Per dataset: dataset1 = 6 subjects / 69 concepts (27 flagged), dataset2 = 6 / 49 (11 flagged),
dataset3 = 4 / 47 (33 flagged).

**One-liner:** it's surfacing symptoms in the data to eyeball; the high count is because the
demo datasets are tiny.

---

## 3. Vulnerability scan  ("any security holes?")

**What it checks:** common security problems in the code and the running server — hardcoded
secrets, debug mode left on, script-injection (XSS) risks, risky settings, and out-of-date
dependencies.

**How it works:** every time you press Run it freshly scans the actual source files, checks the
dependency versions, and pokes the **live server** (are security headers set? does a bad URL leak
an error trace? does a protected page reject anonymous access?).

**What the results show right now:** **15 findings — 3 high, 6 medium, 6 low.** The high ones:
- a **hardcoded secret key** in the settings,
- **debug mode on** (leaks internal details in errors),
- a **script-injection (XSS) risk** where a concept description is rendered as raw HTML.

The rest are medium/low: empty allowed-hosts, older dependency versions, missing security headers.

**One-liner:** a handful of real, fixable security issues, three of them worth prioritizing.

---

## 4. Inefficiency scan  ("anything slow or wasteful?")

**What it checks:** performance and code-quality problems — repeated database queries in loops,
oversized default page sizes, dead/duplicated code, disabled caching, and heavy front-end imports.

**How it works:** every Run freshly analyzes the actual source code for these patterns and reports
where each one is (file + line).

**What the results show right now:** **49 findings — 31 medium, 18 low.** By type:
- **27 possible "N+1" queries** — a database call sitting inside a loop (fetching one row at a time
  instead of all at once); the biggest performance category.
- **8 commented-out/dead routes**, **5 full-lodash imports** (bloats the front-end bundle),
- **4 oversized page-size defaults**, **3 dead files**, **1 caching-disabled**, **1 duplicated model**.

**One-liner:** mostly "fetching data in loops" and some dead code to clean up — real, but low-risk.

---

## 5. Benchmark suite  ("how fast is it?")

**What it checks:** speed and reliability — how quickly the API responds (typical and worst-case),
how many requests per second it handles under load, error rates, and how fast the key UI screens load.

**How it works:** it hammers the live API and times the key user flows with synthetic data, then
grades every measurement against a target ("control") — pass or fail.

**What the results show right now:** **58 of 60 controls pass.** Response times and UI flows are all
well within target. The **2 fails** are throughput under load:
- **List concepts:** ~5 requests/sec (target ≥ 12),
- **List reports:** ~10 requests/sec (target ≥ 12).

Both are the same story — those two list pages get slow when many people hit them at once, which
lines up with the "N+1 queries" the inefficiency scan flagged.

**One-liner:** fast overall; two list endpoints are the throughput bottleneck to optimize.

---

## How they fit together
- **Validator + Data quality** = correctness (the API shape, and the data values).
- **Vulnerability + Inefficiency scans** = problems in the code (security, and performance/quality).
- **Benchmark** = actual measured speed.

Two of them even corroborate each other: the benchmark's slow "list concepts" endpoint is explained
by the inefficiency scan's N+1-query findings. Everything runs live and on-demand from the dashboard.
