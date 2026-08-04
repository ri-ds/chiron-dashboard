# Chiron Performance Report

_Automated benchmark of the live Chiron API + key UI flows, driven by synthetic clinical data. Readable at a glance: green = meets target, red = misses target._

## Headline

**58 of 60 controls passing (97%)**  ` ███████████████████████░ `

| | |
|---|---|
| Run | 2026-07-21T18:33:21+00:00 → 2026-07-21T18:34:07+00:00 (45.33s) |
| Target | `http://127.0.0.1:8000` · dataset `dataset1_stored` |
| Controls | 60 total — ✅ 58 pass · ❌ 2 fail · ⚪ 0 not-measured |
| Load | 30 samples/endpoint · burst 60@8 · 15 flow reps |

## Controls — pass/fail by area

### API latency — 34/34 passing

| | Control | Measured | Target |
|---|---------|----------|--------|
| ✅ | Auth / whoami: 95th-percentile response under 300 ms | 2.71 ms | <= 300 ms |
| ✅ | Auth / whoami: 99th-percentile response under 600 ms | 3.33 ms | <= 600 ms |
| ✅ | Concept category tree: 95th-percentile response under 300 ms | 15.3 ms | <= 300 ms |
| ✅ | Concept category tree: 99th-percentile response under 600 ms | 15.92 ms | <= 600 ms |
| ✅ | Category detail: 95th-percentile response under 300 ms | 22.27 ms | <= 300 ms |
| ✅ | Category detail: 99th-percentile response under 600 ms | 22.3 ms | <= 600 ms |
| ✅ | Load active cohort def: 95th-percentile response under 900 ms | 2.85 ms | <= 900 ms |
| ✅ | Load active cohort def: 99th-percentile response under 1800 ms | 3.13 ms | <= 1800 ms |
| ✅ | List collections: 95th-percentile response under 300 ms | 7.84 ms | <= 300 ms |
| ✅ | List collections: 99th-percentile response under 600 ms | 8.47 ms | <= 600 ms |
| ✅ | Concept detail: 95th-percentile response under 900 ms | 4.54 ms | <= 900 ms |
| ✅ | Concept detail: 99th-percentile response under 1800 ms | 4.87 ms | <= 1800 ms |
| ✅ | Concept search: 95th-percentile response under 900 ms | 108.1 ms | <= 900 ms |
| ✅ | Concept search: 99th-percentile response under 1800 ms | 117.64 ms | <= 1800 ms |
| ✅ | Concept detail + statistics: 95th-percentile response under 2500 ms | 143.76 ms | <= 2500 ms |
| ✅ | Concept detail + statistics: 99th-percentile response under 5000 ms | 146.15 ms | <= 5000 ms |
| ✅ | List concepts (max page 1000): 95th-percentile response under 900 ms | 164.3 ms | <= 900 ms |
| ✅ | List concepts (max page 1000): 99th-percentile response under 1800 ms | 177.01 ms | <= 1800 ms |
| ✅ | List concepts (page 1): 95th-percentile response under 900 ms | 168.57 ms | <= 900 ms |
| ✅ | List concepts (page 1): 99th-percentile response under 1800 ms | 172.63 ms | <= 1800 ms |
| ✅ | List datasets: 95th-percentile response under 300 ms | 3.49 ms | <= 300 ms |
| ✅ | List datasets: 99th-percentile response under 600 ms | 3.86 ms | <= 600 ms |
| ✅ | Query preview (rows): 95th-percentile response under 2500 ms | 14.19 ms | <= 2500 ms |
| ✅ | Query preview (rows): 99th-percentile response under 5000 ms | 71.04 ms | <= 5000 ms |
| ✅ | Query preview metadata: 95th-percentile response under 900 ms | 3.63 ms | <= 900 ms |
| ✅ | Query preview metadata: 99th-percentile response under 1800 ms | 3.79 ms | <= 1800 ms |
| ✅ | Report preview (warehouse): 95th-percentile response under 2500 ms | 50.08 ms | <= 2500 ms |
| ✅ | Report preview (warehouse): 99th-percentile response under 5000 ms | 50.2 ms | <= 5000 ms |
| ✅ | List reports (paginated): 95th-percentile response under 900 ms | 70.89 ms | <= 900 ms |
| ✅ | List reports (paginated): 99th-percentile response under 1800 ms | 70.97 ms | <= 1800 ms |
| ✅ | Load active table def: 95th-percentile response under 900 ms | 2.81 ms | <= 900 ms |
| ✅ | Load active table def: 99th-percentile response under 1800 ms | 3.49 ms | <= 1800 ms |
| ✅ | Viewable reports: 95th-percentile response under 900 ms | 10.42 ms | <= 900 ms |
| ✅ | Viewable reports: 99th-percentile response under 1800 ms | 10.48 ms | <= 1800 ms |

### API availability — 17/17 passing

| | Control | Measured | Target |
|---|---------|----------|--------|
| ✅ | Auth / whoami: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Concept category tree: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Category detail: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Load active cohort def: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | List collections: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Concept detail: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Concept search: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Concept detail + statistics: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | List concepts (max page 1000): zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | List concepts (page 1): zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | List datasets: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Query preview (rows): zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Query preview metadata: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Report preview (warehouse): zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | List reports (paginated): zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Load active table def: zero unexpected errors | 0 fraction | == 0 fraction |
| ✅ | Viewable reports: zero unexpected errors | 0 fraction | == 0 fraction |

### API throughput — 3/5 passing

| | Control | Measured | Target |
|---|---------|----------|--------|
| ❌ | List concepts (page 1): sustains ≥ 12 req/s under concurrency | 4.8 req/s | >= 12 req/s |
| ❌ | List reports (paginated): sustains ≥ 12 req/s under concurrency | 9.5 req/s | >= 12 req/s |
| ✅ | Auth / whoami: sustains ≥ 25 req/s under concurrency | 546 req/s | >= 25 req/s |
| ✅ | Concept category tree: sustains ≥ 25 req/s under concurrency | 48.6 req/s | >= 25 req/s |
| ✅ | List datasets: sustains ≥ 25 req/s under concurrency | 353.1 req/s | >= 25 req/s |

### UI flow — 4/4 passing

| | Control | Measured | Target |
|---|---------|----------|--------|
| ✅ | UI flow — App bootstrap (login landing): 95th-pct completes under 800 ms | 6.31 ms | <= 800 ms |
| ✅ | UI flow — Open a dataset (home + query builder): 95th-pct completes under 1800 ms | 219.13 ms | <= 1800 ms |
| ✅ | UI flow — Run a query preview: 95th-pct completes under 3000 ms | 20.59 ms | <= 3000 ms |
| ✅ | UI flow — Open the reports list: 95th-pct completes under 1500 ms | 160.27 ms | <= 1500 ms |

## What failed (and by how much)

- ❌ **List concepts (page 1): sustains ≥ 12 req/s under concurrency** — measured **4.8 req/s** (target >= 12). single-node dev server target.
- ❌ **List reports (paginated): sustains ≥ 12 req/s under concurrency** — measured **9.5 req/s** (target >= 12). single-node dev server target.

## Raw metrics (per endpoint)

| Endpoint | tier | p50 ms | p95 ms | p99 ms | mean | err% | rps | statuses |
|----------|------|--------|--------|--------|------|------|-----|----------|
| Auth / whoami | light | 2.06 | 2.71 | 3.33 | 2.11 | 0 | 546.0 | 200×30 |
| List datasets | light | 2.82 | 3.49 | 3.86 | 2.89 | 0 | 353.1 | 200×30 |
| Concept category tree | light | 14.26 | 15.3 | 15.92 | 14.35 | 0 | 48.6 | 200×30 |
| List collections | light | 6.91 | 7.84 | 8.47 | 6.95 | 0 | — | 200×30 |
| List concepts (page 1) | medium | 129.87 | 168.57 | 172.63 | 133.35 | 0 | 4.8 | 200×30 |
| List concepts (max page 1000) | medium | 128.17 | 164.3 | 177.01 | 132.25 | 0 | — | 200×30 |
| Concept detail | medium | 3.66 | 4.54 | 4.87 | 3.75 | 0 | — | 200×30 |
| Concept detail + statistics | heavy | 104 | 143.76 | 146.15 | 107.56 | 0 | — | 200×30 |
| Category detail | light | 21.16 | 22.27 | 22.3 | 21.18 | 0 | — | 200×30 |
| Concept search | medium | 63.85 | 108.1 | 117.64 | 67.02 | 0 | — | 200×30 |
| Load active cohort def | medium | 2.27 | 2.85 | 3.13 | 2.34 | 0 | — | 200×30 |
| Query preview (rows) | heavy | 12.34 | 14.19 | 71.04 | 14.5 | 0 | — | 200×30 |
| Query preview metadata | medium | 3.26 | 3.63 | 3.79 | 3.28 | 0 | — | 200×30 |
| Load active table def | medium | 2.29 | 2.81 | 3.49 | 2.37 | 0 | — | 400×30 |
| List reports (paginated) | medium | 68.88 | 70.89 | 70.97 | 68.89 | 0 | 9.5 | 200×30 |
| Viewable reports | medium | 9.48 | 10.42 | 10.48 | 9.62 | 0 | — | 200×30 |
| Report preview (warehouse) | heavy | 46.72 | 50.08 | 50.2 | 47.28 | 0 | — | 200×30 |

## Raw metrics (UI flows)

| Flow | steps | p50 ms | p95 ms | max ms |
|------|-------|--------|--------|--------|
| App bootstrap (login landing) | 2 | 5.02 | 6.31 | 6.31 |
| Open a dataset (home + query builder) | 3 | 150.6 | 219.13 | 219.13 |
| Run a query preview | 3 | 18.54 | 20.59 | 20.59 |
| Open the reports list | 2 | 78.21 | 160.27 | 160.27 |

_Full machine-readable data (every sample summary + control result) is in the accompanying `results/latest.json`._
