import React, { useState } from "react";

const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
const LABELS = {
  n: "Requests", error_rate: "Error rate", avg_retries: "Avg retries per request", avg_concurrency: "Avg simultaneous requests",
  app_versions: "App version", latency_p50_s: "Median latency (s)", latency_p95_s: "p95 latency (s)",
  avg_input_tokens: "Avg input tokens", avg_output_tokens: "Avg output tokens", ttft_p50_s: "Median time to first token (s)",
  median_latency_s: "Median latency (s)", input_tokens_range: "Prompt size (tokens)", concurrency_range: "Simultaneous requests",
  input_tokens: "Prompt size (tokens)", retries: "Retries", concurrency: "Simultaneous requests", window: "Period",
  share: "Share of requests", final_error_rate: "Ended in error", kind: "Type", detail: "What changed",
  before_incident_start: "Before the incident", util_pct: "Utilization (%)", temp_c: "Temperature (°C)", power_w: "Power (W)",
  sm_clock_mhz: "Clock speed (MHz)", samples: "Samples", share_throttled: "Share of time throttled",
  thermal_slowdown_share: "Share of time in thermal slowdown", xid_errors_seen: "GPU error codes seen",
  stdev: "Spread (std dev)", share_below_50pct: "Share of time below 50%", host_cpu_util_pct: "Host CPU (%)",
  is_flagged: "Flagged GPU", gpu: "GPU", baseline: "Normal period", incident: "Incident",
};
const nice = (k) => LABELS[k] ?? (k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()));
const HIDE = new Set(["ts"]);   // raw epoch timestamps are not readable

function cell(v) {
  if (v == null) return "n/a";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return Number.isInteger(v) ? v : +v.toFixed(2);
  return String(v);
}

/** Renders a tool result as a small table instead of raw JSON. */
export default function ResultView({ data }) {
  const [all, setAll] = useState(false);
  if (Array.isArray(data) && data.length && data.every(isObj)) {
    const cols = [...new Set(data.flatMap(Object.keys))].filter((c) => !HIDE.has(c));
    const rows = all ? data : data.slice(0, 8);
    return (
      <div className="rv">
        <table><thead><tr>{cols.map((c) => <th key={c}>{nice(c)}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{cell(r[c])}</td>)}</tr>)}</tbody></table>
        {data.length > 8 && !all && <button className="linkbtn" onClick={() => setAll(true)}>Show all {data.length} rows</button>}
      </div>
    );
  }
  if (isObj(data) && Object.values(data).length && Object.values(data).every(isObj)) {
    const colKeys = Object.keys(data);
    const rowKeys = [...new Set(Object.values(data).flatMap(Object.keys))];
    return (
      <div className="rv"><table>
        <thead><tr><th></th>{colKeys.map((c) => <th key={c}>{nice(c)}</th>)}</tr></thead>
        <tbody>{rowKeys.map((r) => <tr key={r}><th scope="row">{nice(r)}</th>{colKeys.map((c) => <td key={c}>{cell(data[c][r])}</td>)}</tr>)}</tbody>
      </table></div>
    );
  }
  if (isObj(data)) {
    return <div className="rv"><table><tbody>{Object.entries(data).map(([k, v]) => <tr key={k}><th scope="row">{nice(k)}</th><td>{cell(v)}</td></tr>)}</tbody></table></div>;
  }
  return <pre>{JSON.stringify(data, null, 2)}</pre>;
}
