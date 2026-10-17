---
title: ClusterDoctor
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
license: mit
short_description: Agentic root-cause analysis for AI inference and GPU fleets, on Nemotron
---

# ClusterDoctor

Watches telemetry from an AI inference app and a GPU fleet, opens an incident when something degrades,
and investigates the root cause with Nemotron on Nebius Token Factory.

Stored investigations replay with no API use. "Run live" re-runs one on Token Factory, limited per visitor
per day. The GPU fleet is simulated and labelled as such.

Source and benchmark results: see the project repository.
