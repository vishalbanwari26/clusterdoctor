import React, { useEffect, useRef, useState } from "react";
import { RAMP_COLORS, fmt, rampColor } from "./util.js";

function useWidth() {
  const ref = useRef(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const niceMax = (v) => {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((c) => c >= v);
};

/**
 * One measure, one axis. points: [{x, y|null}], refLine: {y,label}, markers: [{x,label}], band: [x0,x1].
 * Single series: no legend, the title names it.
 */
export function LineChart({ title, unit, points, xFmt, refLine, markers = [], band, yMax, tableRows }) {
  const [ref, W] = useWidth();
  const [hover, setHover] = useState(null);
  const H = 210, m = { t: 14, r: 14, b: 28, l: 44 };
  const xs = points.map((p) => p.x);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const ys = points.map((p) => p.y).filter((v) => v != null);
  const top = yMax ?? niceMax(Math.max(...ys, refLine?.y ?? 0) * 1.1);
  const sx = (x) => m.l + ((x - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const sy = (y) => m.t + (1 - y / top) * (H - m.t - m.b);
  const segs = [];
  let cur = [];
  points.forEach((p) => { if (p.y == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); });
  if (cur.length) segs.push(cur);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  const nearest = (clientX, rect) => {
    const x = x0 + ((clientX - rect.left - m.l) / (W - m.l - m.r)) * (x1 - x0);
    return points.reduce((a, b) => (Math.abs(b.x - x) < Math.abs(a.x - x) ? b : a));
  };
  return (
    <figure className="chart" ref={ref}>
      <figcaption>{title}</figcaption>
      <svg width={W} height={H} role="img" aria-label={title}
           onMouseMove={(e) => setHover(nearest(e.clientX, e.currentTarget.getBoundingClientRect()))}
           onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={sy(t)} y2={sy(t)} className="grid" />
            <text x={m.l - 8} y={sy(t) + 4} className="axis" textAnchor="end">{+t.toFixed(top < 10 ? 2 : 0)}</text>
          </g>
        ))}
        {band && <rect x={sx(band[0])} y={m.t} width={Math.max(2, sx(band[1]) - sx(band[0]))} height={H - m.t - m.b} className="band" />}
        {refLine && (
          <g>
            <line x1={m.l} x2={W - m.r} y1={sy(refLine.y)} y2={sy(refLine.y)} className="ref" />
            <text x={W - m.r} y={sy(refLine.y) - 6} className="axis" textAnchor="end">{refLine.label}</text>
          </g>
        )}
        {markers.map((mk, i) => (
          <g key={i}>
            <line x1={sx(mk.x)} x2={sx(mk.x)} y1={m.t} y2={H - m.b} className="marker" />
            <text x={sx(mk.x) + 4} y={m.t + 10} className="axis">{mk.label}</text>
          </g>
        ))}
        {segs.map((s, i) => (
          <polyline key={i} points={s.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")} className="series" />
        ))}
        {[x0, (x0 + x1) / 2, x1].map((x) => (
          <text key={x} x={sx(x)} y={H - 8} className="axis" textAnchor="middle">{xFmt(x)}</text>
        ))}
        {hover && hover.y != null && (
          <g>
            <line x1={sx(hover.x)} x2={sx(hover.x)} y1={m.t} y2={H - m.b} className="crosshair" />
            <circle cx={sx(hover.x)} cy={sy(hover.y)} r={4} className="dot" />
          </g>
        )}
      </svg>
      {hover && hover.y != null && (
        <div className="tooltip" style={{ left: Math.min(sx(hover.x) + 10, W - 150), top: 30 }}>
          <b>{fmt(hover.y, 2)} {unit}</b><br />{xFmt(hover.x)}{hover.n != null && <> · {hover.n} requests</>}
        </div>
      )}
      {tableRows && (
        <details className="tableview"><summary>Table view</summary>
          <table><thead><tr><th>Time</th><th>{unit}</th></tr></thead>
            <tbody>{tableRows.map((r, i) => <tr key={i}><td>{r[0]}</td><td>{r[1]}</td></tr>)}</tbody></table>
        </details>
      )}
    </figure>
  );
}

export function FleetGrid({ chart }) {
  const real = chart.simulated === false;
  const [hover, setHover] = useState(null);
  const byNode = {};
  chart.cells.forEach((c) => { (byNode[c.node] ||= []).push(c); });
  const nodes = Object.keys(byNode).sort();
  const f = chart.flagged;
  return (
    <figure className="chart fleet">
      <figcaption>Mean GPU utilization during the incident window, {chart.cells.length} GPUs{real ? " on this machine (real data)" : " (simulated)"}</figcaption>
      <div className="grid8" role="img" aria-label="GPU utilization heatmap">
        {nodes.map((n) => (
          <div className="noderow" key={n}>
            <span className="nodelabel">{n.replace("node-", "n")}</span>
            {byNode[n].map((c) => {
              const flagged = c.node === f.node && c.gpu === f.gpu;
              return (
                <button key={c.gpu} className={"cell" + (flagged ? " flagged" : "")}
                        style={{ background: c.util_inc == null ? "#33332f" : rampColor(c.util_inc) }}
                        onMouseEnter={() => setHover(c)} onMouseLeave={() => setHover(null)}
                        onFocus={() => setHover(c)} onBlur={() => setHover(null)}
                        aria-label={`${c.node} GPU ${c.gpu}: ${c.util_inc ?? "no"}% utilization`}>
                  {flagged ? <span className="flagmark">!</span> : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <div className="legendrow">
        <span className="scale">0%<span className="bar">{RAMP_COLORS.map((c) => <i key={c} style={{ background: c }} />)}</span>100%</span>
        <span className="flaglegend"><span className="flagmark inline">!</span> flagged by the watcher</span>
      </div>
      <div className="hoverline">
        {hover ? <>{hover.node} GPU {hover.gpu}: <b>{hover.util_inc ?? "no data"}{hover.util_inc != null && "%"}</b> now, {hover.util_base != null ? `${hover.util_base}%` : "no data"} at baseline, {hover.temp_inc ?? "no"} °C</>
               : "Hover a GPU for details. Darker cells ran at lower utilization; not every one is an incident (a GPU can simply be idle)."}
      </div>
      <details className="tableview"><summary>Table view</summary>
        <table><thead><tr><th>GPU</th><th>Util now</th><th>Util baseline</th><th>Temp °C</th></tr></thead>
          <tbody>{chart.cells.filter((c) => c.util_inc < 60 || (c.node === f.node && c.gpu === f.gpu)).map((c) => (
            <tr key={c.node + c.gpu}><td>{c.node} / {c.gpu}</td><td>{c.util_inc ?? "n/a"}</td><td>{c.util_base ?? "n/a"}</td><td>{c.temp_inc ?? "n/a"}</td></tr>))}</tbody></table>
        <p className="note">Showing GPUs below 60% utilization and the flagged one. The grid has all 64.</p>
      </details>
    </figure>
  );
}
