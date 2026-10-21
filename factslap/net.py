"""One HTTP helper for every external API: timeouts, retries with backoff, no blocking sleeps."""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    pass


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    base_delay: float = 0.6,
    **kwargs: Any,
) -> Any:
    """Send a request and return parsed JSON, retrying temporary failures."""
    last_error: str = ""
    for attempt in range(attempts):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code in RETRY_STATUS:
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("retry-after")
                if retry_after and retry_after.isdigit() and attempt < attempts - 1:
                    await asyncio.sleep(min(float(retry_after), 5.0))
                    continue
            elif response.status_code >= 400:
                raise SourceError(f"HTTP {response.status_code} from {url}: {response.text[:200]}")
            else:
                return response.json()
        if attempt < attempts - 1:
            await asyncio.sleep(base_delay * (2**attempt) + random.uniform(0, 0.3))
    raise SourceError(f"{url} failed after {attempts} attempts ({last_error})")


def new_client(timeout: float = 12.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": "FactSlap/2.0 (https://www.factslap.app)"},
        follow_redirects=True,
    )
