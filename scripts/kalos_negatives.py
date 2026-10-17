"""Test 3 data: find ~16 more real utilization collapses with NO Xid change nearby, in a 50 MB slice starting 2023-08-24 (dense data),
and fetch their +-20 min windows. Hard cap 280 MB in total, counted across the slice reads and the window fetches.
Writes data/real/job_end_cases.json (the 16 existing N windows plus the new ones), derived subset of AcmeTrace (CC-BY-4.0)."""
import datetime as dt
import json
import random
import sys
import urllib.request
from array import array
from collections import defaultdict

sys.path.insert(0, "scripts")
import kalos_fetch_windows as W
import kalos_probe as K

CAP_TOTAL = 280 * 1024 * 1024
SLICE = 50 * 1024 * 1024
STREAM = [0]
T0 = dt.datetime.fromisoformat("2023-08-24 00:00:00+08:00")
W.CAP = 180 * 1024 * 1024                         # windows + probes; the two slices use at most 2 x 50 MB


def slice_rows(name, off):
    """Rows from a bounded range read of SLICE bytes starting at `off` (first partial line dropped)."""
    ncol = len(W.HDR[name]); req = urllib.request.Request(K.BASE + name + ".csv", headers={"Range": f"bytes={off}-{off + SLICE}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        if r.status != 206: raise SystemExit("range ignored")
        first = True
        for line in r:
            STREAM[0] += len(line)
            if first: first = False; continue
            f = line.decode("utf-8", "replace").rstrip("\n").split(",")
            if len(f) == ncol and K.TS.match(f[0]): yield f


def main():
    ex = json.load(open("data/real/hidden_xid_cases.json"))
    existing = [c for c in ex["cases"] if c["kind"] == "N_collapse"]
    ex_times = [c["time"] for c in existing]
    off_u, off_x = W.find_offset("GPU_UTIL", T0), W.find_offset("XID_ERRORS", T0)
    print(f"offsets found; probes so far {W.TALLY[0]/1e6:.1f} MB", flush=True)
    t0 = T0.timestamp(); mins = {}; hdr = W.HDR["GPU_UTIL"]; cur = -1; sums = cnts = None
    def flush(b):
        for j in range(1, len(hdr)):
            if cnts[j]: mins[hdr[j]][b] = min(254, int(sums[j] / cnts[j] + .5))
    nb = int(SLICE / 11000 * 15 / 60) + 40
    mins = {c: array("B", [255]) * nb for c in hdr[1:]}
    for f in slice_rows("GPU_UTIL", off_u):
        b = int((K.to_time(f[0]).timestamp() - t0) // 60)
        if b < 0 or b >= nb: continue
        if b != cur:
            if cur >= 0: flush(cur)
            sums = [0.0] * len(hdr); cnts = [0] * len(hdr); cur = b
        for j in range(1, len(hdr)):
            if f[j]: sums[j] += float(f[j]); cnts[j] += 1
    flush(cur); last_block = cur
    xh = W.HDR["XID_ERRORS"]; prev = [-1] * len(xh); xid_blocks = defaultdict(list)
    for f in slice_rows("XID_ERRORS", off_x):
        b = int((K.to_time(f[0]).timestamp() - t0) // 60)
        for j in range(1, len(xh)):
            if f[j] == "": continue
            x = int(float(f[j]))
            if prev[j] != -1 and x != prev[j] and x > 0: xid_blocks[xh[j]].append(b)
            prev[j] = x
    print(f"slice read {STREAM[0]/1e6:.0f} MB, util blocks 0..{last_block}, Xid changes in slice: {sum(len(v) for v in xid_blocks.values())}", flush=True)
    def mean(a, lo, hi):
        v = [a[i] for i in range(max(0, lo), min(len(a), hi)) if a[i] != 255]
        return (sum(v) / len(v), len(v)) if v else (None, 0)
    cands = []
    for g, a in mins.items():
        i = 22
        while i < last_block - 25:
            if a[i] != 255:
                pm, pn = mean(a, i - 20, i); qm, qn = mean(a, i, i + 2)
                if pn >= 15 and pm >= 80 and qn == 2 and qm < 32:
                    if not any(abs(x - i) <= 30 for x in xid_blocks.get(g, [])):
                        tt = t0 + i * 60
                        if all(abs(tt - e) > 3600 for e in ex_times): cands.append({"gpu": g, "node": g.rsplit("-", 1)[0], "time": tt})
                    i += 60; continue
            i += 1
    print(f"candidate job-end collapses without Xid: {len(cands)}", flush=True)
    rng = random.Random(11); rng.shuffle(cands); chosen = []; seen = set()
    for c in cands:
        key = (c["node"], int(c["time"] // 10800))
        if key in seen: continue
        seen.add(key); chosen.append(c)
        if len(chosen) == 16: break
    new = []
    for i, e in enumerate(chosen):
        if STREAM[0] + W.TALLY[0] > CAP_TOTAL - 8_000_000: print("STOP: nearing the 280 MB cap"); break
        anchor = dt.datetime.fromtimestamp(e["time"], dt.timezone(dt.timedelta(hours=8)))
        ts_, te_ = anchor - dt.timedelta(minutes=20), anchor + dt.timedelta(minutes=20)
        node = e["node"]; cols = [f"{node}-{k}" for k in range(8)]; case = {"id": f"n{i:02d}", "kind": "N_collapse", "gpu": e["gpu"], "node": node,
                                                                              "time": e["time"], "gpu_index": int(e["gpu"].rsplit("-", 1)[1]), "xid_code": None, "metrics": {}}
        for name, key in W.FILES.items():
            rows = W.fetch_window(name, ts_, te_); idx = {c: W.HDR[name].index(c) for c in cols}
            case["metrics"][key] = {"t": [int(K.to_time(r[0]).timestamp()) for r in rows],
                                    "v": {c.rsplit("-", 1)[1]: [float(r[idx[c]]) if r[idx[c]] != "" else None for r in rows] for c in cols}}
        new.append(case); print(f"{case['id']} {e['gpu']} fetched, total {(STREAM[0] + W.TALLY[0])/1e6:.0f} MB", flush=True)
    for c in existing: c["id"] = "e" + c["id"][1:]
    json.dump({"attribution": ex["attribution"], "step_s": 15, "cases": existing + new}, open("data/real/job_end_cases.json", "w"), separators=(",", ":"))
    print(f"[done] {len(existing)} existing + {len(new)} new windows | network total {(STREAM[0] + W.TALLY[0])/1e6:.0f} MB (cap 280)")


main()
