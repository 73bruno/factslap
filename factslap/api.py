"""HTTP API: one plain endpoint and one that streams each step (Server-Sent Events). Both go through the
abuse guard (factslap/limits.py) before any model or API is called."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from factslap import share
from factslap.config import Settings
from factslap.limits import Guard, LimitExceeded, Redis, cache_key
from factslap.models import CheckResult, Tone
from factslap.net import new_client
from factslap.pipeline import FactSlap

ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "FACTSLAP_ALLOWED_ORIGINS", "https://www.factslap.app,https://factslap.app,http://localhost:5173").split(",")]

router = APIRouter(prefix="/api/v2")
_app: FactSlap | None = None
_guard: Guard | None = None


def get_factslap() -> FactSlap:
    global _app
    if _app is None:
        _app = FactSlap()
    return _app


def get_guard() -> Guard | None:
    global _guard
    if _guard is None and os.getenv("UPSTASH_REDIS_URL") and os.getenv("UPSTASH_REDIS_TOKEN"):
        _guard = Guard(Redis(os.environ["UPSTASH_REDIS_URL"], os.environ["UPSTASH_REDIS_TOKEN"]))
    return _guard


class CheckRequest(BaseModel):
    claim: str = Field(min_length=5, max_length=300)
    tone: Tone | None = Tone.CASUAL

    @field_validator("claim")
    @classmethod
    def plain_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 5:
            raise ValueError("claim is too short")
        return value


def client_ip(request: Request) -> str | None:
    # On Vercel these headers are set by the platform, so the client can't spoof them.
    for header in ("x-real-ip", "x-vercel-forwarded-for", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else None


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Requests are only accepted from factslap.app")


def limit_response(exc: LimitExceeded) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
    return JSONResponse({"error": exc.message}, status_code=exc.status, headers=headers)


@router.post("/check-stream")
async def check_stream(body: CheckRequest, request: Request):
    check_origin(request)
    guard = get_guard()
    key = cache_key(body.claim, body.tone.value if body.tone else None)
    async with new_client() as client:
        if guard is not None:
            cached = await guard.cached(client, key)
            if cached is not None and not cached.get("share_id"):  # cached before share links existed
                cached["share_id"] = await share.save(guard.redis, client, cached)
                await guard.remember(client, key, cached)
            if cached is not None:
                async def replay():
                    yield f"data: {json.dumps({'type': 'step', 'step': 'cache', 'message': 'Already checked', 'ms': 0})}\n\n"
                    yield f"data: {json.dumps({'type': 'result', **cached}, ensure_ascii=False)}\n\n"
                return StreamingResponse(replay(), media_type="text/event-stream")
            try:
                ticket = await guard.admit(client, client_ip(request))
            except LimitExceeded as exc:
                return limit_response(exc)
        elif os.getenv("VERCEL"):
            # In production the guard is mandatory: no Redis, no checks.
            return JSONResponse({"error": "FactSlap is temporarily unavailable."}, status_code=503)
        else:
            ticket = None

    async def events():
        cost, ok = 0.0, False
        async with new_client() as client:
            try:
                async for event in get_factslap().run(body.claim, body.tone, ip=client_ip(request), client=client):
                    if isinstance(event, CheckResult):
                        cost, ok = event.cost_usd, True
                        payload = event.model_dump(mode="json")
                        if guard is not None and event.verification.passed:
                            try:
                                payload["share_id"] = await share.save(guard.redis, client, payload)
                            except Exception:
                                pass  # sharing is a bonus; never fail a check over it
                            await guard.remember(client, key, payload)
                        yield f"data: {json.dumps({'type': 'result', **payload}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'step', **event.model_dump(mode='json')}, ensure_ascii=False)}\n\n"
            except Exception as exc:
                error = {"type": "error", "message": "The check failed, please try again.", "kind": type(exc).__name__}
                yield f"data: {json.dumps(error)}\n\n"
            finally:
                if guard is not None and ticket is not None:
                    await guard.release(client, ticket, cost, ok)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/check", response_model=CheckResult)
async def check(body: CheckRequest, request: Request):
    """Same pipeline without streaming (used by the evaluation and scripts); same guard."""
    response = await check_stream(body, request)
    if not isinstance(response, StreamingResponse):
        return response
    result = None
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["type"] == "result":
                    event.pop("type")
                    result = event
                elif event["type"] == "error":
                    raise HTTPException(status_code=502, detail=event["message"])
    return result


async def _shared_result(share_id: str) -> dict | None:
    guard = get_guard()
    if guard is None or not share.valid_share_id(share_id):
        return None
    async with new_client() as client:
        try:
            return await share.load(guard.redis, client, share_id)
        except Exception:
            return None


@router.get("/share/{share_id}")
async def shared(share_id: str):
    result = await _shared_result(share_id)
    if result is None:
        raise HTTPException(status_code=404, detail="This link has expired or never existed.")
    return result


@router.get("/share/{share_id}/card.jpg")
async def shared_card(share_id: str):
    result = await _shared_result(share_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(share.card_jpg(result, share_id), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400, s-maxage=604800, immutable"})


page_router = APIRouter()


@page_router.get("/c/{share_id}")
async def share_page(share_id: str):
    """The public link people paste: social previews read its tags, people are forwarded to the result."""
    result = await _shared_result(share_id)
    if result is None:
        return RedirectResponse("/", status_code=307)
    return HTMLResponse(share.page_html(share_id, result), headers={"Cache-Control": "public, max-age=300"})


@router.get("/health")
async def health() -> dict:
    s = Settings()
    return {"status": "ok", "llm": s.has_llm, "index": s.has_index, "guard": get_guard() is not None}


def create_app() -> FastAPI:
    app = FastAPI(title="FactSlap", version="2.0.0a1", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])
    app.include_router(router)
    app.include_router(page_router)
    return app
