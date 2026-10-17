"""Hidden-Xid test: can utilization, temperature and power alone tell a driver error from a normal job ending?

The Xid series is never loaded for these cases. Ground truth comes from the real Xid series of the dataset.
"""
from __future__ import annotations

import copy
import json
import time

from .agent import Chat
from .bench import _parse_json
from .gpu_tools import GpuTools, GPU_TOOL_SPECS, _spec
from .tools import NO_ARGS, WINDOW_ARG

LABELS = ["driver_error_reported", "no_driver_error", "insufficient_evidence"]

SYSTEM = """You are ClusterDoctor. A GPU in a production cluster had a notable event at the anchor time (5 minutes into the
incident window). The question: did the NVIDIA driver report an Xid error on THIS GPU in this window?
You must answer from telemetry only. The Xid series is NOT available. You have utilization, temperature and power for the
GPU and the other GPUs on its machine, 15 s samples. A utilization collapse alone does not prove a driver error: jobs also
end, get cancelled or finish normally. Missing samples are null. Use the tools, then call submit_diagnosis with root_cause
driver_error_reported, no_driver_error, or insufficient_evidence if the telemetry cannot decide. Cite call_ids as evidence."""

_submit = copy.deepcopy(GPU_TOOL_SPECS[-1])
_submit["function"]["parameters"]["properties"]["root_cause"]["enum"] = LABELS
HIDDEN_SPECS = [s for s in GPU_TOOL_SPECS if s["function"]["name"] in ("compare_windows", "util_pattern", "peer_gpus")] + [_submit]


class HiddenTools(GpuTools):
    """Same read-only queries; the registry only exposes tools that cannot leak or imply Xid information."""
    def registry(self):
        r = super().registry()
        return {k: r[k] for k in ("compare_windows", "util_pattern", "peer_gpus")}


def baseline_answer(chat: Chat, tools: HiddenTools, system_prompt: str = SYSTEM, labels: list[str] = LABELS) -> dict:
    win = ("baseline", "incident")
    dump = {"windows": tools.compare_windows(), "utilization_pattern": {w: tools.util_pattern(w) for w in win},
            "peer_gpus_same_machine_during_incident": tools.peer_gpus()}
    system = (system_prompt.split("Use the tools")[0] + 'Reply with ONLY JSON: {"root_cause": one of ' + str(labels) +
              ', "confidence": "high"|"medium"|"low", "reasoning": "<short>"}.')
    t = time.time()
    reply = chat([{"role": "system", "content": system}, {"role": "user", "content": json.dumps(dump, default=str)}], [])
    p = _parse_json(reply.get("content") or "")
    ok = p is not None and p.get("root_cause") in labels
    return {"root_cause": p["root_cause"] if ok else "unparseable", "confidence": p.get("confidence", "low") if ok else "low",
            "reasoning": (p or {}).get("reasoning", "")[:300], "latency_s": time.time() - t,
            "prompt_tokens": reply.get("prompt_tokens") or 0, "completion_tokens": reply.get("completion_tokens") or 0}


# ---- Test 3: false-alarm test on real job-end collapses (no Xid, normal temperature) ----
FA_LABELS = ["thermal_throttling", "data_loader_bottleneck", "gpu_hardware_fault", "no_fault_job_ended", "insufficient_evidence"]
FA_SYSTEM = """You are ClusterDoctor. A GPU in a production cluster had a sudden utilization collapse at the anchor time (5 minutes
into the incident window). Telemetry is REAL (15 s samples): utilization, temperature and power for the GPU and the other GPUs on
its machine. Missing samples are null. There is no driver, log or scheduler information. Possible explanations:
- thermal_throttling: this GPU got hot and slowed down (temperature high or rising).
- data_loader_bottleneck: the GPU is starved of data: low, bursty utilization while it stays cool.
- gpu_hardware_fault: the GPU itself failed.
- no_fault_job_ended: nothing is wrong; the workload ended, was cancelled or restarted (often every GPU of the job stops together and temperatures fall).
- insufficient_evidence: the data cannot decide.
Use the tools, then call submit_diagnosis citing call_ids. Do not invent a fault the data does not show."""
_fa_submit = copy.deepcopy(GPU_TOOL_SPECS[-1])
_fa_submit["function"]["parameters"]["properties"]["root_cause"]["enum"] = FA_LABELS
FA_SPECS = [s for s in GPU_TOOL_SPECS if s["function"]["name"] in ("compare_windows", "util_pattern", "peer_gpus")] + [_fa_submit]
