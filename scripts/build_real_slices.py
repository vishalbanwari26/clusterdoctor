"""Turn the raw AcmeTrace Kalos event windows into a small derived JSON (target GPU + its 7 node peers).

Run: python3 -I scripts/build_real_slices.py     (reads data/raw/acme_kalos_events/, git-ignored)
Writes data/real/kalos_events.json, which is committed with the CC-BY attribution it carries.
"""
import csv
import datetime as dt
import json

RAW = "data/raw/acme_kalos_events"
OUT = "data/real/kalos_events.json"
METRICS = {"GPU_UTIL": "util", "GPU_TEMP": "temp", "POWER_USAGE": "power"}
info = json.load(open(f"{RAW}/events.json"))

out = {
    "attribution": {
        "dataset": "AcmeTrace (Kalos cluster utilization traces), Shanghai AI Laboratory",
        "url": "https://huggingface.co/datasets/Qinghao/AcmeTrace",
        "license": "CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/)",
        "paper": "Qinghao Hu et al. Characterization of Large Language Model Development in the Datacenter. NSDI '24. arXiv:2403.07648",
        "changes": "Subset of rows (3 h windows around two events) and columns (8 GPUs of one node), converted from CSV to JSON. "
                   "The Xid series of the target GPU is reconstructed from bisection of XID_ERRORS.csv: 0 before the first row showing code 94, 94 after.",
    },
    "step_s": 15,
    "events": {},
}
for ev, meta in info.items():
    gpu = meta["gpu"]; node = gpu.rsplit("-", 1)[0]
    cols = [f"{node}-{k}" for k in range(8)]
    e = {"node": node, "gpu": gpu, "gpu_index": int(gpu.rsplit("-", 1)[1]), "xid": meta["xid"],
         "event_epoch": dt.datetime.fromisoformat(meta["event_time"]).timestamp(), "metrics": {}}
    for fname, key in METRICS.items():
        with open(f"{RAW}/{fname}_{ev}.csv", newline="") as fh:
            rd = csv.reader(fh); hdr = next(rd)
            idx = {c: hdr.index(c) for c in cols}
            t, vals = [], {str(c.rsplit('-', 1)[1]): [] for c in cols}
            for r in rd:
                if len(r) != len(hdr):
                    continue
                t.append(int(dt.datetime.fromisoformat(r[0]).timestamp()))
                for c in cols:
                    v = r[idx[c]]
                    vals[c.rsplit("-", 1)[1]].append(float(v) if v != "" else None)
        e["metrics"][key] = {"t": t, "v": vals}
    out["events"][ev] = e
    print(ev, gpu, {k: len(m["t"]) for k, m in e["metrics"].items()})
json.dump(out, open(OUT, "w"), separators=(",", ":"))
import os
print("wrote", OUT, f"{os.path.getsize(OUT)/1024:.0f} KB")
