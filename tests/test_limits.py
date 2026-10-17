import pytest

from clusterdoctor.limits import LiveGuard, LiveLimit, client_ip


class Clock:
    t = 1_000_000.0
    def __call__(self): return self.t


def test_per_ip_limit_then_other_ip_ok():
    g = LiveGuard(daily_cap=10, per_ip=2, max_concurrent=5, clock=Clock())
    for _ in range(2):
        g.acquire("1.1.1.1"); g.release()
    with pytest.raises(LiveLimit, match="per visitor"):
        g.acquire("1.1.1.1")
    g.acquire("2.2.2.2")


def test_daily_cap_and_reset_next_day():
    c = Clock(); g = LiveGuard(daily_cap=2, per_ip=5, max_concurrent=5, clock=c)
    g.acquire("a"); g.release(); g.acquire("b"); g.release()
    with pytest.raises(LiveLimit, match="Daily limit"):
        g.acquire("c")
    c.t += 86400
    g.acquire("c")                          # new UTC day, counters reset


def test_concurrency_limit_and_release():
    g = LiveGuard(daily_cap=10, per_ip=10, max_concurrent=1, clock=Clock())
    g.acquire("a")
    with pytest.raises(LiveLimit, match="busy"):
        g.acquire("b")
    g.release()
    g.acquire("b")


def test_client_ip_takes_last_forwarded_entry():
    assert client_ip({"x-forwarded-for": "6.6.6.6, 9.9.9.9"}, "10.0.0.1") == "9.9.9.9"
    assert client_ip({}, "10.0.0.1") == "10.0.0.1"
