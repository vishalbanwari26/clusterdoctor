"""Computed evidence sections (pre-registered as Test 5 in docs/preregistered-tests.md). Pure code, no model."""
from __future__ import annotations

import statistics


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None if singular."""
    n = len(b); m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))) / m[i][i]
    return x


def effect_split(tools) -> dict:
    """What explains the latency rise, using ONLY variation inside the incident window.

    OLS of latency on prompt size (per 1,000 tokens), retries and concurrency, over successful requests in the incident window.
    A factor that does not vary inside the window cannot be separated from the other changes there, so it is reported as such.
    """
    def rows(w):
        return [r for r in tools.store.requests_between(*tools._window(w)) if r["status"] == 200 and r["latency_s"] is not None and r["input_tokens"] is not None]
    inc, base = rows("incident"), rows("baseline")
    if len(inc) < 8 or not base:
        return {"note": "too few requests in the incident window to separate factors"}
    feats = {"prompt_size": (lambda r: r["input_tokens"] / 1000.0, "s per 1,000 input tokens"),
             "retries": (lambda r: float(r["retries"]), "s per retry"),
             "concurrency": (lambda r: float(r["concurrency"]), "s per extra simultaneous request")}
    y = [r["latency_s"] for r in inc]; my_b, my_i = statistics.mean(r["latency_s"] for r in base), statistics.mean(y)
    out, varying = [], []
    for name, (f, unit) in feats.items():
        xs = [f(r) for r in inc]; mi = statistics.mean(xs); mb = statistics.mean(f(r) for r in base)
        v = statistics.pstdev(xs) / max(abs(mi), 1e-9) >= 0.05 and max(xs) > min(xs)
        out.append({"factor": name, "varies_in_incident_window": v, "mean_normal": round(mb, 3), "mean_incident": round(mi, 3), "unit": unit})
        if v: varying.append((name, f, mi, mb))
    explained, r2 = 0.0, None
    if varying:
        X = [[1.0] + [f(r) for _, f, _, _ in varying] for r in inc]
        k = len(X[0]); xtx = [[sum(row[i] * row[j] for row in X) + (1e-9 if i == j else 0) for j in range(k)] for i in range(k)]
        xty = [sum(row[i] * yy for row, yy in zip(X, y)) for i in range(k)]
        beta = _solve(xtx, xty)
        if beta:
            pred = [sum(b * x for b, x in zip(beta, row)) for row in X]
            ss_res = sum((a - p) ** 2 for a, p in zip(y, pred)); ss_tot = sum((a - my_i) ** 2 for a in y) or 1e-9
            r2 = round(1 - ss_res / ss_tot, 3)
            for (name, f, mi, mb), b in zip(varying, beta[1:]):
                e = b * (mi - mb); explained += e
                d = next(o for o in out if o["factor"] == name); d["slope"] = round(b, 4); d["explained_rise_s"] = round(e, 3)
    return {"method": "latency ~ the factors that vary inside the incident window, fitted on the incident window only",
            "n_incident_requests": len(inc), "mean_latency_normal_s": round(my_b, 3), "mean_latency_incident_s": round(my_i, 3),
            "observed_rise_s": round(my_i - my_b, 3), "explained_by_varying_factors_s": round(explained, 3),
            "unexplained_s": round((my_i - my_b) - explained, 3), "r2_within_window": r2, "factors": out,
            "note": "A factor with varies_in_incident_window=false changed between the normal period and the incident but cannot be told apart "
                    "from the other changes in this window; its effect is in 'unexplained_s' if it matters."}


def dimension_scan(tools, top: int = 3, flag_z: float = 4.0) -> list[dict]:
    """Automatic scan of every dimension and metric for groups whose incident mean is an outlier among groups. For BigFleetTools."""
    out = []
    for metric in ("util", "temp", "power"):
        for dim, keyf in (("node", lambda n, g: n), ("rack", lambda n, g: f"rack {int(n[1:3])}"), ("slot", lambda n, g: f"slot {g}")):
            groups: dict = {}
            for (n, g), v in tools._gpu_means(metric, "incident").items():
                groups.setdefault(keyf(n, g), []).append(v)
            means = {k: statistics.mean(v) for k, v in groups.items()}
            # Robust z (median and MAD). A plain z cannot exceed (n-1)/sqrt(n) with n groups: about 2.5 for 8 slots.
            mu = statistics.median(means.values())
            sd = (statistics.median(abs(v - mu) for v in means.values()) * 1.4826) or 1e-9
            for k in sorted(means, key=lambda k: -abs(means[k] - mu))[:top]:
                z = (means[k] - mu) / sd
                out.append({"metric": metric, "dimension": dim, "group": k, "mean": round(means[k], 2), "n_gpus": len(groups[k]),
                            "z": round(z, 1), "outlier": abs(z) >= flag_z})
    return out
