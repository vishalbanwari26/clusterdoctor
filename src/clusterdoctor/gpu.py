"""GPU fleet telemetry in the shape of NVIDIA DCGM exporter metrics.

There is no real GPU behind this data: every sample is generated and stored with
source='simulated'. Metric names follow dcgm-exporter so a real Prometheus
scrape of dcgm-exporter can be swapped in later. Verify exact names/units
against the exporter version you deploy.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .store import Store

UTIL = "DCGM_FI_DEV_GPU_UTIL"                  # percent
TEMP = "DCGM_FI_DEV_GPU_TEMP"                  # celsius
POWER = "DCGM_FI_DEV_POWER_USAGE"              # watts
SM_CLOCK = "DCGM_FI_DEV_SM_CLOCK"              # MHz
THROTTLE = "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS"  # bitmask; 0x20 = SW thermal, 0x40 = HW thermal
XID = "DCGM_FI_DEV_XID_ERRORS"                 # last Xid code, 0 = none
CPU_UTIL = "node_cpu_utilization_percent"      # host side, not DCGM

THERMAL_SLOWDOWN = 0x20


@dataclass(frozen=True)
class GpuScenario:
    name: str
    root_cause: str        # ground truth for the benchmark
    description: str


SCENARIOS = {
    "healthy": GpuScenario("healthy", "none", "training at steady state"),
    "thermal_throttle": GpuScenario(
        "thermal_throttle", "thermal_throttling",
        "cooling degraded: temperature climbs, clocks drop, utilization falls"),
    "dataloader_bottleneck": GpuScenario(
        "dataloader_bottleneck", "data_loader_bottleneck",
        "input pipeline starves the GPU: low, bursty utilization, host CPU saturated, GPU cool"),
    "gpu_hardware_fault": GpuScenario(
        "gpu_hardware_fault", "gpu_hardware_fault",
        "GPU reports an Xid error and stops doing work: near-zero utilization and power, normal temperature"),
    "transient_dip": GpuScenario("transient_dip", "none", "45 s utilization dip, then recovers (decoy)"),
    "idle": GpuScenario("idle", "none", "idle by schedule for the whole run (decoy)"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS gpu_metrics (
    ts REAL NOT NULL, node TEXT NOT NULL, gpu INTEGER NOT NULL,
    metric TEXT NOT NULL, value REAL NOT NULL, source TEXT NOT NULL DEFAULT 'simulated'
);
CREATE INDEX IF NOT EXISTS idx_gpu_ts ON gpu_metrics(ts);
CREATE INDEX IF NOT EXISTS idx_gpu_key ON gpu_metrics(node, gpu, metric, ts);
"""


def sample(scenario: str, t: float, onset: float, rng: random.Random) -> dict[str, float]:
    """One scrape of one GPU. `onset` is when the fault begins (seconds)."""
    n = lambda sd: rng.gauss(0, sd)  # noqa: E731
    faulty = t >= onset
    ramp = min(1.0, (t - onset) / 120) if faulty else 0.0   # fault develops over 2 minutes

    util, temp, clock, cpu, throttle = 96 + n(2), 68 + n(1.5), 1980 + n(15), 45 + n(5), 0.0
    if scenario == "thermal_throttle" and faulty:
        temp = 68 + 20 * ramp + n(1.5)
        throttle = THERMAL_SLOWDOWN if temp > 80 else 0.0
        clock = 1980 - 700 * ramp + n(15)
        util = 96 - 50 * ramp + n(3)
    elif scenario == "dataloader_bottleneck" and faulty:
        util = rng.choice([15, 20, 30, 90]) + n(4) if ramp > 0.1 else util
        cpu = 97 + n(1.5)
        temp = 68 - 8 * ramp + n(1.5)
    xid = 0.0
    if scenario == "gpu_hardware_fault" and faulty:
        util, xid = max(0.0, 2 + n(1.5)), 48.0
    elif scenario == "transient_dip" and faulty and t - onset < 45:
        util = 20 + n(3)
    elif scenario == "idle":
        util = max(0.0, 1 + n(0.5))
    util = max(0.0, min(100.0, util))
    power = 90 + 3.2 * util + n(5)
    return {UTIL: util, TEMP: temp, POWER: power, SM_CLOCK: clock, THROTTLE: throttle,
            XID: xid, CPU_UTIL: max(0.0, min(100.0, cpu))}


def generate(store: Store, scenario: str, t0: float, duration: float, onset: float,
             node: str = "node-a", gpus: int = 4, step: float = 5.0, seed: int = 0) -> None:
    """Write simulated scrapes into the store. Only GPU 0 is faulty (others stay healthy)."""
    rng = random.Random(seed)
    store.db.executescript(SCHEMA)
    rows = []
    t = 0.0
    while t < duration:
        for g in range(gpus):
            for metric, value in sample(scenario if g == 0 else "healthy", t, onset, rng).items():
                if metric == CPU_UTIL and g != 0:
                    continue  # host metric recorded once per node
                rows.append((t0 + t, node, g, metric, value, "simulated"))
        t += step
    with store.lock:
        store.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows)
        store.db.commit()


def prometheus_text(store: Store, at: float) -> str:
    """Latest sample per (gpu, metric) at/before `at`, in Prometheus exposition format."""
    out = []
    q = """SELECT node, gpu, metric, value FROM gpu_metrics g WHERE ts = (
             SELECT MAX(ts) FROM gpu_metrics WHERE node=g.node AND gpu=g.gpu AND metric=g.metric AND ts <= ?)"""
    for r in store.db.execute(q, (at,)):
        out.append(f'{r["metric"]}{{node="{r["node"]}",gpu="{r["gpu"]}",simulated="true"}} {r["value"]:.2f}')
    return "\n".join(sorted(out)) + "\n"


def generate_fleet(store: Store, faults: dict[tuple[str, int], str], nodes: int = 8, gpus: int = 8,
                   duration: float = 12000, onset: float = 7200, step: float = 30.0, seed: int = 0) -> None:
    """A large simulated fleet. `faults` maps (node, gpu) -> scenario; every other GPU is healthy.
    Host CPU is a node-level metric, stored on each of the node's GPU rows."""
    rng = random.Random(seed)
    store.db.executescript(SCHEMA)
    names = [f"node-{i:02d}" for i in range(nodes)]
    rows, t = [], 0.0
    while t < duration:
        for node in names:
            samples = {g: sample(faults.get((node, g), "healthy"), t, onset, rng) for g in range(gpus)}
            loader = [g for g in range(gpus) if faults.get((node, g)) == "dataloader_bottleneck"]
            cpu = samples[loader[0]][CPU_UTIL] if loader else max(0.0, rng.gauss(45, 5))
            for g, m in samples.items():
                m[CPU_UTIL] = cpu
                rows += [(t, node, g, k, v, "simulated") for k, v in m.items()]
        t += step
    with store.lock:
        store.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows)
        store.db.commit()
