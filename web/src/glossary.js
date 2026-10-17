import { pretty } from "./util.js";

// What each diagnosis means, in plain words.
export const CAUSES = {
  prompt_expansion: { label: "Prompts got much larger", plain: "The app started sending far more text with each request (for example, more retrieved documents), so every call does more work." },
  client_concurrency: { label: "Too many requests at once", plain: "The app sends many requests at the same time, and they slow each other down." },
  retry_storm: { label: "Retries piling up", plain: "Requests fail or get rate-limited, the app retries them after waiting, and users feel that extra delay." },
  provider_side: { label: "Slowdown outside the app", plain: "Nothing changed in how the app calls the model, yet responses got slower. The cause sits with the provider or the network." },
  insufficient_evidence: { label: "Not enough evidence", plain: "The data cannot tell the possible causes apart, so the agent declined to guess." },
  thermal_throttling: { label: "GPU overheating, slowing itself down", plain: "The GPU got too hot and lowered its own clock speed to protect itself, so it does less work." },
  data_loader_bottleneck: { label: "GPU waiting for data", plain: "The input pipeline cannot feed data fast enough, so the GPU sits idle between batches. The host CPU is usually maxed out." },
  gpu_hardware_fault: { label: "GPU hardware error", plain: "The GPU driver reported a hardware-related error code (an Xid). Depending on the code, the affected program may have to restart, and the GPU may or may not show a performance symptom." },
};
export const causeLabel = (c) => CAUSES[c]?.label ?? pretty(c);
export const causePlain = (c) => CAUSES[c]?.plain ?? "";

// Hover/focus definitions for jargon.
export const TERMS = {
  p95: "95% of requests finished faster than this. It captures the slow tail that users notice.",
  baseline: "The normal period before the problem started. Everything is compared against it.",
  watcher: "A simple statistical check, with no AI involved. It opens an incident when a metric stays far from its normal level.",
  stratified: "Comparing like with like: change one factor while holding another fixed, so two overlapping changes can be told apart.",
  concurrency: "How many requests are in flight at the same moment.",
  retries: "How many times a failed request was sent again before it succeeded.",
  utilization: "How busy the GPU is, as a percentage of its capacity.",
  throttling: "A GPU deliberately lowering its clock speed, for example because it is too hot.",
  xid: "An error code that NVIDIA GPUs report when something goes wrong.",
  confidence: "How sure the model says it is. It is the model's own statement, not a measured probability.",
  tokens: "Pieces of text the model reads and writes. More input tokens means more work per request.",
};

const win = (w) => ({ baseline: "normal period", incident: "incident", both: "both periods" }[w] ?? w);
const factor = (f) => ({ input_tokens: "prompt size", retries: "retries", concurrency: "concurrency" }[f] ?? f);

// Friendly name and one-line purpose for every tool the agent can call.
export const TOOLS = {
  compare_windows: { title: () => "Compared the normal period with the incident", why: "Shows what changed overall." },
  list_events: { title: () => "Looked for deploys and config changes", why: "A recorded change may explain the timing." },
  latency_by_input_size: { title: (a) => `Latency by prompt size (${win(a.window)})`, why: "Do bigger prompts take longer?" },
  latency_by_concurrency: { title: (a) => `Latency by simultaneous requests (${win(a.window)})`, why: "Do parallel requests slow each other down?" },
  retry_breakdown: { title: (a) => `Latency by number of retries (${win(a.window)})`, why: "Are retried requests the slow ones?" },
  stratified_latency: { title: (a) => `Compared ${factor(a.factor_a)} with ${factor(a.factor_b)} (${win(a.window)})`, why: "Changes one factor while holding the other fixed, to separate overlapping causes." },
  throttle_reasons: { title: (a) => `Checked for throttling and GPU errors (${win(a.window)})`, why: "Throttling points to heat, Xid errors point to hardware." },
  util_pattern: { title: (a) => `Looked at how utilization behaves over time (${win(a.window)})`, why: "Steady-but-lower and bursty-and-starved mean different things." },
  host_cpu: { title: (a) => `Checked the host CPU (${win(a.window)})`, why: "Data loading runs on the CPU. A maxed-out CPU can starve the GPU." },
  peer_gpus: { title: () => "Compared with the other GPUs on the same machine", why: "Is the problem one GPU or the whole node?" },
};
// Sections of the fixed evidence pack (collected by code, not chosen by the model).
Object.assign(TOOLS, {
  pack_windows: { title: () => "Compared the normal period with the incident", why: "Shows what changed overall." },
  pack_events: { title: () => "Looked for deploys and config changes", why: "A recorded change may explain the timing." },
  pack_retries_baseline: { title: () => "Latency by number of retries (normal period)", why: "Are retried requests the slow ones?" },
  pack_retries_incident: { title: () => "Latency by number of retries (incident)", why: "Are retried requests the slow ones?" },
  pack_strat_input_retries: { title: () => "Compared prompt size with retries (both periods)", why: "Changes one factor while holding the other fixed, to separate overlapping causes." },
  pack_strat_input_concurrency: { title: () => "Compared prompt size with concurrency (both periods)", why: "Changes one factor while holding the other fixed, to separate overlapping causes." },
  pack_strat_retries_concurrency: { title: () => "Compared retries with concurrency (both periods)", why: "Changes one factor while holding the other fixed, to separate overlapping causes." },
  pack_effect_split: { title: () => "Worked out which factor explains the slowdown", why: "Uses only variation inside the incident window, and says which factors cannot be told apart." },
  pack_gpu_windows: { title: () => "Compared the normal period with the incident", why: "Utilization, temperature, power and clocks for the flagged GPU." },
  pack_gpu_throttle_baseline: { title: () => "Throttling and GPU errors (normal period)", why: "Throttling points to heat, Xid errors point to the driver." },
  pack_gpu_throttle_incident: { title: () => "Throttling and GPU errors (incident)", why: "Throttling points to heat, Xid errors point to the driver." },
  pack_gpu_pattern_baseline: { title: () => "How utilization behaves over time (normal period)", why: "Steady-but-lower and bursty-and-starved mean different things." },
  pack_gpu_pattern_incident: { title: () => "How utilization behaves over time (incident)", why: "Steady-but-lower and bursty-and-starved mean different things." },
  pack_gpu_host_cpu_baseline: { title: () => "Host CPU (normal period)", why: "Data loading runs on the CPU. A maxed-out CPU can starve the GPU." },
  pack_gpu_host_cpu_incident: { title: () => "Host CPU (incident)", why: "Data loading runs on the CPU. A maxed-out CPU can starve the GPU." },
  pack_gpu_peers: { title: () => "Compared with the other GPUs on the same machine", why: "Is the problem one GPU or the whole node?" },
  pack_gpu_xid_catalog: { title: () => "What the Xid error code means (NVIDIA catalog)", why: "Only a few codes are in the local catalog." },
});

export const toolTitle = (t, args) => TOOLS[t]?.title(args) ?? pretty(t);
export const toolWhy = (t) => TOOLS[t]?.why ?? "";
