"""Benchmark scenarios — the key API flows, driven by synthetic data.

A scenario is one endpoint call with concrete params. Path placeholders
(`{dataset}`, `{concept}`, `{report}`) are filled by discovering real ids over
the public API first (same black-box approach as the validator). Each scenario
declares a latency *tier* that sets its pass/fail thresholds (see controls.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scenario:
    id: str
    name: str
    group: str                 # metadata | query | reports | analysis
    method: str
    path: str
    tier: str                  # light | medium | heavy
    params: dict = field(default_factory=dict)
    throughput: bool = False   # also run a concurrent burst
    expected_status: int = 200  # what a healthy call returns (some are 400 w/o state)
    note: str = ""


# Latency tiers → threshold ms for p95 / p99 (justified in BENCHMARKING.md).
TIERS = {
    "light":  {"p95": 300,  "p99": 600},    # cached/metadata reads
    "medium": {"p95": 900,  "p99": 1800},   # metadata joins / list building
    "heavy":  {"p95": 2500, "p99": 5000},   # warehouse queries (counts/previews/exports)
}


def discover(client) -> dict:
    """Harvest live ids so scenario paths resolve. client = LoadClient."""
    ctx = {}
    r = client.session.get(f"{client.base_url}/api/v2/dataset/", timeout=client.timeout)
    try:
        ds = r.json().get("datasets", [])
    except Exception:
        ds = []
    ctx["dataset"] = (ds[0]["name"] if ds else "dataset1_stored")
    d = ctx["dataset"]
    def _get(p):
        try:
            return client.session.get(f"{client.base_url}{p}", timeout=client.timeout).json()
        except Exception:
            return None
    cj = _get(f"/api/v2/{d}/concepts/")
    res = (cj or {}).get("results") if isinstance(cj, dict) else None
    ctx["concept"] = res[0]["permanent_id"] if res else None
    rj = _get(f"/api/v2/{d}/reports/")
    rres = (rj or {}).get("results") if isinstance(rj, dict) else None
    ctx["report"] = (rres[0]["id"] if rres else None)
    catj = _get(f"/api/v2/{d}/concept_categories/")
    cats = (catj or {}).get("categories") if isinstance(catj, dict) else None
    ctx["category"] = cats[0]["id"] if cats else None
    return ctx


def build(ctx: dict) -> list[Scenario]:
    d = ctx.get("dataset", "dataset1_stored")
    c = ctx.get("concept")
    rep = ctx.get("report")
    cat = ctx.get("category")
    S = []
    add = S.append
    # --- metadata / light reads ---
    add(Scenario("auth", "Auth / whoami", "metadata", "GET", "/api/v2/auth/", "light", throughput=True))
    add(Scenario("dataset_list", "List datasets", "metadata", "GET", "/api/v2/dataset/", "light", throughput=True))
    add(Scenario("categories", "Concept category tree", "metadata", "GET",
                 f"/api/v2/{d}/concept_categories/", "light", throughput=True))
    add(Scenario("collections", "List collections", "metadata", "GET",
                 f"/api/v2/{d}/collections/", "light"))
    add(Scenario("concepts_page", "List concepts (page 1)", "metadata", "GET",
                 f"/api/v2/{d}/concepts/", "medium", params={"page": 1, "page_size": 100}, throughput=True))
    add(Scenario("concepts_big", "List concepts (max page 1000)", "metadata", "GET",
                 f"/api/v2/{d}/concepts/", "medium", params={"page": 1, "page_size": 1000}))
    if c:
        add(Scenario("concept_detail", "Concept detail", "metadata", "GET",
                     f"/api/v2/{d}/concepts/{c}/", "medium"))
        add(Scenario("concept_stats", "Concept detail + statistics", "query", "GET",
                     f"/api/v2/{d}/concepts/{c}/", "heavy", params={"include_statistics": "true"},
                     note="triggers a warehouse stats query"))
    if cat is not None:
        add(Scenario("category_detail", "Category detail", "metadata", "GET",
                     f"/api/v2/{d}/concept_categories/{cat}/", "light"))
    add(Scenario("concept_search", "Concept search", "query", "GET",
                 f"/api/v2/{d}/concept_categories/concept_search/", "medium",
                 params={"search": "a", "concept_type": "cohort"}))
    # --- query engine / warehouse (heavy) ---
    add(Scenario("cohort_def", "Load active cohort def", "query", "GET",
                 f"/api/v2/{d}/cohort_def/", "medium"))
    add(Scenario("qt_preview", "Query preview (rows)", "query", "GET",
                 f"/api/v2/{d}/query_tools/preview/", "heavy", note="warehouse query"))
    add(Scenario("qt_preview_meta", "Query preview metadata", "query", "GET",
                 f"/api/v2/{d}/query_tools/preview_metadata/", "medium"))
    add(Scenario("table_def", "Load active table def", "query", "GET",
                 f"/api/v2/{d}/table_def/", "medium", expected_status=400,
                 note="400 'no active snapshot' when none set — measured as a reachability/latency path"))
    # --- reports ---
    add(Scenario("reports_list", "List reports (paginated)", "reports", "GET",
                 f"/api/v2/{d}/reports/", "medium", throughput=True))
    add(Scenario("viewable_reports", "Viewable reports", "reports", "GET",
                 f"/api/v2/{d}/reports/viewable_reports/", "medium"))
    if rep is not None:
        add(Scenario("report_preview", "Report preview (warehouse)", "reports", "GET",
                     f"/api/v2/{d}/report_tools/{rep}/preview/", "heavy", note="warehouse query"))
    return S


# UI flows: ordered sequences of API calls that back a key user interaction.
# Measured end-to-end (sum of the calls) as a proxy for the API-bound portion of
# perceived UI responsiveness. Real browser load times are captured separately
# (see BENCHMARKING.md). threshold_ms = target p95 for the whole flow.
def flows(ctx: dict) -> list[dict]:
    d = ctx.get("dataset", "dataset1_stored")
    c = ctx.get("concept")
    F = [
        {"id": "flow_bootstrap", "name": "App bootstrap (login landing)", "threshold_ms": 800,
         "steps": ["/api/v2/auth/", "/api/v2/dataset/"]},
        {"id": "flow_dataset_home", "name": "Open a dataset (home + query builder)", "threshold_ms": 1800,
         "steps": [f"/api/v2/{d}/concept_categories/", f"/api/v2/{d}/concepts/?page=1&page_size=100",
                   f"/api/v2/{d}/collections/"]},
        {"id": "flow_query_preview", "name": "Run a query preview", "threshold_ms": 3000,
         "steps": [f"/api/v2/{d}/cohort_def/", f"/api/v2/{d}/query_tools/preview_metadata/",
                   f"/api/v2/{d}/query_tools/preview/"]},
        {"id": "flow_reports", "name": "Open the reports list", "threshold_ms": 1500,
         "steps": [f"/api/v2/{d}/reports/", f"/api/v2/{d}/reports/viewable_reports/"]},
    ]
    return F

