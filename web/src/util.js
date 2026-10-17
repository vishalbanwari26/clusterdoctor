export const pretty = (s) => (s ? s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "");

export async function getJson(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return r.json();
}

export const fmt = (v, d = 1) => (v == null ? "n/a" : Number(v).toFixed(d));

// Sequential blue ramp (steps 700 -> 250 of the reference palette), low -> high utilization on a dark surface.
const RAMP = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef"];
export const rampColor = (pct) => RAMP[Math.max(0, Math.min(RAMP.length - 1, Math.floor((pct / 100) * RAMP.length)))];
export const RAMP_COLORS = RAMP;
