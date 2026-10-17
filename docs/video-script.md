# ClusterDoctor demo video script (target 2:50, hard limit 3:00)

The video must be public on YouTube and show Token Factory and Nemotron actually being used. Record at 1080p, dark mode, browser zoom 110%. Plain sentences. Do not read the page aloud.

## Before recording

- Deploy the Space and check one live run works through the hosted URL (about 15 to 30 seconds, about $0.02).
- Have the Nebius Token Factory console open in a second tab on the usage or request log page.
- Do one live run in advance so you know the timing today. Check how many live runs are left for your IP (shown in the header).
- Open the incident "Prompt bloat after a retrieval change".

## Script

| Time | On screen | Voice-over |
|---|---|---|
| 0:00 to 0:15 | The p95 chart alone, with the spike. | "When an AI service or a GPU slows down, a dashboard shows that something is wrong. It does not say why. Working that out takes an engineer an hour of reading metrics, logs and deploy history." |
| 0:15 to 0:35 | The incident feed: the three groups (real traffic, real GPU data, simulated). | "ClusterDoctor opens an incident on its own, with plain statistics, no model. The traffic here is real calls to Nemotron on Token Factory. Two incidents use real GPU data from a production cluster. The rest of the GPU data is simulated, and the page says so." |
| 0:35 to 0:55 | The chart and the four tiles for prompt bloat. | "Here p95 latency rose from 0.47 to 0.83 seconds, and prompts grew from about 200 tokens to 55,000 after a retrieval change." |
| 0:55 to 1:35 | Click **Run it live**. Steps appear while the timer runs. Cut to the Token Factory console tab for 3 seconds, then back. | "Now live. Code first collects a fixed set of evidence: the two time periods compared, any deploy, retries, and tables that change one factor while holding another fixed. Then one Nemotron 3 Ultra call writes the report, and a second call checks every claim against that evidence. Both are real calls to Token Factory." |
| 1:35 to 2:00 | The answer card, then the full report. Click an evidence chip so it jumps to its step. Show the fact-check line. | "It says prompts got much larger, and every reason points at the evidence it came from. The check found no claim that conflicts. If it had, the model would revise, and if that failed, a tool-using agent takes over. Nothing is ever changed automatically: a person approves any action." |
| 2:00 to 2:25 | The real-data incident (real GPU, memory error). Click **Reveal the answer key** and show the reference chip. | "This one is real GPU data, a driver memory error on a production cluster. There is no human-verified diagnosis for it, only the driver's error code, so the page shows a reference, not a right-or-wrong." |
| 2:25 to 2:50 | One slide with the results table, then the repo and demo URLs. | "I tested whether a tool-using agent diagnoses better than one well-built call, with the tests written down first. It did not: a fair one call matched it at a tenth of the cost, which is why the one-call workflow is the default. The gains came from computing better evidence in code. Every negative result is in the repo, which is MIT licensed." |

## If a live run fails or is slow on the day

- Click **Watch it work** instead. It replays a stored run. Say so on camera: "this is a saved run".
- Do not fake a live run. The console tab only helps if the requests are real.
- If your IP is out of live runs, wait for the daily reset (UTC) or run locally with `CD_ALLOW_LIVE=1`.

## Shots to capture separately

- The model name in the report footer (`nvidia/Nemotron-3-Ultra-550b-a55b`).
- The README section "Where Nemotron and Token Factory are used".
- The README results tables.

## Cut list if over 3:00

1. The results slide (keep the voice-over, show the README table).
2. The console tab switch.
3. The real-data incident.

Keep the live run and the honest result. Those are the two things a viewer will remember.
