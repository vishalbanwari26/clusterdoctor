"""Dashboard API. Replays stored investigations by default; live reruns are opt-in and capped.

Env: CD_DATA (replay dir), CD_ALLOW_LIVE=1 to enable POST .../rerun, CD_LIVE_DAILY_CAP / CD_LIVE_PER_IP /
CD_LIVE_MAX_CONCURRENT (limits, see limits.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(".env")

from .limits import LiveGuard, LiveLimit, client_ip  # noqa: E402

DATA = Path(os.environ.get("CD_DATA", "data/replays"))
WEB = Path(os.environ.get("CD_WEB", "web/dist"))
app = FastAPI(title="ClusterDoctor")
guard = LiveGuard(daily_cap=int(os.environ.get("CD_LIVE_DAILY_CAP", "20")),
                  per_ip=int(os.environ.get("CD_LIVE_PER_IP", "2")),
                  max_concurrent=int(os.environ.get("CD_LIVE_MAX_CONCURRENT", "2")))


ORDER = ["prompt-bloat", "retry-storm", "overlap", "misleading-event", "provider-slowdown",
         "gpu-thermal", "gpu-loader", "gpu-hardware"]   # real-traffic inference incidents first


def _ids() -> list[str]:
    found = [p.name[:-5] for p in DATA.glob("*.json") if not p.name.endswith(".telemetry.json")]
    return sorted(found, key=lambda i: (ORDER.index(i) if i in ORDER else len(ORDER), i))


def _load(rid: str) -> dict:
    if rid not in _ids():          # whitelist from the directory listing: no path traversal
        raise HTTPException(404, "unknown incident")
    return json.loads((DATA / f"{rid}.json").read_text())


def _live_enabled() -> bool:
    return os.environ.get("CD_ALLOW_LIVE") == "1" and bool(os.environ.get("NEBIUS_API_KEY"))


@app.get("/api/health")
def health(request: Request):
    ip = client_ip(request.headers, request.client.host if request.client else None)
    return {"mode": "replay", "live_enabled": _live_enabled(), "incidents": len(_ids()), **guard.status(ip)}


@app.get("/api/incidents")
def incidents():
    out = []
    for rid in _ids():
        d = _load(rid)
        inv = d.get("investigation") or {}
        diag = inv.get("diagnosis") or {}
        out.append({"id": rid, "title": d["title"], "domain": d["domain"], "summary": d["summary"],
                    "source": d["source"], "root_cause": diag.get("root_cause"), "confidence": diag.get("confidence")})
    return out


@app.get("/api/incidents/{rid}")
def incident(rid: str):
    d = _load(rid)
    d.pop("truth", None)        # revealed only via /truth
    d.pop("telemetry", None)    # server-side input for live reruns, not needed by the UI
    return d


@app.get("/api/incidents/{rid}/truth")
def truth(rid: str):
    """The injected ground truth. Kept behind its own call so the UI can hide it until revealed."""
    return _load(rid)["truth"]


@app.post("/api/incidents/{rid}/rerun")
def rerun(rid: str, request: Request):
    if not _live_enabled():
        raise HTTPException(403, "live reruns are disabled (set CD_ALLOW_LIVE=1 and NEBIUS_API_KEY)")
    d = _load(rid)
    try:
        guard.acquire(client_ip(request.headers, request.client.host if request.client else None))
    except LiveLimit as e:
        raise HTTPException(429, e.message)
    try:
        return _run_live(rid, d)
    except HTTPException:
        raise
    except Exception as e:          # never echo provider errors (they can contain request details)
        raise HTTPException(502, f"live run failed ({type(e).__name__}). The run was still counted.")
    finally:
        guard.release()


def _run_live(rid: str, d: dict) -> dict:
    from .agent import nemotron_chat
    from .replay import investigation_to_dict, run_app_investigation, run_gpu_investigation
    from .store import Request as Row, Store
    chat, verifier = nemotron_chat(), nemotron_chat(os.environ.get("CD_VERIFIER_MODEL"))
    tel = d["telemetry"]
    if d["domain"] == "inference":
        raw = json.loads((DATA / f"{rid}.telemetry.json").read_text())
        store = Store(":memory:")
        for row in raw["requests"]:
            store.add_request(Row(**dict(zip(raw["columns"], row))))
        for ts, kind, detail in raw["events"]:
            store.add_event(ts, kind, detail)
        inv = run_app_investigation(chat, verifier, store, tuple(tel["baseline"]), tuple(tel["incident"]), d["summary"])
    else:
        from .gpu import generate_fleet
        store = Store(":memory:")
        generate_fleet(store, {(n, g): s for n, g, s in tel["faults"]}, duration=tel["duration"],
                       onset=tel["onset"], seed=tel["seed"])
        inv = run_gpu_investigation(chat, verifier, store, tel["node"], tel["gpu"], tuple(tel["baseline"]),
                                    tuple(tel["incident"]), d["summary"])
    return investigation_to_dict(inv)


if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        f = (WEB / path).resolve()
        return FileResponse(f if f.is_file() and WEB.resolve() in f.parents else WEB / "index.html")
