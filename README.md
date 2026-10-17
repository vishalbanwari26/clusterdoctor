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

### Real GPU data (AcmeTrace Kalos)
Two real incidents from a production GPU cluster, loaded from public data (CC-BY-4.0, see `data/real/README.md` for the attribution and what was changed). Both are the first time the driver reported **Xid 94, a contained memory error** on a GPU, found by searching the dataset's Xid series.

| | What the real telemetry did | Agent's answer (second attempt) |
|---|---|---|
| **A** `172.31.15.203` GPU 3, 2023-08-28 | Utilization fell from 96% to 25% at the Xid. All 8 GPUs on the node dropped together. Temperature fell (idle GPU cooled). | GPU hardware fault, medium confidence. Ruled out overheating (temperature fell) and data loading. |
| **B** `172.31.0.68` GPU 6, 2023-08-18 | No visible change in utilization (about 99%), temperature (about 50 °C) or power. This GPU has no utilization or power data before the event. | GPU hardware fault, medium confidence. Said plainly that the telemetry shows no symptoms and the baseline is missing. |

What to take from this, and what not to:
- There is **no human-verified diagnosis** for these events. The only label is the Xid code, and the agent was given that same code (through an Xid lookup tool that holds only the four catalog entries I verified: 31, 43, 45, 94). Agreement with the Xid-derived reference is not independent validation, so the dashboard shows the reference without a match/miss verdict.
- **A one-shot baseline ties the agent on both events.** One call given every table the agent could have queried (windows, throttle and Xid state, utilization pattern, peers, and the Xid catalog entry) answered `gpu_hardware_fault` in 6 of 6 runs (medium confidence, once high), for $0.002 to $0.009 per call against $0.019 to $0.034 for the agent. With the Xid code and the catalog in hand the question is easy, which is also why agreement with the Xid-derived reference proves little. Results: `bench/results_real_baseline.json`.
- Two events cannot measure accuracy. This is a demonstration that the pipeline copes with real, gappy data.
- **The first attempt failed for reasons in my own pipeline.** Event A hit the 10-step budget while re-checking missing data and ended as `insufficient_evidence` without concluding. Event B's prompt said a monitor had flagged "low utilization", but the incident was opened by an Xid change, and the agent reasoned from that wrong premise. I fixed the prompt, raised the step budget to 16 for real runs, and re-ran. The first-attempt outputs are kept in `data/replays_attempts/`.
- One stretch in A: the agent says the Xid "preceded" the stall. The data only shows them in the same 15-second sample.
- Real data forced two watcher changes: it now treats missing windows as unknown and skips GPUs with no baseline, and a new Xid watcher opens an incident when the (sticky) Xid value *changes*. Event B cannot be seen by a utilization watcher at all.
- Facts about this dataset worth knowing: the Xid field keeps the last code, so a nonzero value is not an event; rows are sparse early in the file and dense later; column order differs between files; across the 15 days probed, Xid 43 (application error) and 31 (memory page fault) dominate (about 93% of the GPUs showing a code carry 43).

### Follow-up tests (pre-registered in `docs/preregistered-tests.md`)
Run after the benchmarks above, with the design written first. All numbers come from `bench/results_sim_levels.json`, `bench/results_scale.json` and `bench/results_false_alarm.json`. Total spend about $4.16 ($3.50 cap, then up to $2.00 more approved for the v2 re-run). The agent did **not** win any of them.

**Test 2, simulated fleet with difficulty levels** (4 seeds x 3 levels = 36 incidents; the models only run on incidents the watchers detect):

| Level | Detected | Agent | One-shot |
|---|---|---|---|
| easy | 12 / 12 | 12 / 12 | 12 / 12 |
| medium (signal 0.6x, noise 1.5x, 5% missing) | 8 / 12 | 7 / 8 (one confidently wrong) | 8 / 8 |
| hard (signal 0.35x, noise 2x, 15% missing) | 4 / 12 | 4 / 4 | 4 / 4 |

The finding is detection: the watchers catch every fault at easy level, two thirds at medium and a third at hard, and at hard level only the hardware fault is caught, because its Xid stays visible. Diagnosis stays easy after a fault is caught; catching it is what breaks first.

**Test 1, scale (2,048 simulated GPUs, 4.4M samples, 20 cases):** the one-shot gets a fixed dump of about 2,400 tokens; the agent gets tools including `group_stats` over the whole fleet.

| Family | Agent | One-shot |
|---|---|---|
| A isolated GPU thermal | 2 / 5 | 5 / 5 |
| B rack cooling | 0 / 5 | 5 / 5 |
| C slot position | 0 / 5 | 0 / 5 |
| D node-wide stall | 3 / 5 | 5 / 5 |
| **Pooled** | **5 / 20** | **15 / 20** |

The pre-registered rule for claiming an edge was not met; the agent lost. What I found when I looked into why, and what limits this result:
- **Format failures counted as abstentions.** The agent abstained on 13 of 20 cases. In follow-up diagnostics, some of those were submissions where `root_cause` was a free-text paragraph instead of one of the allowed labels, or where evidence was not cited correctly, and my evidence check turned them into `insufficient_evidence`. The saved results do not record the original answers, so I cannot say how many.
- **Run-to-run noise.** Case c00 abstained in the pre-registered run and was correct, with 4 tool calls, in a later diagnostic.
- **Family C was badly designed by me.** Five slot issues were active at once, so no single slot stood out from the fleet mean by more than about 0.5 C, and the one-shot also scored 0/5. In 3 of 5 exploratory re-runs the agent did slice by slot and still answered "isolated GPU". Whether the agent can find a slot-level cause when the signal is clean is untested.
- **The one-shot dump was small** (about 2,400 of a 12,000-token allowance), and it had the information for families A, B and D.
- Four of my own bugs interrupted the run (an invalid argument, a missing field, evidence given as plain strings, and a rounding of a missing value). They were fixed in the agent loop, listed under "Deviations" in the design doc, and finished cases were never repeated.

**Test 1 v2, corrected scale test** (pre-registered, `bench/results_scale_v2.json`, spend $1.22). I fixed the two flaws above: a clean family C (one slot index, +0.94 C from the fleet mean, three times any other slot) and a retry when the answer uses a label outside the allowed set or cites no evidence. Same fleet size, one-shot dump, tools, prompt and model.

| Family | Agent | One-shot |
|---|---|---|
| A isolated GPU | 1 / 3 | 3 / 3 |
| B rack cooling | 0 / 3 | 2 / 3 |
| **C slot position (clean)** | **0 / 5** | **0 / 5** |
| D node-wide stall | 0 / 3 | 3 / 3 |
| **Pooled** | **1 / 14** | **8 / 14** |

The rule for claiming an edge on slicing was not met. The agent called `group_stats` in 3 of the 5 slot cases and still answered "isolated GPU" or abstained, so the problem is using the evidence, not having the tool. Eleven of 14 answers needed a retry for format, and it often wrote confidence as a number (0.85 to 0.95) instead of high, medium or low. Limits: one model, one prompt, one tool set; a different model or a prompt that forces slicing first might do better, and I did not test that.

**Test 3, real job-end windows** (31 real Kalos windows with a utilization collapse, no Xid within 30 minutes and normal temperature; the Xid is hidden; one window was excluded for missing temperature data): the label is "no fault", which is unverified. A model that names a fault is raising a false alarm.

| | One-shot | Agent |
|---|---|---|
| Named a fault | 8 / 31 (26%) | 9 / 31 (29%) |
| Said "no fault" | 22 | 20 |
| Abstained | 1 | 2 |

Every false alarm was `data_loader_bottleneck`, mostly on the same windows. Several of those windows dip only partway (for example 90% to 77%), so some may be real mild stalls and not false alarms at all.

**What these tests support:** a fair one-shot call matches or beats the agent in everything I tested at these data sizes, detection is the weak link as signals get weaker, and models raise a fault on roughly a quarter of ordinary-looking collapses. They do not show whether an agent helps on larger, messier real incidents, and they are mostly simulated.

### Hidden-Xid test: can telemetry alone see a driver error? (real data, negative result)
I streamed the whole Kalos Xid and utilization files once (1.6 GB, nothing stored) to find real events with real labels. **The dataset holds only 50 true Xid changes in 15.5 days** (35 x Xid 43, 11 x 31, 3 x 45, 1 x 94), and only 5 passed a "busy before, data after" filter. In the same file **48,811 utilization collapses** pass the same kind of filter, so a collapse that coincides with a driver error is about 4 in 48,811: almost every collapse is a normal job ending.

I then hid the Xid series and asked the one-shot baseline and the agent, on 20 real windows (3 collapses with an Xid, 1 Xid without a collapse, 16 normal job-end collapses), whether the driver reported an Xid on that GPU. Neither ever said yes (0 of 20). Both missed all 4 real driver errors. On the 4 positives the baseline said "no driver error" with high confidence twice, while the agent abstained on 3, but that is 4 cases and I do not read it as a result. On the 16 normal job ends the baseline said "no error" 13 times and the agent 10 (it abstained 6 times against 3). Spend $0.26.

Reading: utilization, temperature and power cannot reveal a driver error, and the models correctly defaulted to the base rate. That is why the Xid watcher exists. n = 4 positives, so nothing here supports a claim about the models' accuracy. Windows are in `data/real/hidden_xid_cases.json`, results in `bench/results_hidden_xid.json`, and the scripts are `kalos_scan.py`, `kalos_fetch_windows.py` and `hidden_xid_test.py`.

### Real LLM traffic shapes (Azure traces, profiled only)
I downloaded the Azure LLM inference traces (conversation and code, 2023, CC-BY, Patel et al., *Splitwise*, ISCA 2024) and profiled them but have **not** used them to drive the benchmarks. They show real median prompts of about 1,000 to 1,500 tokens (p95 4,000 to 7,300) and 5.5 requests per second with bursts. My synthetic baseline traffic used 213-token prompts, so the benchmark's absolute numbers are not production-like, and the 55,000-token "prompt bloat" is far outside real traffic. The conclusions about which causes the agent can separate do not depend on those sizes, but the absolute latencies do.

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

Eight stored incidents (5 inference with live Token Factory traffic, 3 simulated GPU) are replayed from `data/replays/` with no API spend. The page is written for someone seeing it for the first time: an intro explains what it is, each incident has a plain-words summary, the AI's answer comes first with a plain explanation of the cause, and jargon (p95, stratified, Xid) has hover definitions. Below that: what the watcher saw (latency chart or 64-GPU heatmap), the investigation as a list of questions the agent asked the data with readable result tables, and the full report with evidence, ruled-out causes and a fact-check summary. **Watch it work** replays a saved run step by step. **Run it live** asks Nemotron again. **Reveal the answer key** shows what was injected next to the diagnosis, including where the agent was wrong.

```bash
cd web && npm install && npm run build && cd ..          # build the UI once
PYTHONPATH=src uv run uvicorn clusterdoctor.api:app --port 8011
# optional: enable live runs (about $0.04 each). Needs NEBIUS_API_KEY in .env
CD_ALLOW_LIVE=1 PYTHONPATH=src uv run uvicorn clusterdoctor.api:app --port 8011
```

To rebuild the replays: generate cases with `bench_generate.py`, then `scripts/build_replays.py` (`--dry` skips the model calls).

## Live URL on a Hugging Face Space

The same app runs as a Docker Space: replays are free and unlimited, and "Run live" calls Token Factory.

1. Create a Space at huggingface.co/new-space (SDK: Docker, blank template).
2. In the Space settings add a **secret** named `NEBIUS_API_KEY`. Never put the key in git or the image.
3. Deploy: `scripts/deploy_space.sh <hf-username>/<space-name>` (git asks for a Hugging Face write token as the password).
4. **In the Nebius console, set a spending limit on that API key.** This is the real hard cap.

Live runs are limited per visitor (default 2/day, by IP) and per day for the whole server (default 20), with at most 2 running at once; each run costs about $0.02 to $0.06 and takes about a minute. Change the limits with `CD_LIVE_PER_IP`, `CD_LIVE_DAILY_CAP` and `CD_LIVE_MAX_CONCURRENT`. The counters live in memory, so a restart resets them; that is why the key's own spending limit matters. Without the secret the Space still serves replays and the live button stays off. Free Spaces may sleep when idle, so the first visit can be slow.

## Demo plan (3 minutes)

1. A fleet view looks healthy; an AI app is running against Token Factory.
2. A fault is injected. The watcher opens an incident on its own.
3. The investigation runs live: hypotheses are tested and rejected, each claim cites a tool result.
4. The report names the cause; then the injected fault is revealed.
5. A simulated GPU node shows the same symptom (low utilization) with a different cause and a different diagnosis.
6. The results slide, including the single-call baseline that ties the agent, and why that matters.

Still to do: deploy the Space and record the video.

## Feedback for Nebius

- A 402 "exhausted your budget" error did not say whether the limit was on the key or the account, which cost time to diagnose.
- See the Token Factory observations above.
- **Structured output compliance.** In the scale test, Nemotron 3 Ultra needed a format retry on 11 of 14 answers (free text in an enum field, missing required fields, numeric confidence where a three-value enum was specified). Enforced tool-call schemas or guided decoding on Token Factory would remove that failure mode.

## License

MIT
