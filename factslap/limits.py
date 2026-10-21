"""Abuse protection, all in Upstash Redis with atomic commands.

Every check must get through four hard gates before any money is spent:
1. One check per person per hour.
2. A fixed number of checks per day for everyone together (50 by default).
3. A cap on checks running at the same moment.
4. A daily budget: each check reserves its worst-case cost up front (atomic INCRBYFLOAT), and the
   reservation is corrected to the real cost afterwards, so parallel requests can't overshoot it.
IPs are stored only as salted hashes. If Redis is unreachable we refuse (fail closed): no limits, no spending.
Identical claims are answered from a cache, which costs nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from factslap.net import request_json


class LimitExceeded(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


@dataclass(frozen=True)
class Limits:
    """Hard limits, chosen because each check costs about 2 cents."""

    cooldown_s: int = int(os.getenv("FACTSLAP_COOLDOWN_SECONDS", "3600"))  # one check per person per hour
    daily_checks_total: int = int(os.getenv("FACTSLAP_DAILY_CHECKS_TOTAL", "50"))  # for everyone together
    max_in_flight: int = int(os.getenv("FACTSLAP_MAX_IN_FLIGHT", "4"))
    daily_budget_usd: float = float(os.getenv("LIMIT_OPENAI", "2"))
    reserve_usd: float = 0.08  # worst case for one check; the real cost is ~2 cents
    cache_ttl_s: int = 7 * 24 * 3600


class Redis:
    """Minimal async client for the Upstash REST API (pipeline endpoint: several commands, one round trip)."""

    def __init__(self, url: str, token: str):
        self.url, self.headers = url.rstrip("/"), {"Authorization": f"Bearer {token}"}

    async def pipeline(self, client: httpx.AsyncClient, *commands: list) -> list:
        data = await request_json(client, "POST", f"{self.url}/pipeline", headers=self.headers,
                                  json=[[str(part) for part in command] for command in commands], attempts=2)
        results = []
        for item in data:
            if "error" in item:
                raise RuntimeError(f"redis: {item['error']}")
            results.append(item.get("result"))
        return results


def hash_ip(ip: str | None, salt: str) -> str:
    return hashlib.sha256(f"{salt}|{ip or 'unknown'}".encode()).hexdigest()[:20]


def cache_key(claim: str, tone: str | None) -> str:
    normal = " ".join(unicodedata.normalize("NFKC", claim).lower().split()).rstrip(".!?")
    return "cache:" + hashlib.sha256(f"{normal}|{tone}".encode()).hexdigest()[:32]


@dataclass
class Ticket:
    user_key: str
    day: str
    reserved: float
    token: str


class Guard:
    def __init__(self, redis: Redis, limits: Limits | None = None, salt: str | None = None):
        self.redis = redis
        self.limits = limits or Limits()
        self.salt = salt or os.getenv("IP_HASH_SALT", "factslap")

    async def cached(self, client, key: str) -> dict | None:
        try:
            [value] = await self.redis.pipeline(client, ["GET", key])
        except Exception:
            return None
        return json.loads(value) if value else None

    async def remember(self, client, key: str, result: dict) -> None:
        try:
            await self.redis.pipeline(client, ["SET", key, json.dumps(result), "EX", self.limits.cache_ttl_s])
        except Exception:
            pass

    async def admit(self, client: httpx.AsyncClient, ip: str | None) -> Ticket:
        lim = self.limits
        user = hash_ip(ip, self.salt)
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        cooldown_key, count_key = f"cooldown:{user}", f"checks:{day}"
        token, now = uuid.uuid4().hex, time.time()
        try:
            # In-flight checks live in a sorted set scored by start time: entries older than the function
            # timeout are dropped, so a crashed request can never block capacity for good.
            cooldown_ok, cooldown_left, checks_today, _, _, _, in_flight = await self.redis.pipeline(
                client,
                ["SET", cooldown_key, "1", "NX", "EX", lim.cooldown_s],
                ["TTL", cooldown_key],
                ["INCR", count_key],
                ["EXPIRE", count_key, 172800],
                ["ZREMRANGEBYSCORE", "inflight", "-inf", now - 330],
                ["ZADD", "inflight", now, token],
                ["ZCARD", "inflight"],
            )
        except Exception as exc:
            raise LimitExceeded(503, "FactSlap is temporarily unavailable. Please try again in a minute.") from exc

        async def undo(*commands):
            try:
                await self.redis.pipeline(client, *commands)
            except Exception:
                pass

        if cooldown_ok is None:  # this person already ran a check in the last hour
            await undo(["DECR", count_key], ["ZREM", "inflight", token])
            minutes = max(1, -(-int(cooldown_left or lim.cooldown_s) // 60))
            raise LimitExceeded(429, f"FactSlap allows one check per hour per person. Try again in {minutes} min.",
                                int(cooldown_left or lim.cooldown_s))
        if int(checks_today) > lim.daily_checks_total:  # everyone's checks for today are used up
            await undo(["DECR", count_key], ["DEL", cooldown_key], ["ZREM", "inflight", token])
            raise LimitExceeded(429, f"Today's {lim.daily_checks_total} free checks are used up. Come back tomorrow!",
                                _seconds_to_midnight())
        if int(in_flight) > lim.max_in_flight:
            await undo(["DECR", count_key], ["DEL", cooldown_key], ["ZREM", "inflight", token])
            raise LimitExceeded(503, "FactSlap is busy right now. Please try again in a moment.", 10)

        budget_key = f"spend:{day}"
        try:
            [spent, _] = await self.redis.pipeline(client, ["INCRBYFLOAT", budget_key, lim.reserve_usd],
                                                   ["EXPIRE", budget_key, 172800])
        except Exception as exc:
            await undo(["DECR", count_key], ["DEL", cooldown_key], ["ZREM", "inflight", token])
            raise LimitExceeded(503, "FactSlap is temporarily unavailable. Please try again in a minute.") from exc
        if float(spent) > lim.daily_budget_usd:
            await undo(["INCRBYFLOAT", budget_key, -lim.reserve_usd], ["DECR", count_key], ["DEL", cooldown_key],
                       ["ZREM", "inflight", token])
            raise LimitExceeded(503, "FactSlap has reached today's budget. It will be back tomorrow.", _seconds_to_midnight())
        return Ticket(user_key=cooldown_key, day=day, reserved=lim.reserve_usd, token=token)

    async def release(self, client: httpx.AsyncClient, ticket: Ticket, cost_usd: float, succeeded: bool) -> None:
        # Hard limits: a started check always counts (it may already have cost money), even if it failed.
        commands = [["ZREM", "inflight", ticket.token],
                    ["INCRBYFLOAT", f"spend:{ticket.day}", round(cost_usd - ticket.reserved, 6)]]
        try:
            await self.redis.pipeline(client, *commands)
        except Exception:
            pass


def _seconds_to_midnight() -> int:
    now = datetime.now(UTC)
    return int(86400 - (now.hour * 3600 + now.minute * 60 + now.second))
