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
        out <em>why</em>. A simple check spots the problem, code gathers a fixed set of evidence, one NVIDIA Nemotron call (on Nebius Token Factory)
        writes the report, and a second call checks every claim against that evidence. A tool-using agent steps in only if that check fails.
      </p>
      <ol className="introsteps">
        <li><b>Pick an incident</b> on the left.</li>
        <li><b>See what the watcher saw</b>: the chart or GPU map that triggered it.</li>
        <li><b>Follow the report being built</b>: each step is a piece of evidence the code collected before the AI wrote anything.</li>
        <li><b>Read the diagnosis</b>, then click <i>Reveal the answer key</i> to see what was really wrong.</li>
      </ol>
      <p className="note">
        These are saved runs of real investigations, so viewing them costs nothing. The &ldquo;Real traffic&rdquo; incidents
        come from live calls to Token Factory. The &ldquo;Real GPU data&rdquo; incidents use telemetry recorded on a production GPU cluster
        (AcmeTrace, CC-BY-4.0); no one verified a diagnosis for them, so they come with a reference label, not an answer key. The &ldquo;Simulated&rdquo;
        GPU incidents are generated, because there is no GPU behind this demo.
      </p>
    </section>
  );
}
