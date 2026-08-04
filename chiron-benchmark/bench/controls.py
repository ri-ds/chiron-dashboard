"""Performance controls — the ~50 pass/fail checks driven through the suite.

A *control* is one measurable assertion about the running system: a metric, a
comparator, and a threshold, plus a plain-language description a non-engineer can
read. Controls are generated from the scenarios/flows so the count scales with
what the system actually exposes (see BENCHMARKING.md for the realistic number
and the threshold rationale).
"""

from __future__ import annotations

from dataclasses import dataclass

from .scenarios import TIERS


@dataclass
class Control:
    id: str
    name: str            # plain-language, non-engineer readable
    category: str        # API latency | API throughput | API availability | UI flow
    kind: str            # api_latency | api_throughput | api_error | ui_flow | health
    ref: str             # scenario/flow id it measures
    metric: str          # p95 | p99 | error_rate | throughput_rps | total_ms
    comparator: str      # <= | == | >=
    threshold: float
    unit: str
    rationale: str = ""


def generate(scenarios, flows) -> list[Control]:
    controls: list[Control] = []
    # Throughput target (rps) by tier for the burst-tagged scenarios.
    tput_target = {"light": 25, "medium": 12, "heavy": 4}

    for s in scenarios:
        t = TIERS[s.tier]
        controls.append(Control(
            id=f"{s.id}__p95", name=f"{s.name}: 95th-percentile response under {t['p95']} ms",
            category="API latency", kind="api_latency", ref=s.id, metric="p95",
            comparator="<=", threshold=float(t["p95"]), unit="ms",
            rationale=f"{s.tier}-tier endpoint"))
        controls.append(Control(
            id=f"{s.id}__p99", name=f"{s.name}: 99th-percentile response under {t['p99']} ms",
            category="API latency", kind="api_latency", ref=s.id, metric="p99",
            comparator="<=", threshold=float(t["p99"]), unit="ms",
            rationale="tail latency guard"))
        controls.append(Control(
            id=f"{s.id}__err", name=f"{s.name}: zero unexpected errors",
            category="API availability", kind="api_error", ref=s.id, metric="error_rate",
            comparator="==", threshold=0.0, unit="fraction",
            rationale=f"expects HTTP {s.expected_status}"))
        if s.throughput:
            controls.append(Control(
                id=f"{s.id}__rps",
                name=f"{s.name}: sustains ≥ {tput_target[s.tier]} req/s under concurrency",
                category="API throughput", kind="api_throughput", ref=s.id, metric="throughput_rps",
                comparator=">=", threshold=float(tput_target[s.tier]), unit="req/s",
                rationale="single-node dev server target"))

    for fl in flows:
        controls.append(Control(
            id=f"{fl['id']}__total",
            name=f"UI flow — {fl['name']}: 95th-pct completes under {fl['threshold_ms']} ms",
            category="UI flow", kind="ui_flow", ref=fl["id"], metric="p95",
            comparator="<=", threshold=float(fl["threshold_ms"]), unit="ms",
            rationale="p95 of the summed backing API calls (API-bound portion of the interaction)"))

    return controls


def evaluate(control: Control, value: float) -> dict:
    if value is None:
        return {"pass": None, "value": None, "detail": "not measured"}
    ok = {
        "<=": value <= control.threshold,
        ">=": value >= control.threshold,
        "==": value == control.threshold,
    }[control.comparator]
    return {"pass": bool(ok), "value": value,
            "detail": f"{value:g} {control.unit} {control.comparator} {control.threshold:g}"}
