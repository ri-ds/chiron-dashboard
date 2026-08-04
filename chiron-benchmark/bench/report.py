"""Render a benchmark run to a non-engineer-friendly Markdown report + JSON."""

from __future__ import annotations

import json
from pathlib import Path


def _bar(pct: float, width: int = 24) -> str:
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def build_markdown(run: dict) -> str:
    L = []
    A = L.append
    total = run["n_controls"]
    npass, nfail, nna = run["n_pass"], run["n_fail"], run["n_na"]
    measured = npass + nfail
    pct = (100.0 * npass / measured) if measured else 0.0

    A("# Chiron Performance Report\n")
    A("_Automated benchmark of the live Chiron API + key UI flows, driven by "
      "synthetic clinical data. Readable at a glance: green = meets target, "
      "red = misses target._\n")

    A("## Headline\n")
    A(f"**{npass} of {measured} controls passing ({pct:.0f}%)**  ` {_bar(pct)} `\n")
    A("| | |")
    A("|---|---|")
    A(f"| Run | {run['started']} → {run['finished']} ({run['wall_s']}s) |")
    A(f"| Target | `{run['base_url']}` · dataset `{run['dataset']}` |")
    A(f"| Controls | {total} total — ✅ {npass} pass · ❌ {nfail} fail · ⚪ {nna} not-measured |")
    cfg = run["config"]
    A(f"| Load | {cfg['iterations']} samples/endpoint · burst {cfg['burst_total']}@{cfg['concurrency']} "
      f"· {cfg['flow_reps']} flow reps |")
    A("")

    # ---- controls grouped by category (the skimmable table) ----
    cats: dict[str, list] = {}
    for c in run["controls"]:
        cats.setdefault(c["control"]["category"], []).append(c)
    A("## Controls — pass/fail by area\n")
    for cat, items in cats.items():
        p = sum(1 for c in items if c["pass"] is True)
        A(f"### {cat} — {p}/{len(items)} passing\n")
        A("| | Control | Measured | Target |")
        A("|---|---------|----------|--------|")
        for c in sorted(items, key=lambda c: (c["pass"] is not False, c["control"]["id"])):
            icon = "✅" if c["pass"] else ("❌" if c["pass"] is False else "⚪")
            ctl = c["control"]
            val = "—" if c["value"] is None else f"{c['value']:g} {ctl['unit']}"
            tgt = f"{ctl['comparator']} {ctl['threshold']:g} {ctl['unit']}"
            A(f"| {icon} | {ctl['name']} | {val} | {tgt} |")
        A("")

    # ---- failures called out ----
    fails = [c for c in run["controls"] if c["pass"] is False]
    if fails:
        A("## What failed (and by how much)\n")
        for c in fails:
            ctl = c["control"]
            A(f"- ❌ **{ctl['name']}** — measured **{c['value']:g} {ctl['unit']}** "
              f"(target {ctl['comparator']} {ctl['threshold']:g}). {ctl['rationale']}.")
        A("")

    # ---- raw metrics behind the controls ----
    A("## Raw metrics (per endpoint)\n")
    A("| Endpoint | tier | p50 ms | p95 ms | p99 ms | mean | err% | rps | statuses |")
    A("|----------|------|--------|--------|--------|------|------|-----|----------|")
    for sid, sr in run["scenarios"].items():
        s = sr["scenario"]; lat = sr["latency"]
        rps = sr["throughput"]["throughput_rps"] if sr.get("throughput") else "—"
        st = ",".join(f"{k}×{v}" for k, v in lat["statuses"].items())
        A(f"| {s['name']} | {s['tier']} | {lat['p50']:g} | {lat['p95']:g} | {lat['p99']:g} "
          f"| {lat['mean']:g} | {sr['corrected_error_rate']*100:g} | {rps} | {st} |")
    A("")
    A("## Raw metrics (UI flows)\n")
    A("| Flow | steps | p50 ms | p95 ms | max ms |")
    A("|------|-------|--------|--------|--------|")
    for fid, fr in run["flows"].items():
        f = fr["flow"]; t = fr["total_ms"]
        A(f"| {f['name']} | {len(f['steps'])} | {t['p50']:g} | {t['p95']:g} | {t['max']:g} |")
    A("")
    A("_Full machine-readable data (every sample summary + control result) is in "
      "the accompanying `results/latest.json`._\n")
    return "\n".join(L)


def write(run: dict, md_path, json_path):
    Path(md_path).write_text(build_markdown(run))
    Path(json_path).write_text(json.dumps(run, indent=2, default=str))
