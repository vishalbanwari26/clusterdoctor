import random

from clusterdoctor.store import Store, Request
from clusterdoctor.watcher import detect_latency_incident, percentile


def fill(store, t0, n, base_latency, spread=0.2, version="v1", tokens=500):
    rng = random.Random(1)
    for i in range(n):
        store.add_request(Request(
            ts=t0 + i, app_version=version, model="m", input_tokens=tokens, output_tokens=100,
            latency_s=base_latency + rng.uniform(-spread, spread), ttft_s=0.3, status=200,
            source="simulated"))


def test_percentile():
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3


def test_healthy_period_raises_no_incident():
    s = Store(":memory:")
    fill(s, 0, 300, 2.0)
    assert detect_latency_incident(s, (0, 100), 100, 300) is None


def test_latency_jump_opens_incident():
    s = Store(":memory:")
    fill(s, 0, 100, 2.0)
    fill(s, 100, 200, 8.0, version="v2", tokens=3000)
    inc = detect_latency_incident(s, (0, 100), 100, 300)
    assert inc is not None
    assert inc.observed_value > 6 and inc.baseline_value < 3


def test_single_spike_is_ignored():
    s = Store(":memory:")
    fill(s, 0, 100, 2.0)
    fill(s, 100, 30, 8.0)   # one window only
    fill(s, 130, 170, 2.0)
    assert detect_latency_incident(s, (0, 100), 100, 300) is None
