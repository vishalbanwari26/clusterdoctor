"""Option 1: locate each Xid-94 event by bisection, then fetch 3 h windows (2 h before, 1 h after)
of GPU_UTIL, GPU_TEMP and POWER_USAGE. Hard cap on total bytes read in this run."""
import datetime as dt
import json
import sys

sys.path.insert(0, "scripts")
import kalos_probe as K

CAP = 60 * 1024 * 1024
OUT = "data/raw/acme_kalos_events"
TALLY = [0]
EVENTS = {  # name -> (gpu column, XID bracket (probe idx lo, hi))
    "A": ("172.31.15.203-3", (72, 73)),
    "B": ("172.31.0.68-6", (11, 13)),
}
FILES = ("GPU_UTIL", "GPU_TEMP", "POWER_USAGE")
HDR = {n: K.header(f"data/raw/acme_kalos_peek/{n}.64k.csv") for n in (*FILES, "XID_ERRORS")}


def get(name, off, n):
    if TALLY[0] + n > CAP:
        raise SystemExit(f"STOP: next read would exceed the {CAP/1e6:.0f} MB cap (read so far {TALLY[0]/1e6:.1f} MB)")
    raw = K.fetch(name, off, n)
    TALLY[0] += len(raw)
    return raw


def row_at(name, off):
    """First complete row after `off`: (row_start_byte, fields) or None."""
    ncol = len(HDR[name])
    for n in (32768, 65536):
        raw = get(name, off, n)
        i = raw.find(b"\n")
        if i < 0:
            continue
        rest = raw[i + 1:]
        j = rest.find(b"\n")
        if j < 0:
            continue
        f = rest[:j].decode("utf-8", "replace").split(",")
        if len(f) == ncol and K.TS.match(f[0]):
            return off + i + 1, f
    return None


def first_row_with(name, lo_off, hi_off, pred):
    raw = get(name, lo_off, hi_off - lo_off + 32768)
    pos = lo_off + raw.find(b"\n") + 1
    for line in raw[raw.find(b"\n") + 1:].split(b"\n")[:-1]:
        f = line.decode("utf-8", "replace").split(",")
        if len(f) == len(HDR[name]) and K.TS.match(f[0]) and pred(f):
            return pos, f
        pos += len(line) + 1
    return None


def find_event(gpu, br):
    j = HDR["XID_ERRORS"].index(gpu)
    lo_off, hi_off = K.SIZES["XID_ERRORS"] // 94 * br[0], K.SIZES["XID_ERRORS"] // 94 * br[1]
    while hi_off - lo_off > 48 * 1024:
        mid = (lo_off + hi_off) // 2
        r = row_at("XID_ERRORS", mid)
        if r is None:
            mid += 9000; r = row_at("XID_ERRORS", mid)
        if r is None:
            raise SystemExit("could not read a row during bisection")
        if r[1][j] == "94.0":
            hi_off = r[0]
        else:
            lo_off = r[0]
    hit = first_row_with("XID_ERRORS", lo_off, hi_off, lambda f: f[j] == "94.0")
    if not hit:
        raise SystemExit("event row not found in final bracket")
    return K.to_time(hit[1][0])


def find_time_offset(name, target):
    """Byte offset of a row boundary whose time is within 60 s of target (interpolation search)."""
    lo = (20000, K.T0)
    hi = (K.SIZES[name] - 40000, K.T0 + dt.timedelta(hours=K.SPAN_H))
    for _ in range(14):
        frac = (target - lo[1]).total_seconds() / max(1.0, (hi[1] - lo[1]).total_seconds())
        guess = int(lo[0] + (hi[0] - lo[0]) * min(0.98, max(0.02, frac)))
        r = row_at(name, guess)
        if r is None:
            continue
        t = K.to_time(r[1][0])
        if abs((t - target).total_seconds()) <= 60:
            return r[0], t
        if t < target:
            lo = (r[0], t)
        else:
            hi = (r[0], t)
    raise SystemExit(f"{name}: did not converge near {target}")


def main():
    plan, info = {}, {}
    for ev, (gpu, br) in EVENTS.items():
        t_e = find_event(gpu, br)
        info[ev] = {"gpu": gpu, "event_time": t_e.isoformat(), "xid": 94}
        print(f"event {ev} {gpu}: Xid 94 first seen in row {t_e}  (read so far {TALLY[0]/1e6:.2f} MB)", flush=True)
        for name in FILES:
            s, ts = find_time_offset(name, t_e - dt.timedelta(hours=2))
            e, te = find_time_offset(name, t_e + dt.timedelta(hours=1))
            plan[(ev, name)] = (s, e, ts, te)
    proj = sum(e - s for (s, e, _, _) in plan.values())
    print(f"\nprojected window bytes: {proj/1e6:.1f} MB | read so far: {TALLY[0]/1e6:.1f} MB | total {((proj + TALLY[0])/1e6):.1f} MB (cap {CAP/1e6:.0f} MB)")
    if proj + TALLY[0] > CAP:
        raise SystemExit("STOP: projected total exceeds the cap; nothing downloaded.")
    for (ev, name), (s, e, ts, te) in plan.items():
        chunks, pos = [], s
        while pos < e:
            n = min(4 * 1024 * 1024, e - pos)
            chunks.append(get(name, pos, n)); pos += n
        data = b"".join(chunks)[: e - s]
        with open(f"{OUT}/{name}_{ev}.csv", "w", encoding="utf-8") as fh:
            fh.write(",".join(HDR[name]) + "\n")
            fh.write(data.decode("utf-8", "replace"))
        info[ev][name] = {"bytes": e - s, "start": ts.isoformat(), "end": te.isoformat()}
        print(f"  saved {name}_{ev}.csv  {len(data)/1e6:.1f} MB  {ts} -> {te}", flush=True)
    json.dump(info, open(f"{OUT}/events.json", "w"), indent=2)
    print(f"\nTOTAL read this run: {TALLY[0]/1e6:.1f} MB (cap {CAP/1e6:.0f} MB)")


main()
