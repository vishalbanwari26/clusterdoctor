import React from "react";

export default function Intro({ onClose }) {
  return (
    <section className="intro" aria-label="How to read this page">
      <div className="introhead">
        <h2>What is this?</h2>
        <button className="linkbtn" onClick={onClose}>Got it, hide this</button>
      </div>
      <p>
        When an AI service or a GPU slows down, a dashboard shows <em>that</em> something is wrong. ClusterDoctor finds
        out <em>why</em>. A simple check spots the problem, then an AI agent (NVIDIA Nemotron on Nebius Token Factory)
        investigates it and writes a report you can verify.
      </p>
      <ol className="introsteps">
        <li><b>Pick an incident</b> on the left.</li>
        <li><b>See what the watcher saw</b>: the chart or GPU map that triggered it.</li>
        <li><b>Follow the investigation</b>: each step is a question the agent asked the data.</li>
        <li><b>Read the diagnosis</b>, then click <i>Reveal the answer key</i> to see what was really wrong.</li>
      </ol>
      <p className="note">
        These are saved runs of real investigations, so viewing them costs nothing. The five &ldquo;Real traffic&rdquo; incidents
        come from live calls to Token Factory. The GPU incidents use a <b>simulated</b> fleet, because there is no real GPU behind this demo.
      </p>
    </section>
  );
}
