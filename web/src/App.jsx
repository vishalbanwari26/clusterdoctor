import React, { useCallback, useEffect, useRef, useState } from "react";
import { FleetGrid, LineChart } from "./charts.jsx";
import Intro from "./Intro.jsx";
import Term from "./Term.jsx";
import { Report, Trace, Verdict } from "./Trace.jsx";
import { causeLabel } from "./glossary.js";
import { fmt, getJson } from "./util.js";

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const store = {
  get: (k) => { try { return window.localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { window.localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

/** One or two sentences in plain words about what happened, built from the incident's own numbers. */
function PlainSummary({ d }) {
  const c = d.chart;
  if (c.kind === "latency") {
    const b = d.glance.baseline, i = d.glance.incident;
    const bits = [];
    const ratio = i.avg_input_tokens / b.avg_input_tokens;
    if (ratio >= 1.2 || ratio <= 0.8) bits.push(`The average prompt ${ratio > 1 ? "grew" : "shrank"} from ${b.avg_input_tokens} to ${i.avg_input_tokens} tokens.`);
    if (i.avg_retries - b.avg_retries >= 0.05) bits.push(`Requests needed more retries (${fmt(b.avg_retries, 2)} to ${fmt(i.avg_retries, 2)} per request).`);
    if (i.avg_concurrency !== b.avg_concurrency) bits.push(`More requests ran at the same time (${b.avg_concurrency} to ${i.avg_concurrency} on average).`);
    if (!bits.length) bits.push("Nothing the app sends or measures changed noticeably.");
    return (
      <p className="plain">
        <b>In plain words:</b> the slowest 5% of responses (<Term k="p95">p95 latency</Term>) went from {fmt(b.latency_p95_s, 2)} s to {fmt(i.latency_p95_s, 2)} s.{" "}
        {bits.join(" ")} {c.events.length ? <>A deploy was recorded: &ldquo;{c.events[0].detail}&rdquo;.</> : "No deploy or config change was recorded."}
      </p>
    );
  }
  const f = c.flagged, real = c.simulated === false;
  const me = c.cells.find((x) => x.node === f.node && x.gpu === f.gpu);
  const peers = c.cells.filter((x) => x.node === f.node && x.gpu !== f.gpu && x.util_inc != null);
  const peerNow = peers.length ? Math.round(peers.reduce((s, x) => s + x.util_inc, 0) / peers.length) : null;
  const peerBase = peers.filter((x) => x.util_base != null);
  const peerBefore = peerBase.length ? Math.round(peerBase.reduce((s, x) => s + x.util_base, 0) / peerBase.length) : null;
  const tail = real ? "This is real telemetry, not a simulation." : "This data is simulated.";
  if (me.util_base == null) {
    return (
      <p className="plain">
        <b>In plain words:</b> {f.node} GPU {f.gpu} reported a driver error, but it has no <Term k="utilization">utilization</Term> data
        from before the event, so there is nothing to compare against. During the incident window it ran at {me.util_inc}%
        {peerNow != null && <>, about the same as the other GPUs on the machine ({peerNow}%)</>}. {tail}
      </p>
    );
  }
  const peersMoved = peerNow != null && peerBefore != null && peerNow < peerBefore * 0.8;
  return (
    <p className="plain">
      <b>In plain words:</b> {f.node} GPU {f.gpu} dropped from {me.util_base}% to {me.util_inc}% <Term k="utilization">utilization</Term>,
      {peersMoved ? <> and the other GPUs on the same machine dropped too ({peerBefore}% to {peerNow}%), which looks like the whole workload stalling together.</>
                  : <> while the other GPUs on the same machine stayed around {peerNow}%.</>} {tail}
    </p>
  );
}

function Glance({ glance }) {
  const b = glance.baseline, i = glance.incident;
  const tile = (label, from, to, unit = "") => (
    <div className="tile"><div className="tlabel">{label}</div><div className="tval">{from}<span className="arrow"> → </span><b>{to}</b>{unit}</div></div>
  );
  return (
    <>
      <div className="tilekey">Each box: <Term k="baseline">normal period</Term> → during the incident</div>
      <div className="tiles">
        {tile(<Term k="p95">p95 latency</Term>, fmt(b.latency_p95_s, 2), fmt(i.latency_p95_s, 2), " s")}
        {tile(<>Prompt size (<Term k="tokens">tokens</Term>)</>, b.avg_input_tokens, i.avg_input_tokens)}
        {tile(<>Avg <Term k="retries">retries</Term> per request</>, fmt(b.avg_retries, 2), fmt(i.avg_retries, 2))}
        {tile(<>Avg <Term k="concurrency">simultaneous requests</Term></>, b.avg_concurrency, i.avg_concurrency)}
      </div>
    </>
  );
}

function Evidence({ d }) {
  const c = d.chart;
  if (c.kind === "latency") {
    const pts = c.windows.map((w) => ({ x: w.t, y: w.p95, n: w.n }));
    return (<>
      <Glance glance={d.glance} />
      <LineChart title="How slow the slowest 5% of responses were (p95), in 10-second slices" unit="s" points={pts} xFmt={mmss}
        refLine={{ y: c.baseline_p95, label: `normal: ${c.baseline_p95} s` }}
        markers={[{ x: c.change_t, label: c.events[0]?.detail ? "deploy" : "change" }]}
        tableRows={c.windows.map((w) => [mmss(w.t), w.p95 == null ? "n/a" : w.p95])} />
    </>);
  }
  const f = c.flagged, minT = c.series[0].t;
  const rel = (t) => (t - minT) / 60;
  const inc = c.incident_window.map((t) => rel(t));
  const mins = (m) => `${Math.floor(m / 60)}h${String(Math.round(m % 60)).padStart(2, "0")}`;
  return (<>
    <FleetGrid chart={c} />
    <div className="two">
      <LineChart title={`${f.node} GPU ${f.gpu}: how busy it is over time (%)`} unit="%" yMax={100}
        points={c.series.map((s) => ({ x: rel(s.t), y: s.util }))} xFmt={mins} band={inc}
        markers={[{ x: rel(c.onset), label: c.simulated === false ? "Xid 94 reported" : "problem starts" }]} />
      <LineChart title={`${f.node} GPU ${f.gpu}: temperature (°C)`} unit="°C" yMax={100}
        points={c.series.map((s) => ({ x: rel(s.t), y: s.temp }))} xFmt={mins} band={inc}
        markers={[{ x: rel(c.onset), label: c.simulated === false ? "Xid 94 reported" : "problem starts" }]} />
    </div>
    <p className="note">The shaded band is the window the watcher flagged.</p>
  </>);
}

export default function App() {
  const [list, setList] = useState([]);
  const [health, setHealth] = useState(null);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const [truth, setTruth] = useState(null);
  const [live, setLive] = useState(null);
  const [shown, setShown] = useState(0);
  const [active, setActive] = useState(null);
  const [intro, setIntro] = useState(store.get("cd-intro-hidden") !== "1");
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef(null);

  const loadHealth = useCallback(() => getJson("/api/health").then(setHealth).catch(() => setHealth(null)), []);
  useEffect(() => {
    loadHealth();
    getJson("/api/incidents").then((l) => { setList(l); if (l.length) setSel(l[0].id); }).catch(() => {});
  }, [loadHealth]);

  useEffect(() => {
    if (!sel) return;
    clearInterval(timer.current);
    setDetail(null); setTruth(null); setLive(null); setActive(null);
    getJson(`/api/incidents/${sel}`).then((d) => { setDetail(d); setShown(d.investigation?.trace.length ?? 0); });
  }, [sel]);

  useEffect(() => {
    if (live?.state !== "running") return undefined;
    setElapsed(0);
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [live?.state]);

  const hideIntro = () => { setIntro(false); store.set("cd-intro-hidden", "1"); };
  const inv = live?.state === "done" ? live.inv : detail?.investigation;
  const total = inv?.trace.length ?? 0;
  const replaying = shown < total && !live;
  const finished = inv && shown >= total;

  const replay = () => {
    clearInterval(timer.current);
    setShown(0); setActive(null);
    let n = 0;
    timer.current = setInterval(() => { n += 1; setShown(n); if (n >= total) clearInterval(timer.current); }, 700);
  };
  const cite = (id) => { setActive(id); setShown(total); setTimeout(() => setActive(null), 2500); };
  const rerun = async () => {
    if (!window.confirm("Run this investigation live on Nebius Token Factory with Nemotron?\n\nIt takes 15 to 60 seconds and uses a small amount of the demo's credits (limited per visitor per day).")) return;
    setLive({ state: "running" });
    try { const r = await getJson(`/api/incidents/${sel}/rerun`, { method: "POST" }); setLive({ state: "done", inv: r }); setShown(r.trace.length); }
    catch (e) { setLive({ state: "error", error: e.message }); }
    loadHealth();
  };
  const reveal = () => getJson(`/api/incidents/${sel}/truth`).then(setTruth);
  const liveOn = health?.live_enabled && health.daily_used < health.daily_cap && health.ip_used < health.ip_cap;
  const liveWhy = !health?.live_enabled ? "Live runs are switched off on this server." : "Today's live-run limit has been reached. Replays still work.";

  return (
    <div className="app">
      <header className="top">
        <div><h1>ClusterDoctor</h1><span className="tag">Finds out why your AI service or GPU slowed down</span></div>
        <div className="pills">
          <span className="pill">Saved investigations: free to view</span>
          <span className="pill dim">Live runs: {health ? (health.live_enabled
            ? `${health.daily_cap - health.daily_used} left today, ${Math.max(0, health.ip_cap - health.ip_used)} for you` : "off") : "n/a"}</span>
          {!intro && <button className="pill helpbtn" onClick={() => setIntro(true)}>? How to read this</button>}
        </div>
      </header>

      <div className="body">
        <nav className="feed" aria-label="Incident list">
          <h2>Incidents</h2>
          {list.map((i, idx) => (
            <React.Fragment key={i.id}>
              {(idx === 0 || list[idx - 1].group !== i.group) && <h3 className="grouphead">{i.group}</h3>}
              <button className={"feeditem" + (i.id === sel ? " sel" : "")} onClick={() => setSel(i.id)} aria-current={i.id === sel}>
                <span className="ititle">{i.title}</span>
                <span className="isum">{i.summary.replace("p95_latency", "p95 latency")}</span>
                {i.root_cause && <span className="idiag">AI says: {causeLabel(i.root_cause)}</span>}
              </button>
            </React.Fragment>
          ))}
          {list.length === 0 && <p className="muted">No incidents found. Run scripts/build_replays.py.</p>}
        </nav>

        <main className="detail">
          {intro && <Intro onClose={hideIntro} />}
          {!detail && <p className="muted">Loading…</p>}
          {detail && (<>
            <div className="dhead">
              <h2>{detail.title}</h2>
              <PlainSummary d={detail} />
              <p className={"source" + (detail.chart.simulated !== false && detail.domain === "gpu" ? " warn" : detail.attribution ? " real" : "")}>
                {detail.chart.simulated !== false && detail.domain === "gpu" ? "⚠ " : ""}{detail.source}
              </p>
              {detail.attribution && (
                <p className="attrib">Data: <a href={detail.attribution.url} target="_blank" rel="noreferrer">{detail.attribution.dataset}</a>, {detail.attribution.license}.
                  Paper: {detail.attribution.paper}. Changes: {detail.attribution.changes}</p>
              )}
            </div>

            {finished && <Verdict inv={inv} truth={truth} />}

            <section>
              <h3><span className="num">1</span> What the <Term k="watcher">watcher</Term> saw</h3>
              <Evidence d={detail} />
            </section>

            <section>
              <div className="invhead">
                <h3><span className="num">2</span> How the report was built</h3>
                <div className="actions">
                  <button onClick={replay} disabled={!inv || live?.state === "running"}>▶ Watch it work</button>
                  <button onClick={rerun} disabled={!liveOn || live?.state === "running"} title={liveOn ? "Asks Nemotron again right now" : liveWhy}>
                    {live?.state === "running" ? "Running…" : "Run it live"}
                  </button>
                  <button onClick={reveal} disabled={!!truth || !finished}>Reveal the answer key</button>
                </div>
              </div>
              <p className="help">
                Each step is evidence the code collected before the AI wrote the report (if the check fails, a tool-using agent takes over and each step is a question it asked). <b>Watch it work</b> replays the saved run step by step.
                <b> Run it live</b> asks Nemotron again right now (15 to 60 seconds). <b>Reveal the answer key</b> shows what was really injected, so you can judge the AI.
              </p>
              {live?.state === "running" && (
                <div className="running" role="status" aria-live="polite">
                  <span className="spinner" aria-hidden /> Nemotron is investigating live on Token Factory… {elapsed} s (usually 20 to 70 s)
                </div>
              )}
              {live?.state === "error" && <p className="err">Live run didn&rsquo;t work: {live.error}</p>}
              {live?.state === "done" && <p className="note">This is a fresh live result and is not saved. Select the incident again to get back to the saved run.</p>}
              {!inv && !live && <p className="muted">There is no saved investigation for this incident.</p>}
              {inv && <Trace inv={inv} shown={shown} active={active} />}
              {inv && replaying && <p className="muted">Investigating… {shown} of {total} data lookups</p>}
            </section>

            {finished && (
              <section>
                <h3><span className="num">3</span> Full report</h3>
                <Report inv={inv} onCite={cite} />
              </section>
            )}
          </>)}
        </main>
      </div>
    </div>
  );
}
