# ClusterDoctor demo video script (target 2:50, hard limit 3:00)

The video must be public on YouTube and show Token Factory and Nemotron actually being used. Record the screen at 1080p, dark mode, browser zoom 110%. Voice-over in plain sentences. Do not read the on-screen text aloud word for word.

## Before recording

- Deploy the Space and check the live button works (one real run through the hosted URL).
- Have the Nebius Token Factory console open in a second tab, on the usage or request log page.
- Have the Space URL open on the "Prompt bloat after a retrieval change" incident.
- Do one live run in advance, so you know how long it takes today (stored runs took 18 to 67 s). Choose the live incident by that time.
- Check how many live runs are left for your IP (the header shows it). You need at least one.

## Script

| Time | On screen | Voice-over |
|---|---|---|
| 0:00 to 0:15 | Grafana-style screenshot, or the p95 chart alone, with the spike. | "When an AI service slows down, the dashboard shows a spike. It doesn't say why. Finding out takes an engineer an hour of reading metrics, logs and deploy history. I ran into this on a GPU cluster during my thesis." |
| 0:15 to 0:35 | Dashboard, incident feed visible. Point at the two groups: real Token Factory traffic, simulated GPU fleet. | "ClusterDoctor watches telemetry and opens an incident on its own. A statistical watcher does that, no model involved. The model only runs once there is an incident. These five incidents are real calls to Nemotron on Token Factory. The GPU ones are simulated, and the page says so." |
| 0:35 to 0:55 | Open "Prompt bloat". Show the chart: baseline line, deploy marker, latency rising. Show the four tiles. | "Here the p95 latency went from 0.47 to 0.83 seconds. Prompts grew from about 200 tokens to 55,000 after a retrieval change. That is the symptom. Now the investigation." |
| 0:55 to 1:45 | Click **Run it live**. Confirm. The step list fills in while the timer runs. Switch to the Token Factory console tab for 3 seconds to show the requests arriving, then back. | "I'll run it live. This is Nemotron 3 Ultra on Token Factory. It picks a tool, reads the result, and decides what to check next. It compares the two time windows, reads the deploy event, and splits latency by prompt size, retries and concurrency. It has to test its top two hypotheses before it may answer. Each of these steps is a real model call." |
| 1:45 to 2:10 | The verdict card, then the full report. Click an evidence chip so it jumps to the tool call. Show "Rejected hypotheses". | "It says prompts got much larger, and it shows why: every claim points to the tool result it came from. It also lists what it ruled out and what it is still unsure about. A second pass checks each claim against the data, and the agent has to fix any that conflict. It never changes anything. A person approves the actions." |
| 2:10 to 2:30 | Open "Deploy event points at the wrong change". Click **Reveal the answer key**. The red mismatch chip shows. | "It does get things wrong. In this case a deploy note pointed at prompt size, and the real cause was too many concurrent requests. The agent followed the note. I left this in on purpose." |
| 2:30 to 2:50 | One simple slide: the benchmark table (12, 15, 16, 21, 21 out of 24) and one line of text. Then the repo and Space URLs. | "On 24 hard cases, a one-shot summary got 12 right. The agent got 21 after I added stratified comparisons and claim checks. The part to be honest about: a single call given the same tables also got 21, for a sixth of the cost. What helped was the evidence, and the agent adds an audit trail. Code is MIT licensed on GitHub, and you can try it at the link." |

## If a live run fails or is slow on the day

- Click **Watch it work** instead. It replays a stored run step by step. Say so on camera: "this is a saved run".
- Do not fake a live run. The Token Factory console tab only helps if the requests are real.
- If you run out of live runs for your IP, wait for the daily reset (UTC) or run it locally with `CD_ALLOW_LIVE=1`.

## Shots to capture separately

- The model name in the report footer (`nvidia/Nemotron-3-Ultra-550b-a55b`), for judges who skim.
- The README section "Where Nemotron and Token Factory are used".
- The README results table.

## Cut list if you are over 3:00

1. The slide at 2:30 (keep the voice-over, show the README table instead).
2. The Token Factory console tab switch.
3. The "rejected hypotheses" part.

Keep the live run and the wrong answer. Those are the two things a viewer will remember.
