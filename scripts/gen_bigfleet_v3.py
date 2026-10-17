"""Held-out fleet for Test 5d: same generator and families, a NEW seed and placements. Generated before any run on it."""
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from clusterdoctor import bigfleet as B  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

d = Path("data/raw/bigfleet_v3"); d.mkdir(parents=True, exist_ok=True)
db = d / "fleet.db"; db.unlink(missing_ok=True); (d / "READY").unlink(missing_ok=True)
cases = B.plan_v2(seed=77, slot=6)
t = time.time(); s = Store(db); B.generate(s, cases, seed=78)
s.db.execute("CREATE INDEX IF NOT EXISTS idx_m_ts ON gpu_metrics(metric, ts)"); s.db.commit()
(d / "READY").write_text("ok"); print(f"fleet v3 ready in {time.time()-t:.0f} s", flush=True)
