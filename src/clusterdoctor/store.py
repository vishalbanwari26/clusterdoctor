"""SQLite store for request telemetry captured by the instrumented client."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    app_version TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_s REAL,
    ttft_s REAL,
    status INTEGER NOT NULL,
    retries INTEGER NOT NULL DEFAULT 0,
    concurrency INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'live'  -- 'live' or 'simulated'
);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,        -- 'deploy', 'config_change', ...
    detail TEXT NOT NULL
);
"""


@dataclass
class Request:
    ts: float
    app_version: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_s: float | None
    ttft_s: float | None
    status: int
    retries: int = 0
    concurrency: int = 1
    source: str = "live"


class Store:
    def __init__(self, path: str | Path = "clusterdoctor.db"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def add_request(self, r: Request) -> None:
        d = asdict(r)
        cols = ",".join(d)
        marks = ",".join("?" * len(d))
        with self.lock:
            self.db.execute(f"INSERT INTO requests ({cols}) VALUES ({marks})", list(d.values()))
            self.db.commit()

    def add_event(self, ts: float, kind: str, detail: str) -> None:
        self.db.execute("INSERT INTO events (ts, kind, detail) VALUES (?,?,?)", (ts, kind, detail))
        self.db.commit()

    def requests_between(self, start: float, end: float) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM requests WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)
        ).fetchall()

    def events_between(self, start: float, end: float) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM events WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)
        ).fetchall()
