import pytest

from factslap.limits import Guard, LimitExceeded, Limits, cache_key, hash_ip


class FakeRedis:
    """Just enough Redis semantics for the guard (expiry is ignored)."""

    def __init__(self, fail: bool = False):
        self.kv: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.fail = fail

    async def pipeline(self, client, *commands):
        if self.fail:
            raise RuntimeError("redis down")
        return [self._run(*[str(c) for c in command]) for command in commands]

    def _run(self, op, key, *args):
        z = self.zsets.setdefault(key, {})
        if op == "SET":
            if "NX" in args and key in self.kv:
                return None
            self.kv[key] = args[0]
            if "EX" in args:
                self.ttl[key] = int(args[list(args).index("EX") + 1])
            return "OK"
        if op == "TTL":
            return self.ttl.get(key, -1) if key in self.kv else -2
        if op == "DEL":
            return int(self.kv.pop(key, None) is not None)
        if op == "GET":
            return self.kv.get(key)
        if op in ("INCR", "DECR"):
            self.kv[key] = str(int(self.kv.get(key, "0")) + (1 if op == "INCR" else -1))
            return int(self.kv[key])
        if op == "INCRBYFLOAT":
            self.kv[key] = str(float(self.kv.get(key, "0")) + float(args[0]))
            return self.kv[key]
        if op == "EXPIRE":
            return 1
        if op == "ZADD":
            z[args[1]] = float(args[0])
            return 1
        if op == "ZREM":
            return int(z.pop(args[0], None) is not None)
        if op == "ZCARD":
            return len(z)
        if op == "ZREMRANGEBYSCORE":
            low = float("-inf") if args[0] == "-inf" else float(args[0])
            for member in [m for m, s in z.items() if low <= s <= float(args[1])]:
                del z[member]
            return 0
        raise NotImplementedError(op)


def guard(**limits) -> tuple[Guard, FakeRedis]:
    redis = FakeRedis()
    defaults = {"cooldown_s": 3600, "daily_checks_total": 50, "max_in_flight": 4, "daily_budget_usd": 2.0}
    return Guard(redis, Limits(**{**defaults, **limits}), salt="test"), redis


async def test_one_check_per_person_per_hour_even_if_it_failed():
    g, _ = guard()
    ticket = await g.admit(None, "1.1.1.1")
    await g.release(None, ticket, 0.02, succeeded=False)  # hard limit: a started check always counts
    with pytest.raises(LimitExceeded) as exc:
        await g.admit(None, "1.1.1.1")
    assert exc.value.status == 429 and exc.value.retry_after == 3600
    assert "one check per hour" in exc.value.message and "60 min" in exc.value.message
    assert await g.admit(None, "1.1.1.2")  # someone else is fine


async def test_hard_daily_cap_for_everyone():
    g, redis = guard(daily_checks_total=3, max_in_flight=100)
    for i in range(3):
        await g.release(None, await g.admit(None, f"2.2.2.{i}"), 0.02, True)
    with pytest.raises(LimitExceeded, match="3 free checks are used up"):
        await g.admit(None, "2.2.2.9")
    # the refused visitor isn't put on the hourly cooldown, and the counter stays at the cap
    assert f"cooldown:{hash_ip('2.2.2.9', 'test')}" not in redis.kv
    assert next(v for k, v in redis.kv.items() if k.startswith("checks:")) == "3"


async def test_concurrency_cap_and_release():
    g, _ = guard(max_in_flight=2)
    tickets = [await g.admit(None, f"10.0.0.{i}") for i in range(2)]
    with pytest.raises(LimitExceeded, match="busy"):
        await g.admit(None, "10.0.0.9")
    await g.release(None, tickets[0], 0.02, True)
    assert await g.admit(None, "10.0.0.8")


async def test_budget_reservation_stops_spending_and_is_corrected_to_the_real_cost():
    g, redis = guard(daily_budget_usd=0.2, max_in_flight=100)
    admitted = 0
    with pytest.raises(LimitExceeded, match="budget"):
        for i in range(10):
            await g.admit(None, f"9.9.9.{i}")  # never released: reservations pile up like parallel requests
            admitted += 1
    assert admitted == 2  # 2 x 0.08 reserved fits in 0.20, the third would not
    spend_key = next(k for k in redis.kv if k.startswith("spend:"))
    assert float(redis.kv[spend_key]) == pytest.approx(0.16)


async def test_redis_down_fails_closed():
    g = Guard(FakeRedis(fail=True), Limits(), salt="x")
    with pytest.raises(LimitExceeded) as exc:
        await g.admit(None, "3.3.3.3")
    assert exc.value.status == 503


def test_ips_are_hashed_and_cache_key_ignores_case_and_spacing():
    assert "4.4.4.4" not in hash_ip("4.4.4.4", "salt")
    assert cache_key("Sugar makes kids  hyperactive.", "casual") == cache_key(
        "sugar makes kids hyperactive", "casual")
    assert cache_key("x claim", "casual") != cache_key("x claim", "aggressive")
