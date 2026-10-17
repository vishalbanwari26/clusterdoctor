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


def test_gap_windows_do_not_trigger_and_missing_baseline_is_skipped():
    from clusterdoctor.fleet import detect_low_util
    from clusterdoctor.gpu import SCHEMA, UTIL
    s = Store(":memory:"); s.db.executescript(SCHEMA)
    rows = [(t, "n", 0, UTIL, 97.0, "real") for t in range(0, 600, 15)]            # healthy baseline
    rows += [(t, "n", 0, UTIL, 5.0, "real") for t in range(600, 660, 15)]          # one low window, then a gap
    rows += [(t, "n", 1, UTIL, 5.0, "real") for t in range(600, 900, 15)]          # GPU 1 has no baseline at all
    s.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows); s.db.commit()
    assert detect_low_util(s, (0, 600), 600, 900) == []                            # gap breaks the streak, no baseline = no call


def test_xid_change_is_an_event_but_sticky_value_is_not():
    from clusterdoctor.fleet import detect_xid_change
    from clusterdoctor.gpu import SCHEMA, XID
    s = Store(":memory:"); s.db.executescript(SCHEMA)
    rows = [(t, "n", 0, XID, 43.0, "real") for t in range(0, 300, 15)]             # sticky old code
    rows += [(t, "n", 1, XID, 0.0 if t < 150 else 94.0, "real") for t in range(0, 300, 15)]
    s.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows); s.db.commit()
    inc = detect_xid_change(s, 0, 300)
    assert [(i.gpu, i.code, i.previous, i.opened_at) for i in inc] == [(1, 94, 0, 150)]


def test_real_loader_and_watchers_on_committed_slices():
    from clusterdoctor.fleet import detect_low_util, detect_xid_change
    from clusterdoctor.real import load_event, load_slices
    ev = load_slices()["events"]["A"]
    s = Store(":memory:"); info = load_event(s, ev)
    xid = detect_xid_change(s, 0, info["duration"] + 1)
    assert [(i.gpu, i.code) for i in xid] == [(3, 94)] and abs(xid[0].opened_at - info["onset"]) < 16
    low = detect_low_util(s, (0, info["onset"] - 600), info["onset"] - 300, info["duration"])
    assert any(i.gpu == 3 for i in low)                                            # the real utilization collapse is caught


def test_hidden_xid_tools_cannot_leak_xid():
    from clusterdoctor.hidden import HIDDEN_SPECS, HiddenTools, LABELS
    from clusterdoctor.real import load_event, load_slices
    s = Store(":memory:"); info = load_event(s, load_slices()["events"]["A"])
    t = HiddenTools(s, info["node"], info["gpu"], (0, 6000), (6000, 9000))
    assert set(t.registry()) == {"compare_windows", "util_pattern", "peer_gpus"}      # no throttle_reasons, no xid_lookup
    names = {x["function"]["name"] for x in HIDDEN_SPECS}
    assert names == {"compare_windows", "util_pattern", "peer_gpus", "submit_diagnosis"}
    assert "driver_error_reported" in LABELS


def test_zscore_watcher_catches_weak_consistent_shifts_and_ignores_decoys():
    from clusterdoctor.fleet import detect_zscore
    from clusterdoctor.gpu import SCHEMA, TEMP, UTIL
    import random
    rng = random.Random(0); s = Store(":memory:"); s.db.executescript(SCHEMA); rows = []
    for t in range(0, 1800, 30):
        for g in range(3):
            u = 96 + rng.gauss(0, 2); tp = 62 + rng.gauss(0, 1.5)
            if g == 1 and t >= 900: tp += 8                                  # weak consistent temperature rise
            if g == 2 and 900 <= t < 945: u = 20                             # 45 s dip: a decoy
            rows += [(t, "n", g, UTIL, u, "sim"), (t, "n", g, TEMP, tp, "sim")]
    s.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows); s.db.commit()
    found = {(i.gpu, i.metric) for i in detect_zscore(s, (0, 800), 900, 1800)}
    assert found == {(1, "temp")}
