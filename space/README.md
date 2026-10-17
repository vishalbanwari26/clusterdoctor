---
title: ClusterDoctor
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
license: mit
short_description: Evidence-checked root-cause reports for AI inference and GPU fleets, on Nemotron
---

# ClusterDoctor

Watchers open an incident when an AI inference app or a GPU fleet degrades. Code gathers a fixed evidence pack, one Nemotron call on Nebius Token Factory
writes the report, and a second call checks every claim against the evidence. A tool-using agent steps in only when that check fails.

Stored investigations replay with no API use. "Run live" re-runs one on Token Factory, limited per visitor
per day. The GPU fleet is simulated and labelled as such.

Source and benchmark results: see the project repository.
