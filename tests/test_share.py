from factslap import share
from factslap.limits import Guard, Limits
from tests.test_api import client_with_fake_pipeline
from tests.test_limits import FakeRedis

RESULT = {
    "claim": 'Cracking your knuckles causes "arthritis"',
    "verdict": {"label": "refuted", "confidence": 0.87},
    "answer": {"text": "No link was found [1][2].", "short": "No link with arthritis [1]."},
    "styled_answer": None,
    "evidence": [{}, {}, {}],
}


async def test_save_and_load_round_trip():
    redis = FakeRedis()
    share_id = await share.save(redis, None, RESULT)
    assert share.valid_share_id(share_id)
    assert await share.load(redis, None, share_id) == RESULT
    assert await share.load(redis, None, "../etc/x") is None


def test_preview_text_drops_citation_markers_and_escapes_html():
    title, description = share.summary(RESULT)
    assert title.startswith("REFUTED: “Cracking")
    assert "[1]" not in description and "3 sources cited" in description
    page = share.page_html("AbCdEf12", RESULT)
    assert 'property="og:image" content="https://www.factslap.app/api/v2/share/AbCdEf12/card.jpg"' in page
    assert "&quot;arthritis&quot;" in page  # quotes in the claim can't break the HTML attributes
    assert "/r/AbCdEf12" in page


def test_card_is_a_png_of_the_right_size():
    from io import BytesIO

    from PIL import Image

    for label in ("supported", "refuted", "mixed", "not_enough_evidence"):
        result = {**RESULT, "verdict": {"label": label, "confidence": 0.5}, "claim": "A very long claim " * 20}
        image = Image.open(BytesIO(share.card_jpg(result, "AbCdEf12")))
        assert image.format == "JPEG" and image.size == (1200, 627)


def test_checks_get_a_share_link_that_works_end_to_end():
    redis = FakeRedis()
    client = client_with_fake_pipeline(Guard(redis, Limits(cooldown_s=3600, daily_checks_total=50), salt="t"))
    result = client.post("/api/v2/check", json={"claim": "Cracking your knuckles causes arthritis", "tone": None}).json()
    share_id = result["share_id"]
    assert share.valid_share_id(share_id)

    assert client.get(f"/api/v2/share/{share_id}").json()["verdict"]["label"] == "refuted"
    card = client.get(f"/api/v2/share/{share_id}/card.jpg")
    assert card.headers["content-type"] == "image/jpeg" and "max-age" in card.headers["cache-control"]
    page = client.get(f"/c/{share_id}")
    assert page.status_code == 200 and "og:title" in page.text and "REFUTED" in page.text

    assert client.get("/api/v2/share/Zzzzzzzz").status_code == 404
    assert client.get("/c/Zzzzzzzz", follow_redirects=False).status_code == 307
