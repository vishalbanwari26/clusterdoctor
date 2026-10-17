# ClusterDoctor: Devpost submission text

Fill the bracketed items before submitting: `[SPACE URL]`, `[VIDEO URL]`. Everything else is ready to paste.

- **Track:** Best Apps and Agents
- **Repo:** https://github.com/vishalbanwari26/clusterdoctor (MIT license)
- **Demo:** [SPACE URL]
- **Video:** [VIDEO URL]

---

## Tagline

Watchers catch it, code gathers the evidence, Nemotron writes the report, and a second call checks every claim.

## Short description

ClusterDoctor watches an AI inference app and a GPU fleet. When something degrades it builds a fixed evidence pack, has NVIDIA Nemotron on Nebius Token Factory write the report, and checks every claim in it against the evidence. A tool-using agent steps in only when that check fails. I tested whether the agent diagnoses better than one well-built call; it did not, so the one-call workflow is the default.

## Inspiration

During my master's thesis at DFKI I trained models on a shared GPU cluster and watched it in Grafana. Sometimes a GPU misbehaved. The dashboard showed that utilization was low. It did not show why. Finding out meant reading metrics, logs, job configs and scheduler output by hand.

Monitoring tells you what is happening. The first hour of an incident is spent working out why. I wanted to see how much of that first pass a model could do, and how often it would be confidently wrong.

## What it does

1. **Watchers** (statistics, no model). A latency watcher (p95 above 1.5 times baseline), a GPU utilization watcher, a z-score watcher that catches weak but consistent shifts in utilization or temperature (18 of 18 simulated incidents on unseen seeds with no false alerts, against 12 of 18 before), and an Xid watcher that fires when the driver's error code changes.
2. **An evidence pack** (code, no model). Window comparisons, deploy events, retries, stratified latency tables that change one factor while holding another fixed, and an **effect split** that says which factor explains the slowdown using only variation inside the incident window, and which factors cannot be told apart. For GPUs: throttle and Xid state, utilization pattern, host CPU, peers, and NVIDIA's Xid catalog.
3. **One report call and a claim check.** Nemotron 3 Ultra writes the report under a strict JSON schema, so labels and citations cannot be free text. A second call tests every factual claim against the pack, with one revision.
4. **Escalation.** If the answer abstains, has low confidence or still fails the check, a tool-using agent takes over. This path was rarely needed in my runs.

The dashboard shows what the watcher saw, the evidence the code collected, and the report. A "Reveal the answer key" button shows the ground truth beside the diagnosis, including where the system was wrong. ClusterDoctor never changes infrastructure. It recommends actions and a person approves them.

## How we built it

- **Inference app under test:** real calls to `nvidia/Nemotron-3_5-Lightning` on Token Factory. All latency, time to first token, token counts and retry data in the benchmarks come from those calls.
- **Report, claim check and the escalation agent:** `nvidia/Nemotron-3-Ultra-550b-a55b` on Token Factory, through the OpenAI-compatible API (strict JSON schema for the report, tool calling for the agent).
- **Backend:** Python and FastAPI, SQLite for telemetry.
- **Frontend:** React and Vite, dark mode, hand-drawn SVG charts.
- **Hosting:** a Docker Space. Stored investigations replay with no API use, and "Run live" calls Token Factory with per-visitor and daily limits.

### What is real and what is simulated

I do not have a GPU, so I was careful about this.

- Token Factory telemetry: real.
- The retry-storm 429s and the provider-slowdown delay: injected on the client, and labeled `live_injected`. Retry and backoff behavior on top of them is real.
- Two GPU incidents use **real telemetry** from a production cluster: the public AcmeTrace Kalos traces (CC-BY-4.0, see "Data and attribution"). The dashboard labels them as real data.
- All other GPU telemetry is **simulated**. The metric names follow NVIDIA DCGM exporter, but the series are generated, each fault has a signature I wrote, and the dashboard marks every such view as simulated. Results on it show that the pipeline works. They do not show accuracy on a real cluster.

## Nemotron and Token Factory use

- Every report is live Token Factory calls to Nemotron 3 Ultra: the report and the claim check, plus tool calls on the rare escalation.
- The workload being diagnosed runs on Nemotron 3.5 Lightning through the same API, which keeps the demo cheap and gives the investigator real telemetry from the platform it runs on.
- Using two models for two jobs kept cost down. A workflow report costs about $0.02 and takes 15 to 30 seconds; an escalation to the agent costs $0.07 to $0.13.
- Token Factory's streaming usage field gave exact input and output token counts for every request, which the analysis depends on.

## Results

All numbers come from `bench/results_*.json` in the repo. The cases are small, three repeats per fault, so a difference of one or two cases is noise.

Detection: all 21 injected latency incidents were detected, with no false alerts on 3 healthy runs.

**Hard Token Factory cases** (24 evaluations where a one-shot dashboard summary can mislead: two overlapping changes, a misleading deploy event, bloat in a subset of requests, a provider-side slowdown):

| | Correct | Wrong with high confidence | Cost per case |
|---|---|---|---|
| One call, dashboard summary | 12 / 24 | 11 | $0.003 |
| Agent with tools | 15 / 24 | 9 | $0.016 |
| + claim verification | 16 / 24 | 8 | $0.024 |
| + stratified hypothesis tests | 21 / 24 | 2 | $0.038 |
| One call given the same stratified tables | 21 / 24 | 2 | $0.006 |

The big gain came from giving the model the right evidence: stratified comparisons that separate confounded factors. A single call given those tables ties the agent at about a sixth of the cost. I do not claim an agent beats a single call on these cases. The agent's value here is the audit trail: every claim cites a tool result and is checked against it.

**Simulated GPU fleet** (64 GPUs, 179,200 samples, three different faults plus two decoys, 9 incidents): the agent got 9 of 9 and a one-shot aggregate dump got 8 of 9. The scenarios are my own simulation.

**Real GPU data (2 incidents):** I searched the public AcmeTrace Kalos traces for the first time a GPU reported Xid 94 (a contained memory error), and found two. In one, utilization fell from 96% to 25% and all 8 GPUs on the node stalled together. In the other, nothing in utilization, temperature or power changed at all. The agent answered "GPU hardware fault, medium confidence" for both, and said plainly where the data was missing. There is no human-verified diagnosis for these events. The only label is the Xid code, which the agent also saw, so this is a demonstration that the pipeline copes with real, gappy data, not a measure of accuracy. A one-shot baseline given the same tables gave the same answer in 6 of 6 runs at a fraction of the cost, so the agent has no accuracy edge here either. My first attempt on these failed for reasons in my own pipeline (a step budget that ran out, and a prompt that wrongly said a utilization monitor had fired), so I fixed those and re-ran. Both attempts are in the repo.

**Stored dashboard investigations (simulated GPU and Token Factory):** 7 of 8 matched the injected fault. The miss is the "misleading deploy event" case, where the agent diagnosed prompt expansion and the truth was client concurrency. Its own evidence called concurrency "a significant amplifier", so it contradicted its conclusion. I left it in the demo.

**Improving the workflow (Test 5, pre-registered, $0.99 of a $1.00 cap).** Computing an effect split in code and enforcing a strict schema took the one-call arm from 21 to 23 of 24 on the Token Factory cases (16/16 vs 14/16 on dev, but 7/8 vs 7/8 on the weak hold-out, and two things changed at once). A majority of three samples kept 23/24 and removed the one confident wrong answer. The fleet-scale part did not complete: strict-schema decoding degenerated into endless whitespace on the longer prompts (5 of 6 held-out calls), and a token-cap mistake of mine wasted $0.28 before I noticed. Ten dashboard incidents were rebuilt with the workflow at about $0.019 each: a demonstration, not a test.

## Challenges

- **The first benchmark was too easy.** On single-fault cases a one-line summary was enough, and a plain baseline scored the same as the agent. I built harder cases and found where both failed: confounded changes and a misleading deploy event.
- **My validator checked the wrong thing.** The first citation check only confirmed that a cited tool call existed. The agent still wrote a claim that contradicted the result it cited. That led to the claim-verification pass.
- **A fix I designed after seeing failures.** The stratified tool was added after the agent failed on these exact cases, and its factors match what I varied in the faults. It shows the method works on these fault families. It does not show it generalizes.
- **Detector bugs found in a free dry run.** An idle GPU raised false alerts because a tiny baseline makes noise look like a large drop. I fixed it with a minimum-baseline rule.
- **Prompt bloat is slow-burn on this endpoint.** Growing the prompt from about 200 to 3,700 tokens barely changed latency. It took 28,000 to 56,000 tokens to show a clear effect, so the fault had to be much larger than I first assumed.

## What we learned

- Evidence design matters more than the agent loop. Stratified tables lifted accuracy from 12 to 21 of 24, and a computed effect split plus a strict schema reached 23 of 24, whether or not an agent fetched anything. That is why the one-call workflow is the default.
- Strict-schema decoding is useful and fragile: it removes format errors, but on long prompts it can degenerate into whitespace, so it needs a token cap and a fallback.
- Models anchor on the most visible change. In the confounded cases both the agent and the baseline blamed the 17x jump in input tokens.
- Citing a tool call is not the same as being right about it. 4 to 7% of claims in first-pass reports contradicted or went beyond the data.
- Abstaining is a feature. One case ended as `insufficient_evidence` with low confidence, which is better than a confident wrong answer.

## What changed during the submission period

ClusterDoctor is a new repository, and all its code was written during the submission period. Its first commit is dated 2026-10-17. It grew out of an earlier project of mine, Grid Co-Pilot, which does evidence-first root-cause analysis on electrical grid telemetry. ClusterDoctor reuses that idea and shares no code with it.

**Can telemetry alone see a driver error? No.** I scanned the full Kalos Xid and utilization files (1.6 GB, streamed) for real labels. The dataset holds only 50 true Xid changes in 15.5 days, while 48,811 utilization collapses pass the same filter, so a collapse that coincides with a driver error is about 4 in 48,811. With the Xid hidden, neither a one-shot baseline nor the agent ever said "driver error" on 20 real windows, and both missed all 4 real driver errors. They defaulted to the base rate, which is right but cannot detect anything. This is why ClusterDoctor has an Xid watcher. With only 4 positives it says nothing about model accuracy.

**Follow-up tests, designed in advance (`docs/preregistered-tests.md`): the agent did not win any.** On a 2,048-GPU simulated fleet with a one-shot dump of about 2,400 tokens, the agent got 5 of 20 and the one-shot 15 of 20. Many agent abstentions were its own format failures that my evidence check converted, one of the four families was badly designed by me (five slot issues at once, so the signal was diluted and both scored 0 of 5), and results varied from run to run. Across three difficulty levels on the 64-GPU fleet the watchers detected every fault at easy level, two thirds at medium and a third at hard, while diagnosis stayed easy once a fault was caught. On 31 real windows where nothing was wrong (no Xid, normal temperature), the one-shot named a fault in 8 and the agent in 9, always a data-loader bottleneck, with an unverified "no fault" label. Total spend $2.94.

## Data and attribution

- **AcmeTrace** (Kalos cluster utilization traces), Shanghai AI Laboratory, CC-BY-4.0, https://huggingface.co/datasets/Qinghao/AcmeTrace. Paper: Qinghao Hu et al., *Characterization of Large Language Model Development in the Datacenter*, NSDI '24, arXiv:2403.07648. I used a subset (two 3-hour windows, 8 GPUs each, utilization, temperature, power and the Xid code) converted to JSON. Raw files are not in the repo. Details in `data/real/README.md`.
- **Azure LLM inference traces** (2023, CC-BY, Patel et al., *Splitwise*, ISCA 2024): profiled only, not used to drive the benchmarks. They show real median prompts of 1,000 to 1,500 tokens, much larger than my synthetic 213-token baseline, so my absolute latencies are not production-like.
- **NVIDIA Xid catalog** (https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html): the meanings of Xid 31, 43, 45 and 94 in the agent's lookup tool.
- Not used: the OLCF Summit GPU fault dataset, because its page reserves all rights.

## What's next

- More real incidents with independent labels. Public traces give Xid codes but no verified root causes, so I could only demonstrate, not score.
- Write incident cases independently of the tool design, to check whether the stratified method generalizes.
- Test other models, or a prompt that forces slicing first, on the scale test. A clean slot family and format retries did not rescue this model.
- Hooks for a person to approve a recommended action.

## Feedback for Nebius and NVIDIA

### Token Factory

1. **The 402 error does not say which budget ran out.** My runs failed with "Payment Required: You have exhausted your budget." It was not clear whether that meant the account balance or a limit on the API key. Naming the budget and showing the remaining amount in the error would save time.
2. **Model IDs use inconsistent naming.** The Nemotron models I saw are `nvidia/Nemotron-3-Ultra-550b-a55b`, `nvidia/Nemotron-3_5-Lightning`, `nvidia/nemotron-3-super-120b-a12b` and `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`. Case, hyphens and underscores all vary. It is easy to mistype an ID.
3. **Lightning returns visible reasoning in the response content.** A short answer began with a "thinking process" preamble, and that text counts against `max_tokens`. A separate reasoning field, or a way to turn it off, would help latency-sensitive uses.
4. **Server-side timing would turn a guess into evidence.** My telemetry came from client timers and the token counts in the streaming usage field, which worked well. I did not use any server-side timing such as queue time or time in prefill. If the API exposes it, documenting it would help. If it does not, adding it would let an application separate provider time from its own time, so "the provider is slow" can be an observation and not a leftover explanation.
5. **Prompt size and latency.** On Lightning, latency barely moved from 200 to 3,700 input tokens and roughly doubled around 28,000. A short guide to how latency scales with context on each model would help people plan.

### NVIDIA models

- **Structured output compliance was the weakest point.** In the scale test, 11 of 14 Nemotron 3 Ultra answers needed a format retry: free text in an enum field, missing required fields, numeric confidence where high, medium or low was specified. Token Factory enforcing the tool schema, or guided decoding, would remove that failure mode.

- Nemotron 3 Ultra followed the tool-calling protocol reliably over the OpenAI-compatible API, including a custom `submit_diagnosis` tool with a strict schema. It followed a two-hypothesis testing protocol when told to.
- Failure modes I measured: it anchors on the most visible change in confounded cases, and 4 to 7% of its first-pass claims misstated or went beyond the tool data. A second verification call fixed most of those.
- It abstained appropriately on thin evidence once the schema had an `insufficient_evidence` option.

## Built with

Nebius Token Factory, NVIDIA Nemotron 3 Ultra, NVIDIA Nemotron 3.5 Lightning, Python, FastAPI, SQLite, React, Vite, Docker, Hugging Face Spaces.
