"""Stream Kalos XID_ERRORS.csv and GPU_UTIL.csv once (nothing stored), and select real events for the hidden-Xid test.

Kinds:  P_collapse = Xid change with a utilization collapse at the same time
        P_silent   = Xid change with NO utilization collapse (like event B)
        N_collapse = utilization collapse with NO Xid change on that GPU within +-30 min (normal job ends)
Hard network cap enforced; resumes a dropped connection from the last complete line.
Output: data/raw/acme_kalos_scan/selection.json
"""
import datetime as dt
import json
import random
import sys
import time
import urllib.request
from array import array
from collections import defaultdict

BASE = "https://huggingface.co/datasets/Qinghao/AcmeTrace/resolve/main/data/utilization/kalos/"
CAP = int(1.9e9)
T0 = dt.datetime.fromisoformat("2023-08-15 15:30:15+08:00").timestamp()
TOTAL = [0]
T_START = time.time()
SPEED_DONE = [False]


def stream_lines(name):
    off = 0
    tries = 0
    while True:
        try:
            req = urllib.request.Request(BASE + name + ".csv", headers={"Range": f"bytes={off}-"} if off else {})
            with urllib.request.urlopen(req, timeout=60) as r:
                if off and r.status != 206:
                    raise SystemExit("server ignored the resume range")
                for line in r:
                    if not line.endswith(b"\n"):
                        raise ConnectionError("partial line at end of chunk")
                    off += len(line)
                    TOTAL[0] += len(line)
                    if TOTAL[0] > CAP:
                        raise SystemExit(f"STOP: network cap reached ({TOTAL[0]/1e9:.2f} GB)")
                    if not SPEED_DONE[0] and TOTAL[0] >= 100e6:
                        SPEED_DONE[0] = True
                        el = time.time() - T_START
                        print(f"[speed] first 100 MB in {el:.0f} s = {100/el:.1f} MB/s", flush=True)
                    yield line
                return
        except (ConnectionError, OSError) as e:
            tries += 1
            if tries > 6:
                raise SystemExit(f"STOP: too many connection failures ({e})")
            print(f"[retry {tries}] {type(e).__name__} at {off/1e6:.0f} MB, resuming", flush=True)
            time.sleep(3)


def epoch(s):                      # '2023-08-15 15:30:15+08:00'
    return dt.datetime.fromisoformat(s).timestamp()


def main():
    # ---------- scan 1: Xid change events ----------
    t0 = time.time(); events = []; prev = None; hdr = None; rows = 0
    for raw in stream_lines("XID_ERRORS"):
        f = raw.decode("utf-8", "replace").rstrip("\n").split(",")
        if hdr is None:
            hdr = f; prev = [-1] * len(f); continue
        if len(f) != len(hdr):
            continue
        rows += 1; t = None
        for j in range(1, len(f)):
            v = f[j]
            if v == "":
                continue
            x = int(float(v))
            if prev[j] != -1 and x != prev[j] and x > 0:
                if t is None: t = epoch(f[0])
                events.append((t, hdr[j], prev[j], x))
            prev[j] = x
        if rows % 20000 == 0:
            print(f"[xid] {rows} rows, {len(events)} change events, {TOTAL[0]/1e6:.0f} MB", flush=True)
    print(f"[xid] done: {rows} rows, {len(events)} change events in {time.time()-t0:.0f} s", flush=True)
    by_code = defaultdict(int)
    for e in events: by_code[e[3]] += 1
    print("[xid] events by new code:", dict(by_code), flush=True)

    # ---------- scan 2: per-GPU util minute means (uint8, 255 = missing) ----------
    t0 = time.time(); mins = {}; hdr2 = None; cur = -1; sums = None; cnts = None; ncol = 0; rows = 0
    def flush_block(b):
        for j in range(1, ncol):
            if cnts[j]:
                mins[hdr2[j]][b] = min(254, int(sums[j] / cnts[j] + 0.5))
    for raw in stream_lines("GPU_UTIL"):
        f = raw.decode("utf-8", "replace").rstrip("\n").split(",")
        if hdr2 is None:
            hdr2 = f; ncol = len(f)
            nblocks = int((16.5 * 86400) // 60) + 10
            mins = {c: array("B", [255]) * nblocks for c in hdr2[1:]}
            sums = [0.0] * ncol; cnts = [0] * ncol; continue
        if len(f) != ncol:
            continue
        rows += 1
        b = int((epoch(f[0]) - T0) // 60)
        if b != cur:
            if cur >= 0: flush_block(cur)
            sums = [0.0] * ncol; cnts = [0] * ncol; cur = b
        for j in range(1, ncol):
            v = f[j]
            if v: sums[j] += float(v); cnts[j] += 1
        if rows % 20000 == 0:
            print(f"[util] {rows} rows, {TOTAL[0]/1e6:.0f} MB, {time.time()-t0:.0f} s", flush=True)
    if cur >= 0: flush_block(cur)
    print(f"[util] done: {rows} rows in {time.time()-t0:.0f} s; total network {TOTAL[0]/1e9:.2f} GB", flush=True)

    # ---------- derive collapses ----------
    def mean(a, lo, hi):
        v = [a[i] for i in range(max(0, lo), min(len(a), hi)) if a[i] != 255]
        return (sum(v) / len(v), len(v)) if v else (None, 0)
    collapses = []                       # (block, gpu)
    for g, a in mins.items():
        i = 21
        while i < len(a) - 3:
            if a[i] != 255:
                pm, pn = mean(a, i - 20, i)
                qm, qn = mean(a, i, i + 2)
                if pn >= 15 and pm >= 80 and qn == 2 and qm < 32:
                    collapses.append((i, g)); i += 60; continue
            i += 1
    print(f"[derive] {len(collapses)} utilization collapses (prior 20 min >= 80%, next 2 min < 32%)", flush=True)

    def block(t): return int((t - T0) // 60)
    xid_by_gpu = defaultdict(list)
    for t, g, p, x in events: xid_by_gpu[g].append((block(t), x, p))
    col_by_gpu = defaultdict(list)
    for b, g in collapses: col_by_gpu[g].append(b)
    P_collapse, P_silent, N = [], [], []
    for t, g, p, x in events:
        b = block(t); a = mins.get(g)
        if a is None or b < 22 or b > len(a) - 25: continue
        pm, pn = mean(a, b - 20, b); qm, qn = mean(a, b, b + 5)
        if pn < 15 or pm < 80 or qn < 3: continue                     # need a clean, busy-before window with data after
        node = g.rsplit("-", 1)[0]
        ev = {"gpu": g, "node": node, "time": t, "xid_code": x, "xid_prev": p}
        if any(abs(c - b) <= 3 for c in col_by_gpu[g]): P_collapse.append({**ev, "kind": "P_collapse"})
        elif qm >= 80: P_silent.append({**ev, "kind": "P_silent"})
    for b, g in collapses:
        if any(abs(xb - b) <= 30 for xb, _, _ in xid_by_gpu[g]): continue
        N.append({"gpu": g, "node": g.rsplit("-", 1)[0], "time": T0 + b * 60, "kind": "N_collapse"})
    print(f"[derive] candidates: P_collapse={len(P_collapse)} P_silent={len(P_silent)} N_collapse={len(N)}", flush=True)

    rng = random.Random(7)
    def pick(lst, k):
        rng.shuffle(lst); out = []; seen = set()
        for e in lst:
            key = (e["node"], int(e["time"] // 21600))                  # at most one per node per 6 h
            if key in seen: continue
            seen.add(key); out.append(e)
            if len(out) == k: break
        return sorted(out, key=lambda e: e["time"])
    sel = pick(P_collapse, 8) + pick(P_silent, 8) + pick(N, 16)
    for i, e in enumerate(sel): e["id"] = f"w{i:02d}"
    json.dump({"events": sel, "candidates": {"P_collapse": len(P_collapse), "P_silent": len(P_silent), "N_collapse": len(N)},
               "xid_codes": dict(by_code), "network_gb": TOTAL[0] / 1e9},
              open("data/raw/acme_kalos_scan/selection.json", "w"), indent=1)
    print("[done] selected:", {k: sum(1 for e in sel if e["kind"] == k) for k in ("P_collapse", "P_silent", "N_collapse")},
          "| codes in positives:", sorted({e["xid_code"] for e in sel if "xid_code" in e}), flush=True)


main()
