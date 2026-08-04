"""Unit tests for the benchmark stats/percentile logic."""

from bench.stats import Sample, percentile, summarize


def test_percentile_nearest_rank():
    vals = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert percentile(vals, 50) == 50
    assert percentile(vals, 90) == 90
    assert percentile(vals, 100) == 100
    assert percentile(vals, 0) == 10


def test_percentile_empty():
    import math
    assert math.isnan(percentile([], 95))


def test_summarize_basic():
    samples = [Sample(ok=True, status=200, ms=float(x)) for x in range(1, 101)]
    st = summarize(samples, wall_s=1.0)
    assert st.n == 100
    assert st.n_error == 0
    assert st.error_rate == 0.0
    assert st.p50 == 50
    assert st.p95 == 95
    assert st.p99 == 99
    assert st.min == 1 and st.max == 100
    assert st.throughput_rps == 100.0


def test_summarize_errors_and_statuses():
    samples = ([Sample(ok=True, status=200, ms=5.0)] * 8 +
               [Sample(ok=False, status=500, ms=5.0)] * 2)
    st = summarize(samples)
    assert st.n == 10
    assert st.n_error == 2
    assert st.error_rate == 0.2
    assert st.statuses == {"200": 8, "500": 2}


def test_summarize_empty():
    st = summarize([])
    assert st.n == 0
