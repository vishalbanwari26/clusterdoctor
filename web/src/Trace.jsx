import React, { useEffect, useRef } from "react";
import ResultView from "./ResultView.jsx";
import Term from "./Term.jsx";
import { causeLabel, causePlain, toolTitle, toolWhy } from "./glossary.js";
import { fmt } from "./util.js";

const shorten = (s, n = 170) => (s.length > n ? s.slice(0, n).replace(/\s+\S*$/, "") + "…" : s);

function Step({ n, step, active, cited }) {
  const ref = useRef(null);
  useEffect(() => { if (active && ref.current) ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [active]);
  return (
    <li ref={ref} id={"step-" + step.id} className={"step" + (active ? " active" : "")}>
      <div className="stephead">
        <span className="stepnum">{n}</span>
        <span className="steptitle">{toolTitle(step.tool, step.args)}</span>
        {cited > 0 && <span className="chip cited" title="The report cites this step as evidence">used as evidence {cited}x</span>}
        <span className="callid" title={`Technical name: ${step.tool}`}>{step.id}</span>
      </div>
      {toolWhy(step.tool) && <div className="why">{toolWhy(step.tool)}</div>}
      <details>
        <summary>What it found</summary>
        <ResultView data={step.result} />
        <details className="raw"><summary>Raw data</summary><pre>{JSON.stringify(step.result, null, 2)}</pre></details>
      </details>
    </li>
  );
}

export function Confidence({ level }) {
  const icon = { high: "●●●", medium: "●●○", low: "●○○" }[level] || "";
  return <span className={"conf " + level}><span aria-hidden>{icon}</span> <Term k="confidence">{level} confidence</Term></span>;
}

export function Verdict({ inv, truth }) {
  const d = inv.diagnosis;
  const top = d.evidence.slice(0, 2);
  return (
    <section className="verdictcard" aria-label="Answer">
      <div className="vkicker">The AI's answer</div>
      <div className="vmain">
        <span className={"cause" + (d.root_cause === "insufficient_evidence" ? " abstain" : "")}>{causeLabel(d.root_cause)}</span>
        <Confidence level={d.confidence} />
        {truth && (
          <span className={"truthchip " + (truth.root_cause === d.root_cause ? "match" : "miss")}>
            {truth.root_cause === d.root_cause ? "✔ Matches what was injected" : "✖ Wrong. What was injected: " + causeLabel(truth.root_cause)}
          </span>
        )}
      </div>
      <p className="vplain">{causePlain(d.root_cause)}</p>
      {top.length > 0 && (<>
        <div className="vkicker">Main reasons</div>
        <ul className="vwhy">{top.map((e, i) => <li key={i}>{shorten(e.claim)}</li>)}</ul>
      </>)}
      <div className="vlinks">
        <a href="#trace">See how it got there</a>
        <a href="#report">Read the full report</a>
      </div>
    </section>
  );
}

const Help = ({ children }) => <p className="help">{children}</p>;

export function Report({ inv, onCite }) {
  const d = inv.diagnosis;
  return (
    <section className="report" id="report" aria-label="Full report">
      <h4>Evidence</h4>
      <Help>What the data showed. Click a step id (like call_3) to jump to the step it came from.</Help>
      <ul className="evidence">
        {d.evidence.map((e, i) => (
          <li key={i}>{e.claim} <button className="chip link" onClick={() => onCite(e.tool_call_id)}>{e.tool_call_id}</button></li>
        ))}
      </ul>

      {d.hypothesis_tests?.length > 0 && (<>
        <h4>Tests of the top theories</h4>
        <Help>Before answering, the agent had to test its two leading theories with a <Term k="stratified">like-for-like comparison</Term>.</Help>
        <ul className="evidence">
          {d.hypothesis_tests.map((t, i) => (
            <li key={i}><b>{t.hypothesis}</b>: changed {t.factor_varied}, kept {t.held_fixed} the same. {t.result}{" "}
              <button className="chip link" onClick={() => onCite(t.tool_call_id)}>{t.tool_call_id}</button></li>
          ))}
        </ul>
      </>)}

      <h4>Ruled out</h4>
      <Help>Other explanations the agent considered, and why it dropped them.</Help>
      <ul className="evidence">
        {d.rejected_hypotheses.map((h, i) => <li key={i}><b>{causeLabel(h.cause)}</b>: {h.why_rejected}</li>)}
        {d.rejected_hypotheses.length === 0 && <li className="muted">None listed.</li>}
      </ul>

      <h4>Still uncertain</h4>
      <ul className="evidence">{d.uncertainties.map((u, i) => <li key={i}>{u}</li>)}</ul>

      <h4>Suggested next steps</h4>
      <ul className="evidence">{d.recommended_actions.map((a, i) => <li key={i}>{a}</li>)}</ul>
      <p className="approval">⚑ ClusterDoctor never changes anything itself. A person decides whether to act on these.</p>

      <div className="verify">
        <b>Fact check:</b>{" "}
        {inv.claims_total > 0
          ? <>every claim was checked against the data. {inv.claims_unsupported_first} of {inv.claims_total} needed correcting
            {inv.revisions > 0 ? <>, which took {inv.revisions} revision{inv.revisions === 1 ? "" : "s"}</> : null}. {inv.claims_unsupported_final} left uncorrected.</>
          : "no fact check was recorded for this run."}
        {inv.dropped_evidence?.length > 0 && <> {inv.dropped_evidence.length} citation(s) were dropped because they pointed to a step that never ran.</>}
        <div className="muted">{inv.trace.length} data lookups · {inv.steps} model turns · ${fmt(inv.cost_usd, 3)} · {fmt(inv.wall_s, 0)} s · {inv.model}</div>
      </div>
    </section>
  );
}

export function Trace({ inv, shown, active }) {
  const cites = {};
  inv.diagnosis.evidence.forEach((e) => { cites[e.tool_call_id] = (cites[e.tool_call_id] || 0) + 1; });
  (inv.diagnosis.hypothesis_tests || []).forEach((t) => { cites[t.tool_call_id] = (cites[t.tool_call_id] || 0) + 1; });
  return (
    <ol className="trace" id="trace">
      {inv.trace.slice(0, shown).map((s, i) => <Step key={s.id} n={i + 1} step={s} active={active === s.id} cited={cites[s.id] || 0} />)}
    </ol>
  );
}
