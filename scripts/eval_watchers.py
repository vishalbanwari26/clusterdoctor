"""Test 5a: watchers. Tune the z threshold on seeds 101-102, confirm unchanged on 103-104. Free (simulated, local).
Old watchers = util-drop + Xid (as in Test 2). New = old + z-score watcher (util drop and temperature rise)."""
import json
import sys

sys.path.insert(0, "src")
from clusterdoctor.fleet import detect_low_util, detect_xid_change, detect_zscore  # noqa: E402
from clusterdoctor.gpu import SCENARIOS, generate_fleet  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

LEVELS = {"easy": (1.0, 1.0, 0.0), "medium": (0.6, 1.5, 0.05), "hard": (0.35, 2.0, 0.15)}
ONSET, DUR = 7200, 12000
FAULTS = {("node-02", 5): "thermal_throttle", ("node-05", 1): "dataloader_bottleneck", ("node-07", 6): "gpu_hardware_fault",
          ("node-03", 2): "transient_dip", ("node-04", 7): "idle"}
REAL = {k for k, v in FAULTS.items() if SCENARIOS[v].root_cause != "none"}
THR = (3.0, 4.0, 5.0, 6.0, 8.0, 10.0)


def run(seed, level):
    st, nz, ms = LEVELS[level]
    store = Store(":memory:"); generate_fleet(store, FAULTS, duration=DUR, onset=ONSET, seed=seed, strength=st, noise=nz, missing=ms)
    old = {(i.node, i.gpu) for i in detect_low_util(store, (0, ONSET), ONSET, DUR)} | {(i.node, i.gpu) for i in detect_xid_change(store, 0, DUR + 1)}
    res = {"old": old}
    for z in THR:
        res[z] = old | {(i.node, i.gpu) for i in detect_zscore(store, (0, ONSET), ONSET, DUR, z_thr=z)}
    return res


def score(seeds):
    tot = {k: [0, 0, 0] for k in ("old", *THR)}          # detected, possible, false alerts
    per_level = {lv: {k: [0, 0, 0] for k in ("old", *THR)} for lv in LEVELS}
    for seed in seeds:
        for lv in LEVELS:
            r = run(seed, lv)
            for k, found in r.items():
                d, fa = len(found & REAL), len(found - REAL)
                for t in (tot[k], per_level[lv][k]): t[0] += d; t[1] += len(REAL); t[2] += fa
    return tot, per_level


def show(title, tot, per_level, keys):
    print(f"\n{title}")
    for k in keys:
        lv = "  ".join(f"{l}:{per_level[l][k][0]}/{per_level[l][k][1]}" for l in LEVELS)
        print(f"  {'old watchers' if k == 'old' else f'+ z-score z>={k}':18} detected {tot[k][0]}/{tot[k][1]} | false alerts {tot[k][2]} | {lv}")


tune_tot, tune_lv = score((101, 102))
show("TUNING seeds 101-102", tune_tot, tune_lv, ("old", *THR))
ok = [z for z in THR if tune_tot[z][2] == 0]
chosen = max(ok, key=lambda z: (tune_tot[z][0], z)) if ok else max(THR)
print(f"\nchosen threshold (largest detection with zero false alerts on tuning seeds; ties go to the larger z): z >= {chosen}")
hold_tot, hold_lv = score((103, 104))
show(f"HELD-OUT seeds 103-104, threshold fixed at z>={chosen}", hold_tot, hold_lv, ("old", chosen))
d, p, fa = hold_tot[chosen]
print(f"\nacceptance (held-out): detected >= 15/18 and false alerts <= 1 -> detected {d}/{p}, false alerts {fa}: {'MET' if d >= 15 and fa <= 1 else 'NOT MET'}")
json.dump({"chosen_z": chosen, "tuning": {str(k): v for k, v in tune_tot.items()}, "heldout": {str(k): v for k, v in hold_tot.items()}},
          open("bench/results_watchers.json", "w"), indent=1)
