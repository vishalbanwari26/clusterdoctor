# ClusterDoctor

From monitoring symptoms to diagnosing root causes.

ClusterDoctor watches telemetry from an AI inference app and a GPU fleet, opens an incident when something degrades, and runs an investigation: it forms competing hypotheses, queries diagnostic tools to tell them apart, and writes a report with the evidence, the rejected hypotheses and what is still uncertain. Reasoning runs on NVIDIA Nemotron through Nebius Token Factory.

Built for the Nebius x NVIDIA Global AI Hackathon (track: Best Apps and Agents).

## Status

| Part | State |
|---|---|
| Instrumented Token Factory client, telemetry store | Done, used live |
| Latency watcher and GPU-fleet watcher | Done, tested |
| Investigation agent, diagnostic tools, claim verification | Done, benchmarked |
| Benchmark harnesses and results | Done (see below) |
| FastAPI backend and React dashboard (dark mode) | Done locally: fleet view, incident feed, investigation trace, report |
| Hosted demo URL, demo video | **Not done yet** |

This repo is new for the hackathon. It reuses the idea of evidence-first root-cause analysis from an earlier project (Grid Co-Pilot) but shares no code with it.

## Where Nemotron and Token Factory are used

- **Investigation and tool selection:** `nvidia/Nemotron-3-Ultra-550b-a55b` via Token Factory (OpenAI-compatible API, tool calling). Also used as the claim verifier and as the single-pass baseline, so comparisons isolate the investigation method.
- **The application being diagnosed:** `nvidia/Nemotron-3_5-Lightning` via Token Factory. All latency, token and retry telemetry in the benchmarks comes from real calls to it.

## How it works

```
telemetry -> watcher (statistics, no LLM) -> incident -> agent + tools -> verified report
```

1. **Watchers** are plain statistics. A latency incident opens when p95 stays above 1.5x the baseline for two windows. A GPU incident opens when a GPU's utilization stays 40% below its own baseline for two windows (GPUs that were never busy are ignored).
2. **The agent** calls read-only tools: window comparison, deploy events, latency by input size / concurrency / retries, a stratified latency grid (vary one factor while holding another fixed), and for GPUs: temperature, clocks, throttle reasons, Xid errors, host CPU, peer GPUs.
3. **Checks on the answer.** Every cited call id must exist. A second pass checks each factual or numeric claim against the tool results, and the agent must revise claims that conflict. The agent must also test its top two hypotheses with the stratified tool before diagnosing. If no evidence survives, the answer becomes `insufficient_evidence`.

## What is real and what is simulated

- **Real:** every request in the Token Factory benchmarks (latency, time to first token, token counts, status) comes from live calls.
- **Injected on the client:** the retry-storm 429s and the `provider_slowdown` delay are injected faults. Rows carry `source = live_injected`. Retry and backoff behavior on top of them is real.
- **Simulated:** all GPU telemetry. There is no GPU behind it. Metric names follow NVIDIA DCGM exporter, but the series are generated, labelled `simulated`, and each fault has a clear signature that I wrote. Results on it show the pipeline works, not how accurate it is on a real cluster. Verify metric names against your dcgm-exporter version before a real deployment.

## Results

All numbers are from `bench/results_*.json`. Cases are small (3 repeats per fault), so read differences of one or two cases as noise.

### Detection
All 21 injected latency incidents detected (42 evaluations: each case run with and without the deploy event), 0/3 false alerts on healthy runs. On the 64-GPU fleet, all 3 real faults detected in every seed, no false alerts (after the idle-GPU fix below).

### Token Factory incidents (live traffic)
Easy cases: one fault at a time (prompt bloat, high concurrency, retry storm), 18 evaluations.
Hard cases: 24 evaluations, designed so a one-shot dashboard summary can mislead: two overlapping changes, a misleading deploy event, bloat in a subset of requests, a provider-side slowdown.

| Hard cases (24) | Correct | Wrong with high confidence | Time | Cost |
|---|---|---|---|---|
| One call, dashboard summary | 12 | 11 | 3 s | $0.003 |
| Agent with tools | 15 | 9 | 13 s | $0.016 |
| + claim verification | 16 | 8 | 29 s | $0.024 |
| + stratified hypothesis tests | 21 | 2 | 40 s | $0.038 |
| **One call given the same stratified tables** | **21** | **2** | **6 s** | **$0.006** |

On easy cases the agent got 18/18 and the dashboard-summary baseline 17/18.

**What this says.** The large gain came from giving the model the right evidence (stratified comparisons that separate confounded factors), not from the agent loop. A single call given those tables ties the agent at a sixth of the cost. I do not claim an agent beats a single call on these cases.

Claim verification works at its own job: 4% of claims in the first submission (10 of 224) contradicted or went beyond the tool data, 0 after revision. In the later run with the stratified protocol it was 7% (18 of 266) before and 1 claim after. It did not by itself raise accuracy (15 to 16 of 24), because the main failure was causal reasoning, not misread numbers.

Remaining failures: the confounded `overlap` and `misleading_event` cases when a misleading deploy event is present. The model tends to blame the most visible change (larger prompts).

**Caveat on the stratified result.** I designed the stratified tool after seeing the agent fail on these exact cases, and its factors match the dimensions I varied. It shows the protocol works on these fault families, not that it generalizes. Cases written independently are needed for that.

### GPU fleet (simulated, 64 GPUs, 179,200 samples)
Three faults on different nodes per seed (thermal throttling, data-loader starvation, hardware fault with an Xid error) plus two decoys, 9 incidents over 3 seeds.

| | Correct | Cost per incident | Time |
|---|---|---|---|
| One call, aggregate dump (about 3.3k tokens) | 8/9 | $0.0096 | 6 s |
| Agent with GPU tools | 9/9 | $0.0156 | 10 s |

The raw series would be millions of tokens, but a per-GPU aggregate table fits in 3.3k and was enough for the one-shot call. Scale alone did not separate the two. The scenarios are my own simulation, so this says little about real clusters.

Two detector problems found while building this: an idle GPU raised false alerts (relative-drop rule on a near-zero baseline; fixed with a minimum-baseline rule), and a 75 s utilization dip could straddle windows. The detector ignores dips shorter than two 60 s windows by design, and the decoy was shortened to 45 s to match that rule.

### Observations about Token Factory (real, from the benchmark runs)
- On `Nemotron-3_5-Lightning`, a prompt growing from about 200 to 3.7k input tokens barely changed latency (about 0.45 s to 0.48 s). It took roughly 28k to 56k tokens to see a clear increase. Prompt bloat is a slow-burn problem on this endpoint, not a sharp one.
- Lightning emits visible reasoning text in the response content, which counts against `max_tokens`.
- The API returns opaque tool-call ids (`chatcmpl-tool-...`); the model cited tool names instead until I gave calls short ids.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repo> && cd clusterdoctor
uv sync
cp .env.example .env      # then set NEBIUS_API_KEY in .env
uv run pytest -q          # 13 tests, no API calls
```

Run commands with `PYTHONPATH=src` (the editable install is skipped on macOS when the `.pth` file is flagged hidden, so this is the reliable way):

```bash
# one live end-to-end incident: baseline traffic -> fault -> watcher -> Nemotron investigation
PYTHONPATH=src uv run python scripts/run_demo.py prompt_bloat 25 40

# simulated GPU incident
PYTHONPATH=src uv run python scripts/run_gpu_demo.py thermal_throttle

# benchmarks (cost real credits; start with the free dry run for the fleet)
PYTHONPATH=src uv run python scripts/bench_fleet.py --dry 3
PYTHONPATH=src uv run python scripts/bench_generate.py 3   # live traffic, writes bench/cases/*.db (git-ignored)
PYTHONPATH=src uv run python scripts/bench_eval.py
```

`bench/manifest.json` points to case databases that are not committed; regenerate them with `bench_generate.py`.

## Dashboard

Eight stored incidents (5 inference with live Token Factory traffic, 3 simulated GPU) are replayed from `data/replays/` with no API spend. Each shows what the watcher saw (latency chart or 64-GPU heatmap), the investigation step by step, and the report with evidence citations, rejected hypotheses and the check results. "Reveal injected fault" shows the ground truth next to the diagnosis, including where the agent was wrong. "Run live" re-runs an investigation on Token Factory and is off unless enabled:

```bash
cd web && npm install && npm run build && cd ..          # build the UI once
PYTHONPATH=src uv run uvicorn clusterdoctor.api:app --port 8011
# optional, spends credits (about $0.04 per run), capped per server start:
CD_ALLOW_LIVE=1 CD_LIVE_CAP=5 PYTHONPATH=src uv run uvicorn clusterdoctor.api:app --port 8011
```

To rebuild the replays: generate cases with `bench_generate.py`, then `scripts/build_replays.py` (`--dry` skips the model calls).

## Demo plan (3 minutes)

1. A fleet view looks healthy; an AI app is running against Token Factory.
2. A fault is injected. The watcher opens an incident on its own.
3. The investigation runs live: hypotheses are tested and rejected, each claim cites a tool result.
4. The report names the cause; then the injected fault is revealed.
5. A simulated GPU node shows the same symptom (low utilization) with a different cause and a different diagnosis.
6. The results slide, including the single-call baseline that ties the agent, and why that matters.

Still to do: hosting and the video.

## Feedback for Nebius

- A 402 "exhausted your budget" error did not say whether the limit was on the key or the account, which cost time to diagnose.
- See the Token Factory observations above.

## License

MIT
