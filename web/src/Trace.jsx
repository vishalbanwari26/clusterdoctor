import React, { useEffect, useRef } from "react";
import { fmt, pretty } from "./util.js";

const preview = (r) => {
  const s = JSON.stringify(r);
  return s.length > 150 ? s.slice(0, 150) + "…" : s;
};

function Step({ n, step, active, cited }) {
  const ref = useRef(null);
  useEffect(() => { if (active && ref.current) ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [active]);
  return (
    <li ref={ref} id={"step-" + step.id} className={"step" + (active ? " active" : "")}>
      <div className="stephead">
        <span className="stepnum">{n}</span>
        <code className="toolname">{step.tool}</code>
        {Object.entries(step.args).map(([k, v]) => <span className="chip" key={k}>{k}: {String(v)}</span>)}
        <span className="callid">{step.id}</span>
        {cited > 0 && <span className="chip cited">cited {cited}x</span>}
      </div>
      <details>
        <summary><code className="preview">{preview(step.result)}</code></summary>
        <pre>{JSON.stringify(step.result, null, 2)}</pre>
      </details>
    </li>
  );
}

function Confidence({ level }) {
  const icon = { high: "●●●", medium: "●●○", low: "●○○" }[level] || "";
  return <span className={"conf " + level} title="Model's stated confidence"><span aria-hidden>{icon}</span> {level} confidence</span>;
}

export function Report({ inv, onCite, truth }) {
  const d = inv.diagnosis;
  const cites = {};
  d.evidence.forEach((e) => { cites[e.tool_call_id] = (cites[e.tool_call_id] || 0) + 1; });
  const abstained = d.root_cause === "insufficient_evidence";
  return (
    <section className="report" aria-label="Diagnosis">
      <h3>Diagnosis</h3>
      <div className="verdict">
        <span className={"cause" + (abstained ? " abstain" : "")}>{pretty(d.root_cause)}</span>
        <Confidence level={d.confidence} />
        {truth && (
          <span className={"truthchip " + (truth.root_cause === d.root_cause ? "match" : "miss")}>
            {truth.root_cause === d.root_cause ? "✔ matches injected fault" : "✖ injected fault was " + pretty(truth.root_cause)}
          </span>
        )}
      </div>

      <h4>Evidence</h4>
      <ul className="evidence">
        {d.evidence.map((e, i) => (
          <li key={i}>{e.claim} <button className="chip link" onClick={() => onCite(e.tool_call_id)}>{e.tool_call_id}</button></li>
        ))}
      </ul>

      {d.hypothesis_tests?.length > 0 && (<>
        <h4>Hypothesis tests</h4>
        <ul className="evidence">
          {d.hypothesis_tests.map((t, i) => (
            <li key={i}><b>{t.hypothesis}</b>: varied {t.factor_varied}, held {t.held_fixed}. {t.result}{" "}
              <button className="chip link" onClick={() => onCite(t.tool_call_id)}>{t.tool_call_id}</button></li>
          ))}
        </ul>
      </>)}

      <h4>Rejected hypotheses</h4>
      <ul className="evidence">
        {d.rejected_hypotheses.map((h, i) => <li key={i}><b>{pretty(h.cause)}</b>: {h.why_rejected}</li>)}
        {d.rejected_hypotheses.length === 0 && <li className="muted">None listed.</li>}
      </ul>

      <h4>Still uncertain</h4>
      <ul className="evidence">{d.uncertainties.map((u, i) => <li key={i}>{u}</li>)}</ul>

      <h4>Recommended actions</h4>
      <ul className="evidence">{d.recommended_actions.map((a, i) => <li key={i}>{a}</li>)}</ul>
      <p className="approval">⚑ ClusterDoctor never changes infrastructure. Each action needs a human to approve it.</p>

      <div className="verify">
        <b>Checks:</b>{" "}
        {inv.claims_total > 0
          ? <>{inv.claims_total} claims checked against the tool results; {inv.claims_unsupported_first} flagged on the first
            attempt, {inv.claims_unsupported_final} after {inv.revisions} revision{inv.revisions === 1 ? "" : "s"}.</>
          : "no claim check recorded."}
        {inv.dropped_evidence?.length > 0 && <> {inv.dropped_evidence.length} citation(s) dropped (call never made).</>}
        <div className="muted">{inv.steps} model turns · {inv.trace.length} tool calls · ${fmt(inv.cost_usd, 3)} · {fmt(inv.wall_s, 0)} s · {inv.model}</div>
      </div>
    </section>
  );
}

export function Trace({ inv, shown, active }) {
  const cites = {};
  inv.diagnosis.evidence.forEach((e) => { cites[e.tool_call_id] = (cites[e.tool_call_id] || 0) + 1; });
  (inv.diagnosis.hypothesis_tests || []).forEach((t) => { cites[t.tool_call_id] = (cites[t.tool_call_id] || 0) + 1; });
  return (
    <ol className="trace">
      {inv.trace.slice(0, shown).map((s, i) => <Step key={s.id} n={i + 1} step={s} active={active === s.id} cited={cites[s.id] || 0} />)}
    </ol>
  );
}
