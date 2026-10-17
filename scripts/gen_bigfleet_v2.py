"""Generate the v2 scale-test fleet once (about 21 minutes of pure Python) into data/raw/bigfleet_v2 (git-ignored)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from clusterdoctor import bigfleet as B  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

d = Path("data/raw/bigfleet_v2"); d.mkdir(parents=True, exist_ok=True)
db = d / "fleet.db"; db.unlink(missing_ok=True); (d / "READY").unlink(missing_ok=True)
t = time.time(); s = Store(db); B.generate(s, B.plan_v2(), seed=2)
s.db.execute("CREATE INDEX IF NOT EXISTS idx_m_ts ON gpu_metrics(metric, ts)"); s.db.commit()
n = s.db.execute("SELECT COUNT(*) c FROM gpu_metrics").fetchone()["c"]
(d / "READY").write_text("ok"); print(f"fleet v2 ready: {n:,} samples in {time.time()-t:.0f} s", flush=True)
