from datetime import date

from app.limits import DailyBudget, RateLimiter


def test_rate_limiter_minute_and_day():
    now = [0.0]
    rl = RateLimiter(per_minute=2, per_day=3, clock=lambda: now[0])
    assert rl.check("ip") is None
    assert rl.check("ip") is None
    assert rl.check("ip") == "minute"
    assert rl.check("other") is None
    now[0] = 61
    assert rl.check("ip") is None
    now[0] = 122
    assert rl.check("ip") == "day"
    now[0] = 86_500
    assert rl.check("ip") is None


def test_daily_budget_reserve_settle_and_rollover():
    day = [date(2026, 11, 2)]
    b = DailyBudget(0.10, today=lambda: day[0])
    assert b.reserve(0.05) and b.reserve(0.05)
    assert not b.reserve(0.05)
    b.settle(0.05, 0.01)
    assert abs(b.spent - 0.06) < 1e-9
    day[0] = date(2026, 11, 3)
    assert b.spent == 0.0
