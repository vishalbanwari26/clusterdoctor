"""Run an investigation with the full pipeline and turn it into a JSON-safe dict."""
from __future__ import annotations

import os
import time

from .agent import SYSTEM_STRAT, Investigation, investigate
from .bench import cost_usd
from .gpu_tools import GPU_SYSTEM, GPU_TOOL_SPECS, GpuTools
from .tools import TOOL_SPECS_STRAT, Tools

LAST = {"seconds": 0.0}


def run_app_investigation(chat, verifier, store, baseline, incident, summary) -> Investigation:
    t = time.time()
    inv = investigate(chat, Tools(store, baseline, incident), summary, specs=TOOL_SPECS_STRAT,
                      system=SYSTEM_STRAT, verifier=verifier, required_tests=2)
    inv.wall_s = time.time() - t  # type: ignore[attr-defined]
    return inv


def run_gpu_investigation(chat, verifier, store, node, gpu, baseline, incident, summary) -> Investigation:
    t = time.time()
    inv = investigate(chat, GpuTools(store, node, gpu, baseline, incident), summary + " (telemetry is simulated)",
                      specs=GPU_TOOL_SPECS, system=GPU_SYSTEM, verifier=verifier)
    inv.wall_s = time.time() - t  # type: ignore[attr-defined]
    return inv


def investigation_to_dict(inv: Investigation) -> dict:
    return {
        "diagnosis": inv.diagnosis, "trace": inv.trace, "dropped_evidence": inv.dropped_evidence,
        "steps": inv.steps, "revisions": inv.revisions, "protocol_retries": inv.protocol_retries,
        "tests_valid": inv.tests_valid, "claims_total": inv.claims_total,
        "claims_unsupported_first": inv.claims_unsupported_first,
        "claims_unsupported_final": inv.claims_unsupported_final,
        "tokens": {"agent": inv.prompt_tokens + inv.completion_tokens, "verifier": inv.verifier_tokens},
        "cost_usd": round(cost_usd(inv.prompt_tokens + inv.verifier_tokens, inv.completion_tokens), 4),
        "wall_s": round(getattr(inv, "wall_s", 0.0), 1),
        "model": os.environ.get("CD_AGENT_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b"),
    }


def run_real_gpu_investigation(chat, verifier, store, node, gpu, baseline, incident, summary, max_steps: int = 16) -> Investigation:
    """Same pipeline as the simulated GPU runs, with the Xid catalog tool and a prompt that says the data is real."""
    from .gpu_tools import REAL_SYSTEM, REAL_TOOL_SPECS
    t = time.time()
    inv = investigate(chat, GpuTools(store, node, gpu, baseline, incident), summary + " (REAL telemetry, AcmeTrace Kalos)",
                      specs=REAL_TOOL_SPECS, system=REAL_SYSTEM, verifier=verifier, max_steps=max_steps)
    inv.wall_s = time.time() - t  # type: ignore[attr-defined]
    return inv


# ---------------- fixed workflow runners (what the dashboard and API use) ----------------
def workflow_to_dict(out: dict, wall_s: float) -> dict:
    """Shape a hybrid_investigate result like investigation_to_dict so the dashboard reads both."""
    from .hybrid import pack_trace
    esc = out.get("escalation")
    tk = out["tokens"]; p, c, v = tk["prompt"], tk["completion"], tk["verifier"]
    if esc is not None:
        p, c, v = p + esc.prompt_tokens, c + esc.completion_tokens, v + esc.verifier_tokens
    cl = out["claims"]
    if esc is not None:                                    # the agent's answer is final, with its own trace and checks
        base = investigation_to_dict(esc)
        base.update({"cost_usd": round(cost_usd(p + v, c), 4), "wall_s": round(wall_s, 1)})
    else:
        base = {"diagnosis": out["diagnosis"], "trace": pack_trace(out["pack"]), "dropped_evidence": [], "steps": tk["calls"],
                "revisions": 1 if cl["revised"] else 0, "protocol_retries": 0, "tests_valid": 0, "claims_total": cl["claims_total"],
                "claims_unsupported_first": cl["first_issues"], "claims_unsupported_final": cl["final_issues"],
                "tokens": {"agent": p + c, "verifier": v}, "cost_usd": round(cost_usd(p + v, c), 4), "wall_s": round(wall_s, 1),
                "model": os.environ.get("CD_AGENT_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b")}
    base["workflow"] = {"escalated": out["escalated"], "reasons": out["reasons"], "first_pass": out["first_pass"]}
    return base


def run_workflow(domain: str, chat, verifier, store, baseline, incident, summary, node=None, gpu=None, real=False) -> dict:
    """domain: 'inference' or 'gpu'. Fixed evidence pack -> one strict-schema call -> claim check -> escalate to the tool agent only if needed."""
    from .hybrid import GPU_SYSTEM_WF, INF_SYSTEM, REAL_SYSTEM_WF, gpu_pack, hybrid_investigate, inference_pack
    t = time.time()
    if domain == "inference":
        tools = Tools(store, baseline, incident)
        esc = lambda: investigate(chat, tools, summary, specs=TOOL_SPECS_STRAT, system=SYSTEM_STRAT, verifier=verifier, required_tests=2)  # noqa: E731
        out = hybrid_investigate(chat, verifier, tools, summary, esc, pack=inference_pack(tools), system=INF_SYSTEM, strict=True)
    else:
        from .gpu_tools import GPU_ROOT_CAUSES, REAL_SYSTEM, REAL_TOOL_SPECS
        tools = GpuTools(store, node, gpu, baseline, incident)
        note = " (REAL telemetry, AcmeTrace Kalos)" if real else " (telemetry is simulated)"
        esc = lambda: investigate(chat, tools, summary + note, specs=REAL_TOOL_SPECS if real else GPU_TOOL_SPECS,  # noqa: E731
                                  system=REAL_SYSTEM if real else GPU_SYSTEM, verifier=verifier, max_steps=16 if real else 10)
        out = hybrid_investigate(chat, verifier, tools, summary + note, esc, pack=gpu_pack(tools),
                                 system=REAL_SYSTEM_WF if real else GPU_SYSTEM_WF, labels=GPU_ROOT_CAUSES, strict=True)
    return workflow_to_dict(out, time.time() - t)


def run_live_workflow(rid: str, d: dict, data_dir, chat, verifier) -> dict:
    """Rebuild an incident's telemetry from a stored replay and run the fixed workflow on it. Used by the API and by the replay builder."""
    import json
    from pathlib import Path

    from .store import Request as Row, Store
    tel = d["telemetry"]; baseline, incident = tuple(tel["baseline"]), tuple(tel["incident"])
    store = Store(":memory:")
    if tel.get("real"):
        from .real import load_event, load_slices
        info = load_event(store, load_slices()["events"][tel["event"]])
        return run_workflow("gpu", chat, verifier, store, baseline, incident, d["summary"], node=info["node"], gpu=info["gpu"], real=True)
    if d["domain"] == "inference":
        raw = json.loads((Path(data_dir) / f"{rid}.telemetry.json").read_text())
        for row in raw["requests"]:
            store.add_request(Row(**dict(zip(raw["columns"], row))))
        for ts, kind, detail in raw["events"]:
            store.add_event(ts, kind, detail)
        return run_workflow("inference", chat, verifier, store, baseline, incident, d["summary"])
    from .gpu import generate_fleet
    generate_fleet(store, {(n, g): s for n, g, s in tel["faults"]}, duration=tel["duration"], onset=tel["onset"], seed=tel["seed"])
    return run_workflow("gpu", chat, verifier, store, baseline, incident, d["summary"], node=tel["node"], gpu=tel["gpu"])
