"""Fetch +-20 min windows (GPU_UTIL, GPU_TEMP, POWER_USAGE) for each selected event, with a hard byte cap.

Raw rows go to data/raw/acme_kalos_hidden/ (git-ignored). A small derived JSON (target GPU + 7 node peers, no Xid) goes to
data/real/hidden_xid_cases.json together with the ground truth, which comes from the real Xid series.
"""
import csv
import datetime as dt
import json
import sys
import io

sys.path.insert(0, "scripts")
import kalos_probe as K

CAP = 420 * 1024 * 1024
OUT = "data/raw/acme_kalos_hidden"
FILES = {"GPU_UTIL": "util", "GPU_TEMP": "temp", "POWER_USAGE": "power"}
HDR = {n: K.header(f"data/raw/acme_kalos_peek/{n}.64k.csv") for n in (*FILES, "XID_ERRORS")}
TALLY = [0]


def get(name, off, n):
    if TALLY[0] + n > CAP:
        raise SystemExit(f"STOP: window cap {CAP/1e6:.0f} MB reached ({TALLY[0]/1e6:.0f} MB)")
    raw = K.fetch(name, off, n); TALLY[0] += len(raw); return raw


def row_at(name, off):
    ncol = len(HDR[name])
    for n in (32768, 65536):
        raw = get(name, off, n); i = raw.find(b"\n")
        if i < 0: continue
        rest = raw[i + 1:]; j = rest.find(b"\n")
        if j < 0: continue
        f = rest[:j].decode("utf-8", "replace").split(",")
        if len(f) == ncol and K.TS.match(f[0]): return off + i + 1, f
    return None


def find_offset(name, target):
    lo = (20000, K.T0); hi = (K.SIZES[name] - 40000, K.T0 + dt.timedelta(hours=K.SPAN_H))
    for step in range(40):
        frac = (target - lo[1]).total_seconds() / max(1.0, (hi[1] - lo[1]).total_seconds())
        guess = int(lo[0] + (hi[0] - lo[0]) * min(0.98, max(0.02, frac)))
        if step % 3 == 2 or guess <= lo[0] + 1024 or guess >= hi[0] - 1024:   # interpolation stalled: plain bisection
            guess = (lo[0] + hi[0]) // 2
        r = row_at(name, guess)
        if r is None:
            if hi[0] - lo[0] < 70000: break
            continue
        t = K.to_time(r[1][0])
        if abs((t - target).total_seconds()) <= 45: return r[0]
        if t < target: lo = (r[0], t)
        else: hi = (r[0], t)
    raise SystemExit(f"{name}: no convergence near {target}")


def fetch_window(name, t_start, t_end):
    off = find_offset(name, t_start); ncol = len(HDR[name]); buf = b""; pos = off
    while True:
        buf += get(name, pos, 2 * 1024 * 1024); pos += 2 * 1024 * 1024
        lines = buf.split(b"\n")[:-1]
        if lines:
            last = lines[-1].decode("utf-8", "replace").split(",")
            if len(last) == ncol and K.TS.match(last[0]) and K.to_time(last[0]) >= t_end: break
    rows = []
    for l in lines:
        f = l.decode("utf-8", "replace").split(",")
        if len(f) == ncol and K.TS.match(f[0]) and K.to_time(f[0]) <= t_end: rows.append(f)
    return rows


def main():
    sel = json.load(open("data/raw/acme_kalos_scan/selection.json"))["events"]
    cases = []
    try:
        cases = json.load(open("data/real/hidden_xid_cases.json"))["cases"]      # resume
    except FileNotFoundError:
        pass
    done = {c["id"] for c in cases}
    for e in sel:
        if e["id"] in done:
            continue
        anchor = dt.datetime.fromtimestamp(e["time"], dt.timezone(dt.timedelta(hours=8)))
        t_start, t_end = anchor - dt.timedelta(minutes=20), anchor + dt.timedelta(minutes=20)
        node = e["node"]; cols = [f"{node}-{k}" for k in range(8)]; tgt = int(e["gpu"].rsplit("-", 1)[1])
        case = {k: e[k] for k in ("id", "kind", "gpu", "node", "time")}
        case.update({"gpu_index": tgt, "xid_code": e.get("xid_code"), "metrics": {}})
        for name, key in FILES.items():
            rows = fetch_window(name, t_start, t_end)
            idx = {c: HDR[name].index(c) for c in cols}
            t = [int(K.to_time(r[0]).timestamp()) for r in rows]
            vals = {c.rsplit("-", 1)[1]: [float(r[idx[c]]) if r[idx[c]] != "" else None for r in rows] for c in cols}
            case["metrics"][key] = {"t": t, "v": vals}
        cases.append(case)
        print(f"{e['id']} {e['kind']:10} {e['gpu']:18} rows={[len(case['metrics'][k]['t']) for k in FILES.values()]} total {TALLY[0]/1e6:.0f} MB", flush=True)
        json.dump({"attribution": json.load(open("data/real/kalos_events.json"))["attribution"], "step_s": 15, "cases": cases},
                  open("data/real/hidden_xid_cases.json", "w"), separators=(",", ":"))
    print(f"[done] {len(cases)} windows, network {TALLY[0]/1e6:.0f} MB", flush=True)


if __name__ == "__main__":
    main()
