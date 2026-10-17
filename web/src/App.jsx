import React, { useCallback, useEffect, useRef, useState } from "react";
import { FleetGrid, LineChart } from "./charts.jsx";
import { Report, Trace } from "./Trace.jsx";
import { fmt, getJson, pretty } from "./util.js";

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

function Glance({ glance }) {
  const b = glance.baseline, i = glance.incident;
  const tile = (label, from, to, unit = "") => (
    <div className="tile"><div className="tlabel">{label}</div><div className="tval">{from}<span className="arrow"> → </span><b>{to}</b>{unit}</div></div>
  );
  return (
    <div className="tiles">
      {tile("p95 latency", fmt(b.latency_p95_s, 2), fmt(i.latency_p95_s, 2), " s")}
      {tile("Avg input tokens", b.avg_input_tokens, i.avg_input_tokens)}
      {tile("Avg retries / request", fmt(b.avg_retries, 2), fmt(i.avg_retries, 2))}
      {tile("Avg concurrency", b.avg_concurrency, i.avg_concurrency)}
    </div>
  );
}

function Evidence({ d }) {
  const c = d.chart;
  if (c.kind === "latency") {
    const pts = c.windows.map((w) => ({ x: w.t, y: w.p95, n: w.n }));
    return (<>
      <Glance glance={d.glance} />
      <LineChart title="p95 latency per 10 s window" unit="s" points={pts} xFmt={mmss}
        refLine={{ y: c.baseline_p95, label: `baseline p95 ${c.baseline_p95} s` }}
        markers={[{ x: c.change_t, label: c.events[0]?.detail ? "deploy" : "change" }]}
        tableRows={c.windows.map((w) => [mmss(w.t), w.p95 == null ? "n/a" : w.p95])} />
      {c.events.length > 0 && <p className="note">Recorded deploy/config event: {c.events.map((e) => e.detail).join("; ")}</p>}
    </>);
  }
  const f = c.flagged, minT = c.series[0].t;
  const rel = (t) => (t - minT) / 60;
  const inc = c.incident_window.map((t) => rel(t));
  const mins = (m) => `${Math.floor(m / 60)}h${String(Math.round(m % 60)).padStart(2, "0")}`;
  return (<>
    <FleetGrid chart={c} />
    <p className="note">Flagged: {f.node} GPU {f.gpu}.</p>
    <div className="two">
      <LineChart title={`${f.node} GPU ${f.gpu}: utilization (%)`} unit="%" yMax={100}
        points={c.series.map((s) => ({ x: rel(s.t), y: s.util }))} xFmt={mins} band={inc}
        markers={[{ x: rel(c.onset), label: "onset" }]} />
      <LineChart title={`${f.node} GPU ${f.gpu}: temperature (°C)`} unit="°C" yMax={100}
        points={c.series.map((s) => ({ x: rel(s.t), y: s.temp }))} xFmt={mins} band={inc}
        markers={[{ x: rel(c.onset), label: "onset" }]} />
    </div>
  </>);
}

export default function App() {
  const [list, setList] = useState([]);
  const [health, setHealth] = useState(null);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const [truth, setTruth] = useState(null);
  const [live, setLive] = useState(null);       // {state: "running"|"done"|"error", inv?, error?}
  const [shown, setShown] = useState(0);
  const [active, setActive] = useState(null);
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

  const inv = live?.state === "done" ? live.inv : detail?.investigation;
  const total = inv?.trace.length ?? 0;

  const replay = () => {
    clearInterval(timer.current);
    setShown(0); setActive(null);
    let n = 0;
    timer.current = setInterval(() => { n += 1; setShown(n); if (n >= total) clearInterval(timer.current); }, 700);
  };
  const cite = (id) => { setActive(id); setShown(total); setTimeout(() => setActive(null), 2500); };
  const rerun = async () => {
    if (!window.confirm("Run this investigation live on Nebius Token Factory with Nemotron? It takes about a minute and uses a small amount of the demo's credits (limited per visitor per day).")) return;
    setLive({ state: "running" });
    try { const r = await getJson(`/api/incidents/${sel}/rerun`, { method: "POST" }); setLive({ state: "done", inv: r }); setShown(r.trace.length); }
    catch (e) { setLive({ state: "error", error: e.message }); }
    loadHealth();
  };
  const reveal = () => getJson(`/api/incidents/${sel}/truth`).then(setTruth);
  const liveOn = health?.live_enabled && health.daily_used < health.daily_cap && health.ip_used < health.ip_cap;
  const replaying = shown < total && !live;

  return (
    <div className="app">
      <header className="top">
        <div><h1>ClusterDoctor</h1><span className="tag">From monitoring symptoms to diagnosing root causes</span></div>
        <div className="pills">
          <span className="pill">Replay mode · stored investigations, no API spend</span>
          <span className="pill dim">Live runs: {health ? (health.live_enabled
            ? `${health.daily_cap - health.daily_used} left today, ${Math.max(0, health.ip_cap - health.ip_used)} for you`
            : "off") : "n/a"}</span>
        </div>
      </header>

      <div className="body">
        <nav className="feed" aria-label="Incident feed">
          <h2>Incidents</h2>
          {list.map((i) => (
            <button key={i.id} className={"feeditem" + (i.id === sel ? " sel" : "")} onClick={() => setSel(i.id)}>
              <span className="row1">
                <span className={"domain " + i.domain}>{i.domain === "gpu" ? "GPU fleet" : "Inference"}</span>
                {i.domain === "gpu" && <span className="sim">simulated</span>}
              </span>
              <span className="ititle">{i.title}</span>
              <span className="isum">{i.summary}</span>
              {i.root_cause && <span className="idiag">→ {pretty(i.root_cause)} <span className="muted">({i.confidence})</span></span>}
            </button>
          ))}
          {list.length === 0 && <p className="muted">No replays found. Run scripts/build_replays.py.</p>}
        </nav>

        <main className="detail">
          {!detail && <p className="muted">Loading…</p>}
          {detail && (<>
            <div className="dhead">
              <h2>{detail.title}</h2>
              <p className="summary">{detail.summary}</p>
              <p className={"source" + (detail.domain === "gpu" ? " warn" : "")}>{detail.domain === "gpu" ? "⚠ " : ""}{detail.source}</p>
            </div>

            <section><h3>What the watcher saw</h3><Evidence d={detail} /></section>

            <section>
              <div className="invhead">
                <h3>Investigation</h3>
                <div className="actions">
                  <button onClick={replay} disabled={!inv || live?.state === "running"}>▶ Replay</button>
                  <button onClick={rerun} disabled={!liveOn || live?.state === "running"}
                          title={liveOn ? "Re-runs this investigation on Nebius Token Factory" : health?.live_enabled ? "Live run limit reached for today" : "Live runs are disabled on this server"}>
                    {live?.state === "running" ? "Running live…" : "Run live"}
                  </button>
                  <button onClick={reveal} disabled={!!truth}>Reveal injected fault</button>
                </div>
              </div>
              {live?.state === "error" && <p className="err">Live run failed: {live.error}</p>}
              {live?.state === "done" && <p className="note">Live result (not stored). Compare with the stored replay by selecting the incident again.</p>}
              {!inv && <p className="muted">No stored investigation for this incident.</p>}
              {inv && <Trace inv={inv} shown={shown} active={active} />}
              {inv && shown >= total && <Report inv={inv} onCite={cite} truth={truth} />}
              {inv && replaying && <p className="muted">Investigating… {shown}/{total} tool calls</p>}
            </section>
          </>)}
        </main>
      </div>
    </div>
  );
}
