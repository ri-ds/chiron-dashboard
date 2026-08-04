# Chiron — What I Did (meeting notes, plain English)

**In one sentence:** I was asked to build a tool that checks whether Chiron's API/data
is correct, then review Chiron, improve it, and measure its performance — and along
the way I wrapped everything in a shared web dashboard so anyone can run it.

**Two ground rules I kept the whole time:** everything ran **locally**, and only on
**synthetic (fake) patient data** — no real PHI was ever used or touched.

---

## Quick background (so the rest makes sense)
Chiron is two apps working together:
- a **backend API** (Django) that does the real work, and
- a **website UI** (React) that people click around in,
sitting on top of a **Postgres database** holding the (synthetic) research/patient data.

There are also **two separate "validators"** in play — worth clarifying up front because
the names are similar but they check *different things*:
- **API validator** (I built it) → "Is the API behaving correctly?" (right data types, no crashes)
- **Data-quality validator** (was already there from earlier) → "Is the data itself clean?" (missing values, typos, outliers)

---

## PART A — Build a validator for Chiron

### 1. Understand Chiron end to end
- I read both codebases completely and wrote up how it all works.
- Made a full inventory: **127 API endpoints** and **41 data types**, with the exact
  fields each returns.
- *Output:* `CHIRON_OVERVIEW.md`.

### 2. Run Chiron locally
- Installed and started the backend + the UI, logged in, and confirmed a real end-to-end
  flow works (pick a dataset → run a query → get data back). Screenshots captured.

### 3. Build the "database of type validations" (the validator)
- Built **`chiron-validator`**: it learns the expected shape/type of every field Chiron's
  API should return (straight from Chiron's own code), stores those as rules, then calls
  the **live API** and checks every response **field by field**.
- **Key result:** it found **5 endpoints that crash (HTTP 500)** on ordinary requests —
  real bugs, not guesses. Overall ~63 of 65 endpoints pass cleanly.
- *Output:* the tool + `VALIDATOR_REPORT.md`.

---

## PART B — Review, improve, and instrument Chiron

### 4. Find vulnerabilities (security)
- Did a full security review of both apps.
- **39 confirmed issues** (3 high, 11 medium, rest lower). The big ones:
  - a way to inject HTML/script through a concept description (**stored XSS**),
  - a **hardcoded secret key**, and **debug mode left on** (leaks internal info),
  - a few **"see data you shouldn't"** access gaps, and views that expose raw identifiers.
- *Output:* `VULNERABILITIES.md`.

### 5. Find inefficiencies (performance/quality)
- **25 issues** (5 high). The big ones:
  - repeated slow database queries (**N+1**),
  - a caching shortcut that accidentally **skipped a privacy safeguard** (served un-suppressed counts),
  - data exports that **load everything into memory**, and oversized default page sizes.
- *Output:* `INEFFICIENCIES.md`.

### 6. Prove Claude can actually improve it
- Fixed **3 of the crash bugs** on a separate branch, added **tests**, and showed
  **before/after** proof (validator failures dropped from **5 → 2**).
- Honest note: these were **correctness fixes**. A dedicated *speed-up* or a *brand-new
  feature* wasn't done yet — that's the one piece of this task still open.
- *Output:* `IMPROVEMENTS.md`.

### 7. Instrument Chiron for performance
- Built a **benchmark suite** covering both layers:
  - **API:** response speed (p50/p95/p99), throughput, error rate,
  - **UI:** timing of the key screens/flows.
- Driven by synthetic data. Produced a **report a non-engineer can read**, with
  **60 pass/fail "controls"** (the ask was ~50). **58 pass.** The 2 that fail are genuine
  slow spots — the concepts list and the reports list get slow under load.
- **Integration:** provided a CI check (runs on every code change) and set up a
  **nightly automated run**.
- *Output:* `BENCHMARKING.md` + `chiron-benchmark/`.

---

## The "learning" topics (Claude capabilities)
Explained for reference — and I actually used them:
- **Skills / plugins** = reusable, packaged abilities you can load on demand.
- **"Team of agents"** = several Claude workers running in parallel. I used this twice:
  once to inventory the whole codebase fast, and once to run the security + efficiency
  audit where separate agents **double-checked each finding** (that's how false alarms got filtered out).

---

## The exploration items
- **Can Claude run periodic tasks?** — **Yes, done.** Set up a nightly scheduled job that
  runs the validator + benchmark automatically and tracks results over time.
- **Log into the RDCRN site and pull logs?** — **Not done, on purpose.** I *can* drive a
  login form, but I **can't create a Google account** and I **shouldn't type real
  credentials into a live external system** — plus it needs authorization first. The plan:
  *you* create the account and hold the credentials; *I* build the automation around it so
  I never handle the password.

---

## The dashboard (the large follow-on we spent the most time on)
After the tasks above, we built a shared web app so the whole team can use all of this
without a terminal:
- **"Chiron Control" dashboard** — one page to **start/stop Chiron** and **run every tool**
  (validator, security scan, inefficiency scan, benchmark), watch them run, and read results.
- **Fix & polish round:** switched to **tabs** (one per tool), made it show **the real error
  when something fails**, and removed clutter (the name prompt, the history table).
- **Fixed a confusing bug:** every run looked like it "failed." It was actually mislabeling
  "the tool found issues" as "the run failed." Now it clearly separates **Finished vs Failed**,
  and shows passing results too — not just failures.
- **Made the scans real:** the security + inefficiency scans used to just show old saved
  results. I built **real scanner scripts** so they genuinely **re-scan the live code every
  click** (proved it by planting a fake vulnerability and watching it get caught, then removed it).
- **Fixed the login:** the demo password is `demo1234`; I'd changed it during early setup,
  which quietly broke the login buttons — restored it and repointed all the tools.
- **Added the pre-existing data-quality validator** as a new **"Data quality" tab** (kept my
  API validator separate). It checks the actual data: missing values, typos, outliers,
  mislabeled categories. On the demo data it flags **146 items across 3 datasets**, and the
  tab now shows a **per-dataset summary** plus **every concept** with a clean/flagged/skipped status.
- Briefly made the data-quality **rules editable from the dashboard**, then **removed that
  editor for now** at your request (kept the clear results view).

---

## Headline results (good things to lead with)
- Chiron is running locally; **two validators, two scanners, and a benchmark** all run
  **live from one shared dashboard**.
- Found **concrete bugs** (5 crashing endpoints) and **fixed 3 with before/after proof**.
- **39 security findings + 25 efficiency findings**, each with a location and a suggested fix.
- Performance measured with **60 controls (58 passing)** and a nightly monitor.
- All of it on **synthetic data, locally — zero real patient data**.

## Honest caveats (so you're not caught out)
- The dashboard's security/inefficiency **scanners are fast, rule-based** checks. The deeper
  **39/25 findings** came from a one-time, more thorough AI audit — different, complementary things.
- The data-quality tool fires **a lot of low-severity flags** on the demo data simply because
  the demo datasets are tiny (4–6 subjects); it gets more meaningful on real-sized data.
- "Prove Claude can improve it" was demonstrated via **bug fixes**, not a new feature or a speed optimization.
- **RDCRN** login/monitoring is not started (needs your account + authorization).

## Where everything lives (if someone wants to see it)
- **Write-ups:** `CHIRON_OVERVIEW.md`, `VALIDATOR_REPORT.md`, `VULNERABILITIES.md`,
  `INEFFICIENCIES.md`, `IMPROVEMENTS.md`, `BENCHMARKING.md`, `SUMMARY.md`,
  `CHIRON_REVIEW_LOG.md` (a running log of the whole effort).
- **Tools:** `chiron-validator/` (API types), `chiron-scanners/` (security + inefficiency),
  `chiron-benchmark/` (performance), `chiron-data-validator/` (data quality),
  `chiron-dashboard/` (the web app), `integration/` (CI + nightly job).
