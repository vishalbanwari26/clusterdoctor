from clusterdoctor.fleet import detect_low_util
from clusterdoctor.gpu import generate, prometheus_text, THROTTLE, TEMP
from clusterdoctor.store import Store

DUR, ONSET = 900, 300   # 15 min run, fault at 5 min


def run(scenario):
    s = Store(":memory:")
    generate(s, scenario, t0=0, duration=DUR, onset=ONSET, seed=1)
    return s, detect_low_util(s, (0, ONSET), ONSET, DUR)


def test_healthy_fleet_no_incident():
    _, inc = run("healthy")
    assert inc == []


def test_thermal_throttle_flags_only_gpu0():
    _, inc = run("thermal_throttle")
    assert [(i.node, i.gpu) for i in inc] == [("node-a", 0)]
    assert inc[0].observed_util < inc[0].baseline_util * 0.6


def test_dataloader_bottleneck_flags_only_gpu0():
    _, inc = run("dataloader_bottleneck")
    assert [(i.node, i.gpu) for i in inc] == [("node-a", 0)]


def test_same_symptom_different_evidence():
    """Both look like 'low util' to the watcher; temperature/throttle tell them apart."""
    def mean(s, metric):
        r = s.db.execute("SELECT AVG(value) v FROM gpu_metrics WHERE gpu=0 AND metric=? AND ts>=700", (metric,))
        return r.fetchone()["v"]
    thermal, _ = run("thermal_throttle")
    loader, _ = run("dataloader_bottleneck")
    assert mean(thermal, TEMP) > 80 > mean(loader, TEMP)
    assert mean(thermal, THROTTLE) > 0 == mean(loader, THROTTLE)


def test_prometheus_text_is_labelled_simulated():
    s, _ = run("healthy")
    text = prometheus_text(s, at=100)
    assert 'DCGM_FI_DEV_GPU_UTIL{node="node-a",gpu="0",simulated="true"}' in text
