"""Limits on live (credit-spending) runs: per-IP, per-day, and concurrent.

In-memory, so counters reset when the server restarts. Treat these as a speed bump and set a
spending limit on the API key in the Nebius console as the real hard cap.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict


class LiveLimit(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LiveGuard:
    def __init__(self, daily_cap: int = 20, per_ip: int = 2, max_concurrent: int = 2, clock=time.time):
        self.daily_cap, self.per_ip, self.max_concurrent, self.clock = daily_cap, per_ip, max_concurrent, clock
        self._lock = threading.Lock()
        self._day = None
        self._used = 0
        self._ips: dict[str, int] = defaultdict(int)
        self._running = 0

    def _roll(self) -> None:
        day = int(self.clock() // 86400)            # UTC day
        if day != self._day:
            self._day, self._used, self._ips = day, 0, defaultdict(int)

    def acquire(self, ip: str) -> None:
        with self._lock:
            self._roll()
            if self._used >= self.daily_cap:
                raise LiveLimit(f"Daily limit of {self.daily_cap} live runs reached. Replays still work; try again tomorrow (UTC).")
            if self._ips[ip] >= self.per_ip:
                raise LiveLimit(f"Limit of {self.per_ip} live runs per visitor per day reached. Replays still work.")
            if self._running >= self.max_concurrent:
                raise LiveLimit("The server is busy with other live runs. Try again in a minute.")
            self._used += 1
            self._ips[ip] += 1
            self._running += 1

    def release(self) -> None:
        with self._lock:
            self._running -= 1

    def status(self, ip: str | None = None) -> dict:
        with self._lock:
            self._roll()
            return {"daily_cap": self.daily_cap, "daily_used": self._used,
                    "ip_cap": self.per_ip, "ip_used": self._ips[ip] if ip else None}


def client_ip(headers, peer: str | None) -> str:
    """Behind a proxy, the last X-Forwarded-For entry is the one the proxy added (earlier ones are client-supplied)."""
    xff = headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return peer or "unknown"
