# Pre-registered design: three follow-up tests

Written before any of these tests were run. The scripts record the SHA-256 of this file in their results. Everything run is
reported, including ties and negative results. Limits: credits $3.50 in total (scale test $1.20, simulated expansion $1.00,
real false-alarm test $0.90), 280 MB of downloads, stop on the first API failure.

## Why these tests

The earlier benchmarks showed the agent tied a fair one-shot baseline. Three things were never tested: data too large for one
prompt, the effect of difficulty, and real data where nothing is wrong. All models are Nemotron 3 Ultra on Nebius Token Factory.

## Test 1: scale (data too large for one prompt)

**Fleet:** 32 racks x 8 nodes x 8 GPUs = 2,048 GPUs, 6 hours at 30 s, utilization, temperature and power, simulated.
About 4.4M samples, far beyond any prompt. One fleet holds all 20 cases at different places; other cases' anomalies are
distractors for each case. The anomaly starts at hour 4. The incident text names the flagged GPU and says its utilization fell.

**Families (5 cases each, 20 total).**

| Family | What happens | Truth label |
|---|---|---|
| A isolated GPU thermal | one GPU: temperature +20 C over 10 min, utilization down | `gpu_thermal_isolated` |
| B rack cooling | all 64 GPUs of a rack warm by +15 C over 20 min, the hottest lose utilization | `rack_cooling_failure` |
| C slot position | the GPU at one slot index (0 to 7) on 16 nodes spread over 8 racks runs +18 C hotter and loses utilization | `slot_position_issue` |
| D node-wide stall | all 8 GPUs of one node drop utilization together, temperature falls (a job ended) | `node_wide_stall` |

Answer labels: the four above and `insufficient_evidence`.

**Baseline (one call, no tools).** A generous, fixed dump of at most 12,000 tokens: the flagged GPU's utilization, temperature
and power at 30 s resolution for the 40 minutes around onset, baseline-versus-incident means for it; window means for the 8
GPUs of its node; per-node means for its rack; baseline-versus-incident means for all 32 racks; fleet-wide p1, p50 and p99 of
utilization and temperature. It deliberately does **not** group by slot index: no fixed report can list every dimension.

**Agent.** Tools: `compare_windows`, `series` (a GPU's metric, at most 60 points), `peer_gpus` (its node),
`group_stats` (a metric grouped by node, rack or gpu_index over a window, returning the groups that deviate most from the fleet),
`submit_diagnosis`. At most 14 steps. No claim-verification pass, as in the earlier GPU tests.

**Expectation, stated in advance.** Families A, B and D: the baseline has the information, so a tie. Family C: the evidence is
a slice along an unlisted dimension, so the agent can win only if it slices. Family C is built to test exactly that, and I am
not claiming it represents all incidents.

**Metrics.** Correct per family and pooled; wrong with high confidence; abstentions; cost; tool calls.
**Rule for claiming an edge:** pooled correct at least 4 above the baseline, and family C at least 3 of 5 above it. Otherwise
the result is reported as a tie or a loss.

## Test 2: simulated-fleet expansion (difficulty levels)

The 64-GPU fleet from the earlier test, with three faults per fleet (thermal throttling, data-loader bottleneck, hardware
fault with an Xid), plus the same two decoys. 4 seeds (101 to 104) x 3 levels = 12 fleets = 36 incidents.

| Level | Signature strength | Noise | Missing samples |
|---|---|---|---|
| easy | 1.0 | 1.0x | 0% |
| medium | 0.6 | 1.5x | 5% |
| hard | 0.35 | 2.0x | 15% |

Strength scales the temperature rise, clock drop and utilization drop. The watcher is run first; a missed incident counts as a
detection failure and neither model runs on it. Contestants: the agent with the GPU tools versus the one-shot budgeted dump
(about 3,300 tokens), exactly as in the 64-GPU test. Metrics: detection rate, accuracy and confident-wrong per level, cost.

## Test 3: real job-end false-alarm test

**Data:** real AcmeTrace Kalos windows (CC-BY-4.0). 16 windows already fetched plus up to 16 new ones, each 40 minutes around a
utilization collapse (busy at 80% or more for the 20 minutes before, below 32% for 2 minutes at the anchor) on a GPU with **no Xid
change within 30 minutes** and no elevated temperature. New windows come from a 50 MB slice of the util and Xid files starting
around 2023-08-24 (dense data), at most one per node per 3 hours, none within 1 hour of an existing window. Download cap 280 MB.

**Label.** `no_fault_job_ended`. This is **not verified**: it means no driver error and normal temperature. Nobody confirmed a
job ended.

**Task.** The Xid series is hidden. Answer labels: `thermal_throttling`, `data_loader_bottleneck`, `gpu_hardware_fault`,
`no_fault_job_ended`, `insufficient_evidence`. A false alarm is any of the first three.

**Contestants:** the agent (tools: `compare_windows`, `util_pattern`, `peer_gpus`) versus the one-shot dump of the same tables.
**Metrics:** false-alarm rate, `no_fault_job_ended` rate, abstention rate, cost. With about 32 windows a rate of 0 has a 95%
upper bound near 9%; I report that bound.

## What I will not do

Change these definitions after seeing results, drop a test that turns out badly, or hide a case. Any deviation (for example a
case that fails to generate) is listed in the results with the reason.

## Deviations (added after the fact, with reasons)

- **Scale-test spend cap raised from $1.20 to $1.60.** The first case cost $0.08 for the agent, so 20 cases would cost about $1.6.
  The total budget of $3.50 is unchanged. Cases are now run round-robin across families so a cap cannot truncate one family.
- **Agent loop change.** The first live case crashed because the model passed an invalid `group_by` and my loop did not catch
  the error. Tool argument errors now go back to the model as an error result. This was not triggered by any outcome.
- **Test 2 bug.** The first hard-level case crashed my one-shot dump (it rounded a missing value). Fixed, and the run resumed
  without repeating finished incidents.
- **Case c00 of Test 1** was run before the fix above and is kept as it was: the agent answered `insufficient_evidence` after 8 tool calls.
- **Design hash.** The hash recorded in the Test 1 and Test 2 results (`4db6e820e0c38ec5`) is of this file before this Deviations
  section existed. Test 3 records the hash after the section was added; nothing above the section changed.
- **Family C flaw (found after the run, not fixed in the results).** Five slot issues were active at the same time, so a single hot
  slot differs from the fleet mean by only about 0.5 C. The one-shot also scored 0/5. Family C does not test slicing along an unlisted
  dimension as intended, and its results should not be read as evidence about it.
- **Format failures.** The agent's answers sometimes broke the output format (free text in `root_cause`, evidence as plain strings).
  The evidence check turns those into `insufficient_evidence`. The abstention counts in Test 1 mix real uncertainty with these.
- **Exploratory runs outside the pre-registered results** (about $0.34): two single diagnostic runs (c00, c10) and five re-runs of the family C cases.
- **Spend.** Tests 1, 2 and 3: $1.61, $0.59 and $0.40. Test 1 exceeded its raised cap by $0.01.

## Test 1 v2: corrected scale test (pre-registered before it runs)

**Why.** Test 1 had two problems of my own making: family C was diluted (five slot issues at once), and the agent's answers were
often turned into abstentions by my output checks (free text in `root_cause`, uncited evidence). v2 fixes both and changes nothing else.
The original Test 1 results stand and stay in the repo. Approval for up to $2.00 of additional spend, on top of the earlier $3.50.

**Changes.**
1. **Agent loop.** A `root_cause` outside the allowed labels, or a diagnosis with no valid evidence citation, is sent back to the
   model with the list of allowed labels or of valid `call_` ids, instead of being downgraded at once. Up to 2 retries for labels,
   1 for citations; after that the old fallback to `insufficient_evidence` applies. The number of each retry is recorded.
2. **Family C, clean.** One slot index (3) runs +18 C hotter and loses utilization on 16 nodes spread over 8 racks. The 5 C cases
   are 5 different flagged GPUs among those 16. Nothing else about the slot is happening, so that slot stands out from the fleet
   mean by about +1 C against noise of about 0.1 C.
3. **Cases.** A: 3, B: 3, D: 3 (same generators as before, new random placement), C: 5. Total 14, to fit the budget.

**Unchanged.** The fleet size, the one-shot dump (no slot grouping, about 2,400 tokens), the agent tools, the 14-step limit,
the system prompt, the labels, the model.

**Metrics.** Correct per family and pooled, abstentions, how many answers were rescued by a retry, wrong with high confidence, cost.
**Rule for claiming an edge on slicing:** agent correct on family C at least 3 above the one-shot, and pooled correct no more than 2
below the one-shot. Otherwise reported as a tie or a loss, and a mixed result (edge on C, behind elsewhere) is reported as mixed.
Spend cap $2.00; stop on the first API failure; exploratory runs, if any, are listed separately.

### v2 outcome (added after the run)
Run with design hash `6a0fe958f7bd0bd0` (this file before this paragraph). Agent 1/14, one-shot 8/14; family C 0/5 vs 0/5; the rule for an edge was
not met. Spend $1.22. The agent called `group_stats` in 3 of 5 C cases and still did not name the slot. 11 of 14 answers needed a format retry.
