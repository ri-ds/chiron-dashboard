"""Latency/throughput statistics for a batch of timed requests."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def percentile(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank percentile (p in [0,100]) over an already-sorted list."""
    if not sorted_vals:
        return float("nan")
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    k = math.ceil(p / 100.0 * len(sorted_vals)) - 1
    return sorted_vals[max(0, min(k, len(sorted_vals) - 1))]


@dataclass
class Sample:
    ok: bool
    status: int
    ms: float


@dataclass
class Stats:
    n: int = 0
    n_error: int = 0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    mean: float = 0.0
    min: float = 0.0
    max: float = 0.0
    error_rate: float = 0.0
    throughput_rps: float = 0.0          # concurrent-burst throughput
    wall_s: float = 0.0
    statuses: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def summarize(samples: list[Sample], wall_s: float = 0.0) -> Stats:
    if not samples:
        return Stats()
    lat = sorted(s.ms for s in samples)
    errors = sum(1 for s in samples if not s.ok)
    statuses: dict[str, int] = {}
    for s in samples:
        statuses[str(s.status)] = statuses.get(str(s.status), 0) + 1
    st = Stats(
        n=len(samples), n_error=errors,
        p50=round(percentile(lat, 50), 2),
        p95=round(percentile(lat, 95), 2),
        p99=round(percentile(lat, 99), 2),
        mean=round(sum(lat) / len(lat), 2),
        min=round(lat[0], 2), max=round(lat[-1], 2),
        error_rate=round(errors / len(samples), 4),
        wall_s=round(wall_s, 3),
        throughput_rps=round(len(samples) / wall_s, 1) if wall_s > 0 else 0.0,
        statuses=statuses,
    )
    return st
