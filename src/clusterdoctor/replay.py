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
