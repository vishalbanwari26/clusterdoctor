"""Generate benchmark cases with live traffic (slow, costs a little).

Usage: PYTHONPATH=src uv run python scripts/bench_generate.py [reps]
Writes bench/cases/<id>.db and bench/manifest.json (resumable: skips existing cases).
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.faults import FAULTS, HEALTHY  # noqa: E402
from clusterdoctor.scenario import generate_case  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
N_FAULT = {"prompt_bloat": 45, "high_concurrency": 500, "retry_storm": 60, "healthy": 60,
           "overlap": 60, "misleading_event": 800, "bloat_subset": 120, "provider_slowdown": 60}
root = Path("bench"); (root / "cases").mkdir(parents=True, exist_ok=True)
manifest_path = root / "manifest.json"
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

for fault in [*FAULTS.values(), HEALTHY]:
    for rep in range(1, reps + 1):
        cid = f"{fault.name}_{rep}"
        if cid in manifest:
            continue
        print(f"[{cid}] generating...", flush=True)
        db = root / "cases" / f"{cid}.db"
        db.unlink(missing_ok=True)
        info = generate_case(Store(db), fault, 20, N_FAULT[fault.name])
        manifest[cid] = {**info, "db": str(db)}
        manifest_path.write_text(json.dumps(manifest, indent=2))
print("done:", len(manifest), "cases")
