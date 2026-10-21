import json

from fastapi.testclient import TestClient

import factslap.api as api
from tests.test_pipeline import make_app, outputs


def client_with_fake_pipeline(guard=None):
    app, _ = make_app(outputs())
    api._app = app
    api._guard = guard
    return TestClient(api.create_app())


def test_stream_sends_steps_then_the_result():
    client = client_with_fake_pipeline()
    response = client.post("/api/v2/check-stream",
                           json={"claim": "Cracking your knuckles causes arthritis", "tone": None})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events][-1] == "result"
    assert {e["step"] for e in events if e["type"] == "step"} >= {"plan", "search", "rank", "verdict", "verify"}
    assert events[-1]["verdict"]["label"] == "refuted"


def test_claim_length_is_validated():
    client = client_with_fake_pipeline()
    assert client.post("/api/v2/check", json={"claim": "hi"}).status_code == 422
    assert client.post("/api/v2/check", json={"claim": "x" * 301}).status_code == 422


def test_other_websites_are_rejected():
    client = client_with_fake_pipeline()
    response = client.post("/api/v2/check", json={"claim": "Cracking your knuckles causes arthritis"},
                           headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_guard_limits_and_cache_through_the_api():
    from factslap.limits import Guard, Limits
    from tests.test_limits import FakeRedis

    redis = FakeRedis()
    client = client_with_fake_pipeline(Guard(redis, Limits(cooldown_s=3600, daily_checks_total=50), salt="t"))
    body = {"claim": "Cracking your knuckles causes arthritis", "tone": None}
    first = client.post("/api/v2/check", json=body)
    assert first.status_code == 200 and first.json()["verdict"]["label"] == "refuted"
    # same claim again: served from the cache, so the cooldown doesn't even apply
    again = client.post("/api/v2/check", json=body)
    assert again.status_code == 200
    # a different claim within the hour is refused
    other = client.post("/api/v2/check", json={"claim": "Sugar makes children hyperactive", "tone": None})
    assert other.status_code == 429 and other.headers["retry-after"] == "3600"
    assert "one check per hour" in other.json()["error"]
