"""Range-probe Kalos CSV files. Reads at most `n` bytes per request and refuses a non-206 response."""
import datetime as dt
import re
import sys
import urllib.request

BASE = "https://huggingface.co/datasets/Qinghao/AcmeTrace/resolve/main/data/utilization/kalos/"
SIZES = {"XID_ERRORS": 754379488, "GPU_UTIL": 843403137, "GPU_TEMP": 845136147, "POWER_USAGE": 929567543}
T0 = dt.datetime.fromisoformat("2023-08-15 15:30:15+08:00")
SPAN_H = 377.2                                   # estimated total span, from the XID probes
TS = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\+08:00$")


def fetch(name: str, offset: int, n: int = 16384) -> bytes:
    req = urllib.request.Request(BASE + name + ".csv", headers={"Range": f"bytes={offset}-{offset + n - 1}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 206:
            raise SystemExit(f"server ignored the range (HTTP {r.status}); aborting")
        return r.read(n + 1)[:n]


def header(path: str) -> list[str]:
    return open(path, encoding="utf-8", errors="replace").read().split("\n")[0].split(",")


def first_row(raw: bytes, ncol: int):
    lines = raw.decode("utf-8", errors="replace").split("\n")
    for l in lines[1:-1]:
        f = l.split(",")
        if len(f) == ncol and TS.match(f[0]):
            return f
    return None


def to_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def offset_for(name: str, when: dt.datetime) -> int:
    frac = (when - T0).total_seconds() / 3600 / SPAN_H
    return max(0, min(SIZES[name] - 20000, int(SIZES[name] * frac)))
