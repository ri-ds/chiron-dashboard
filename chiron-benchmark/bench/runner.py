"""Benchmark runner — measure scenarios + flows, evaluate controls."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import controls as controls_mod
from . import scenarios as scen_mod
from .driver import LoadClient
from .stats import Sample, summarize


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BenchmarkRunner:
    def __init__(self, base_url, username, password, iterations=30,
                 burst_total=60, concurrency=8, flow_reps=15, verbose=False):
        self.client = LoadClient(base_url, username, password)
        self.iterations = iterations
        self.burst_total = burst_total
        self.concurrency = concurrency
        self.flow_reps = flow_reps
        self.verbose = verbose

    def run(self) -> dict:
        started = _now()
        t0 = time.perf_counter()
        if not self.client.login():
            raise RuntimeError("login failed — check credentials / server")
        ctx = scen_mod.discover(self.client)
        scenarios = scen_mod.build(ctx)
        flows = scen_mod.flows(ctx)
        controls = controls_mod.generate(scenarios, flows)

        scenario_results = {}
        for s in scenarios:
            stats = self.client.latency(s.method, s.path, self.iterations, params=s.params or None)
            # corrected error rate: a response matching expected_status is NOT an error
            bad = sum(cnt for st, cnt in stats.statuses.items() if int(st) != s.expected_status)
            corrected_err = round(bad / stats.n, 4) if stats.n else 1.0
            tput = None
            if s.throughput:
                tput = self.client.throughput(s.method, s.path, self.burst_total,
                                               self.concurrency, params=s.params or None)
            scenario_results[s.id] = {
                "scenario": s.__dict__, "latency": stats.as_dict(),
                "corrected_error_rate": corrected_err,
                "throughput": (tput.as_dict() if tput else None),
            }
            if self.verbose:
                print(f"  {s.id:18} p95={stats.p95:8.1f}ms p99={stats.p99:8.1f}ms "
                      f"err={corrected_err:.2f} " + (f"rps={tput.throughput_rps}" if tput else ""))

        flow_results = {}
        for fl in flows:
            totals = []
            for _ in range(self.flow_reps):
                tf = time.perf_counter()
                for step in fl["steps"]:
                    self.client.one("GET", step)
                totals.append(Sample(ok=True, status=200, ms=(time.perf_counter() - tf) * 1000))
            st = summarize(totals)
            flow_results[fl["id"]] = {"flow": fl, "total_ms": st.as_dict()}
            if self.verbose:
                print(f"  FLOW {fl['id']:18} p95={st.p95:8.1f}ms")

        # evaluate controls
        control_results = []
        for ct in controls:
            value = self._metric_value(ct, scenario_results, flow_results)
            ev = controls_mod.evaluate(ct, value)
            control_results.append({"control": ct.__dict__, **ev})

        wall = round(time.perf_counter() - t0, 2)
        n_pass = sum(1 for c in control_results if c["pass"] is True)
        n_fail = sum(1 for c in control_results if c["pass"] is False)
        n_na = sum(1 for c in control_results if c["pass"] is None)
        return {
            "started": started, "finished": _now(), "wall_s": wall,
            "base_url": self.client.base_url, "dataset": ctx.get("dataset"),
            "config": {"iterations": self.iterations, "burst_total": self.burst_total,
                       "concurrency": self.concurrency, "flow_reps": self.flow_reps},
            "discovery": ctx,
            "n_controls": len(control_results), "n_pass": n_pass, "n_fail": n_fail, "n_na": n_na,
            "scenarios": scenario_results, "flows": flow_results, "controls": control_results,
        }

    @staticmethod
    def _metric_value(ct, scen, flows):
        if ct.kind == "ui_flow":
            fr = flows.get(ct.ref)
            return fr["total_ms"].get(ct.metric) if fr else None
        sr = scen.get(ct.ref)
        if not sr:
            return None
        if ct.kind == "api_error":
            return sr["corrected_error_rate"]
        if ct.kind == "api_throughput":
            return sr["throughput"][ct.metric] if sr.get("throughput") else None
        return sr["latency"].get(ct.metric)
