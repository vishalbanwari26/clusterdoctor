"""Diagnostic tools for a flagged GPU. Read-only queries over gpu_metrics."""
from __future__ import annotations

import copy
import statistics
from typing import Callable

from .gpu import CPU_UTIL, POWER, SM_CLOCK, TEMP, THROTTLE, UTIL, XID
from .store import Store
from .tools import TOOL_SPECS, WINDOW_ARG, NO_ARGS

GPU_ROOT_CAUSES = ["thermal_throttling", "data_loader_bottleneck", "gpu_hardware_fault",
                   "insufficient_evidence"]

GPU_SYSTEM = """You are ClusterDoctor, an infrastructure reliability investigator for GPU clusters.
A monitor flagged one GPU for low utilization. Find the root cause using only the tools.
Method: form competing hypotheses (e.g. thermal throttling, input-pipeline starvation, hardware
fault), call tools that can tell them apart, and reject hypotheses the data contradicts.
Low utilization alone does not identify a cause. Compare the flagged GPU with its baseline and
with its peer GPUs. If the telemetry cannot decide, submit insufficient_evidence.
Finish by calling submit_diagnosis, citing the call_id (like call_1) of the tool result that
supports each claim. The data may be simulated; say what you can and cannot conclude from it."""


# Entries read from NVIDIA's Xid catalog (https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html).
# Only these four were verified. Anything else is reported as unknown rather than guessed.
XID_CATALOG = {
    31: {"name": "ROBUST_CHANNEL_FIFO_ERROR_MMU_ERR_FLT", "description": "GPU memory page fault",
         "meaning": "Logged when the MMU reports a fault. Typically an application-level bug, possibly a driver or hardware bug.",
         "action": "Restart the application. If it repeats on the same GPU, run hardware diagnostics; on different GPUs, check the application."},
    43: {"name": "ROBUST_CHANNEL_RESETCHANNEL_VERIF_ERROR", "description": "GPU stopped processing",
         "meaning": "Logged when a user application hits a software-induced fault and must terminate. The GPU itself stays healthy.",
         "action": "Ignore on the GPU side; usually a user application error."},
    45: {"name": "ROBUST_CHANNEL_PREEMPTIVE_REMOVAL", "description": "Preemptive cleanup, due to previous errors",
         "meaning": "Logged when the application aborts (examples: Ctrl-C, GPU reset, SIGKILL). Often follows an earlier error such as a double-bit error.",
         "action": "On its own, restart the fabric manager; alongside another Xid, follow that Xid."},
    94: {"name": "ROBUST_CHANNEL_CONTAINED_ERROR", "description": "Contained memory error",
         "meaning": "Logged when the driver handles an error on a GPU that supports error containment. The error is contained to one "
                    "application, which must restart. Xid 45 is expected alongside it. One possible cause is ECC memory error handling.",
         "action": "Restart the affected application."},
}


class GpuTools:
    def __init__(self, store: Store, node: str, gpu: int,
                 baseline: tuple[float, float], incident: tuple[float, float]):
        self.store, self.node, self.gpu = store, node, gpu
        self.baseline, self.incident = baseline, incident

    def _w(self, name):
        return {"baseline": self.baseline, "incident": self.incident}[name]

    def _vals(self, metric, window, gpu=None):
        a, b = self._w(window)
        rows = self.store.db.execute(
            "SELECT value FROM gpu_metrics WHERE node=? AND gpu=? AND metric=? AND ts>=? AND ts<?",
            (self.node, self.gpu if gpu is None else gpu, metric, a, b)).fetchall()
        return [r["value"] for r in rows]

    def _mean(self, metric, window, gpu=None):
        v = self._vals(metric, window, gpu)
        return round(statistics.mean(v), 1) if v else None

    def compare_windows(self) -> dict:
        """Mean utilization, temperature, power, SM clock for the flagged GPU, baseline vs incident."""
        return {w: {"util_pct": self._mean(UTIL, w), "temp_c": self._mean(TEMP, w),
                    "power_w": self._mean(POWER, w), "sm_clock_mhz": self._mean(SM_CLOCK, w)}
                for w in ("baseline", "incident")}

    def throttle_reasons(self, window: str) -> dict:
        """Share of samples with a clock-throttle reason set (0x20 = software thermal slowdown), plus max Xid."""
        v = self._vals(THROTTLE, window)
        xid = self._vals(XID, window)
        return {"samples": len(v),
                "share_throttled": round(sum(x > 0 for x in v) / len(v), 2) if v else None,
                "thermal_slowdown_share": round(sum(int(x) & 0x20 > 0 for x in v) / len(v), 2) if v else None,
                "xid_errors_seen": sorted({int(x) for x in xid if x > 0})}

    def util_pattern(self, window: str) -> dict:
        """How utilization behaves over time: steady-but-lower vs bursty (starved) pattern."""
        v = self._vals(UTIL, window)
        if not v:
            return {"samples": 0}
        return {"samples": len(v), "mean": round(statistics.mean(v), 1), "stdev": round(statistics.pstdev(v), 1),
                "min": round(min(v), 1), "max": round(max(v), 1),
                "share_below_50pct": round(sum(x < 50 for x in v) / len(v), 2)}

    def host_cpu(self, window: str) -> dict:
        """Mean host CPU utilization for the node (data loading runs on the CPU)."""
        return {"host_cpu_util_pct": self._mean(CPU_UTIL, window)}

    def xid_lookup(self, code: int) -> dict:
        """What an Xid code means, from NVIDIA's Xid catalog (only a few codes are included)."""
        entry = XID_CATALOG.get(int(code))
        if entry is None:
            return {"code": int(code), "known": False,
                    "note": "Not in the local catalog (only 31, 43, 45 and 94 are included). Do not guess its meaning."}
        return {"code": int(code), "known": True, **entry, "source": "NVIDIA Xid catalog"}

    def peer_gpus(self) -> list[dict]:
        """Same-node GPUs over the incident window: is the problem isolated to one GPU or node-wide?"""
        gpus = [r["gpu"] for r in self.store.db.execute(
            "SELECT DISTINCT gpu FROM gpu_metrics WHERE node=? ORDER BY gpu", (self.node,))]
        return [{"gpu": g, "is_flagged": g == self.gpu, "util_pct": self._mean(UTIL, "incident", g),
                 "temp_c": self._mean(TEMP, "incident", g)} for g in gpus]

    def registry(self) -> dict[str, Callable]:
        return {"compare_windows": self.compare_windows, "throttle_reasons": self.throttle_reasons,
                "util_pattern": self.util_pattern, "host_cpu": self.host_cpu, "peer_gpus": self.peer_gpus,
                "xid_lookup": self.xid_lookup}


def _spec(name, desc, params):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": params}}


_submit = copy.deepcopy(TOOL_SPECS[-1])
_submit["function"]["parameters"]["properties"]["root_cause"]["enum"] = GPU_ROOT_CAUSES

GPU_TOOL_SPECS = [
    _spec("compare_windows", "Flagged GPU: mean util, temperature, power, SM clock, baseline vs incident.", NO_ARGS),
    _spec("throttle_reasons", "Share of samples with clock throttling / thermal slowdown, and any Xid errors.", WINDOW_ARG),
    _spec("util_pattern", "Utilization spread over time (stdev, min, max, share below 50%).", WINDOW_ARG),
    _spec("host_cpu", "Host CPU utilization on the node.", WINDOW_ARG),
    _spec("peer_gpus", "Other GPUs on the same node during the incident, to check if the problem is isolated.", NO_ARGS),
    _submit,
]


# ---- real-data variant: same tools plus the Xid catalog, and a prompt that says the data is real ----
REAL_TOOL_SPECS = [*GPU_TOOL_SPECS[:-1],
                   _spec("xid_lookup", "Explains an NVIDIA Xid error code using NVIDIA's catalog (a few codes only).",
                         {"type": "object", "properties": {"code": {"type": "integer"}}, "required": ["code"]}),
                   GPU_TOOL_SPECS[-1]]

REAL_SYSTEM = GPU_SYSTEM.replace(
    "A monitor flagged one GPU for low utilization.",
    "A monitor flagged one GPU, either for low utilization or because the driver reported an Xid error. "
    "The incident text says which.").replace(
    "The data may be simulated; say what you can and cannot conclude from it.",
    "This is REAL telemetry from a production GPU cluster, sampled every 15 s. It has utilization, temperature, power and "
    "the driver's Xid error code. It has NO clock, throttle-reason or host-CPU data, and some samples are missing: when a "
    "tool returns no data, say so instead of assuming. Use xid_lookup to interpret any Xid code, and only rely on what the "
    "catalog returns. The Xid field keeps the last code, so a change is an event. Say what you can and cannot conclude.")
