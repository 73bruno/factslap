"""Shareable results: a short link per check, a preview card image and the page social networks read.

A checked claim gets an id like `k3J9xQ2m`. `/c/<id>` serves a tiny HTML page whose Open Graph tags make
LinkedIn, X or WhatsApp show the verdict as a card, then sends people to the result in the web app.
Nothing here calls a model: sharing costs nothing.
"""
from __future__ import annotations

import html
import io
import json
import math
import secrets
import string
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ALPHABET = string.ascii_letters + string.digits
SHARE_TTL_S = 180 * 24 * 3600
SITE = "https://www.factslap.app"
ASSETS = Path(__file__).parent / "assets"  # fonts (OFL / Apache 2.0, licences next to them) and the logo
STAMP, TYPEWRITER, BRAND = "BlackOpsOne-Regular.ttf", "SpecialElite-Regular.ttf", "ArchivoBlack-Regular.ttf"

VERDICT_LABELS = {
    "supported": "SUPPORTED",
    "refuted": "REFUTED",
    "mixed": "MIXED EVIDENCE",
    "not_enough_evidence": "NOT ENOUGH EVIDENCE",
}
STAMP_INK = {  # the word on the rubber stamp and its ink
    "supported": ("SUPPORTED", (22, 150, 80)),
    "refuted": ("REFUTED", (214, 40, 57)),
    "mixed": ("MIXED", (226, 132, 0)),
    "not_enough_evidence": ("UNPROVEN", (52, 86, 196)),
}


def new_share_id() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def valid_share_id(share_id: str) -> bool:
    return len(share_id) == 8 and all(c in ALPHABET for c in share_id)


async def save(redis, client, payload: dict) -> str:
    share_id = new_share_id()
    await redis.pipeline(client, ["SET", f"share:{share_id}", json.dumps(payload), "EX", SHARE_TTL_S])
    return share_id


async def load(redis, client, share_id: str) -> dict | None:
    if not valid_share_id(share_id):
        return None
    [value] = await redis.pipeline(client, ["GET", f"share:{share_id}"])
    return json.loads(value) if value else None


def summary(result: dict) -> tuple[str, str]:
    """(title, description) for link previews."""
    label = VERDICT_LABELS.get(result["verdict"]["label"], VERDICT_LABELS["not_enough_evidence"])
    answer = result.get("styled_answer") or result.get("answer") or {}
    text = answer.get("short") or answer.get("text") or ""
    clean = " ".join(part for part in text.replace("[", " [").split() if not part.startswith("["))
    sources = len(result.get("evidence") or [])
    description = f"{clean} {sources} sources cited. Checked with FactSlap." if sources else clean
    return f"{label}: “{result['claim']}”", description[:300]


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / name), size)


def _wrap(draw, text: str, font, width_at) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width_at(len(lines)) or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return [*lines, line]


def _fit_claim(draw, claim: str, top: int, width: int, max_height: int):
    """Biggest size that fits; lines low enough to meet the stamp get shorter so the text flows around it."""
    for size in (62, 56, 50, 44, 38, 34):
        font, step = _font(TYPEWRITER, size), int(size * 1.22)
        lines = _wrap(draw, f"“{claim}”", font, lambda i, step=step: width if top + (i + 1) * step < 300 else 500)
        if len(lines) * step <= max_height:
            return font, lines, step
    lines = lines[: max_height // step]
    lines[-1] = lines[-1].rstrip(" ”") + "…”"
    return font, lines, step


def _star(draw, cx: float, cy: float, r: float) -> None:
    points = [(cx + (r if i % 2 == 0 else r * 0.45) * math.cos(-math.pi / 2 + i * math.pi / 5),
               cy + (r if i % 2 == 0 else r * 0.45) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]
    draw.polygon(points, fill=255)


def _worn(mask: Image.Image) -> Image.Image:
    """Rubber-stamp wear: speckles where the ink didn't take and uneven pressure."""
    w, h = mask.size
    speckle = Image.effect_noise((w, h), 70).filter(ImageFilter.GaussianBlur(1.1)).point(lambda v: 0 if v > 168 else 255)
    pressure = Image.effect_noise((w // 60 + 2, h // 60 + 2), 60).resize((w, h), Image.BICUBIC)
    pressure = pressure.point(lambda v: int(140 + v * 115 / 255))
    return ImageChops.multiply(ImageChops.multiply(mask, speckle), pressure).filter(ImageFilter.GaussianBlur(0.5))


def _stamp(word: str, color: tuple, sources: int) -> Image.Image:
    w, h = 550, 270
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    size = 100
    while draw.textlength(word, font=_font(STAMP, size)) > 430:
        size -= 4
    small = _font(BRAND, 24)
    draw.rounded_rectangle((6, 6, w - 6, h - 6), radius=26, outline=255, width=11)
    draw.rounded_rectangle((26, 26, w - 26, h - 26), radius=14, outline=255, width=4)
    draw.text((w / 2, 60), "FACTSLAP", font=small, fill=255, anchor="mm")
    half = draw.textlength("FACTSLAP", font=small) / 2
    _star(draw, w / 2 - half - 26, 59, 11)
    _star(draw, w / 2 + half + 26, 59, 11)
    draw.text((w / 2, h / 2 + 2), word, font=_font(STAMP, size), fill=255, anchor="mm")
    draw.text((w / 2, h - 60), f"{sources} SOURCES CITED" if sources else "NO SOLID SOURCES", font=small, fill=255,
              anchor="mm")
    ink = Image.new("RGBA", (w, h), (*color, 0))
    ink.putalpha(_worn(mask).point(lambda v: int(v * 0.93)))
    return ink.rotate(11, resample=Image.BICUBIC, expand=True)


def card_jpg(result: dict, share_id: str | None = None) -> bytes:
    """1200×627 preview card: the claim typed on a report, the verdict stamped across it."""
    width, height = 1200, 627
    word, color = STAMP_INK.get(result["verdict"]["label"], STAMP_INK["not_enough_evidence"])
    sources = len(result.get("evidence") or [])
    confidence = round(float(result["verdict"].get("confidence", 0)) * 100)
    cx, cy = 880, 420  # centre of the stamp

    canvas = Image.new("RGBA", (width, height), (13, 19, 38, 255))
    draw = ImageDraw.Draw(canvas)
    rays = 28  # comic burst behind the stamp, like the slap in the logo
    for i in range(0, rays, 2):
        a0, a1 = 2 * math.pi * i / rays, 2 * math.pi * (i + 1) / rays
        draw.polygon([(cx, cy), (cx + 1600 * math.cos(a0), cy + 1600 * math.sin(a0)),
                      (cx + 1600 * math.cos(a1), cy + 1600 * math.sin(a1))], fill=(22, 31, 60, 255))

    pw, ph = 880, 440
    paper = Image.blend(Image.new("RGBA", (pw, ph), (244, 239, 225, 255)),
                        Image.effect_noise((pw, ph), 28).convert("RGBA"), 0.06)
    draw = ImageDraw.Draw(paper)
    ink, faded = (38, 36, 44), (110, 104, 96)
    draw.text((48, 40), "FACT-CHECK REPORT", font=_font(TYPEWRITER, 28), fill=ink)
    if share_id:
        draw.text((pw - 48, 40), f"No. {share_id}", font=_font(TYPEWRITER, 24), fill=faded, anchor="ra")
    for x in range(48, pw - 48, 14):
        draw.line((x, 88, x + 7, 88), fill=(120, 112, 100), width=2)
    draw.text((48, 112), "CLAIM:", font=_font(TYPEWRITER, 24), fill=faded)
    font, lines, step = _fit_claim(draw, result["claim"], 150, pw - 96, 205)
    for i, line in enumerate(lines):
        draw.text((48, 150 + i * step), line, font=font, fill=ink)
    draw.text((48, ph - 70), f"CONFIDENCE: {confidence}%", font=_font(TYPEWRITER, 26), fill=ink)

    shadow = Image.new("RGBA", (pw + 80, ph + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((40, 40, pw + 40, ph + 40), fill=(0, 0, 0, 170))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)).rotate(2, Image.BICUBIC, expand=True), (20, 6))
    canvas.alpha_composite(paper.rotate(2, Image.BICUBIC, expand=True), (52, 24))
    stamp = _stamp(word, color, sources)
    canvas.alpha_composite(stamp, (cx - stamp.width // 2, cy - stamp.height // 2))

    canvas.alpha_composite(Image.open(ASSETS / "logo-92.png").convert("RGBA"), (50, height - 104))
    draw = ImageDraw.Draw(canvas)
    draw.text((154, height - 76), "FactSlap", font=_font(BRAND, 36), fill=(255, 255, 255), anchor="lm")
    draw.text((156, height - 38), "factslap.app", font=_font(BRAND, 22), fill=(165, 180, 252), anchor="lm")
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="JPEG", quality=88, optimize=True)  # paper grain makes PNGs heavy
    return buffer.getvalue()


def page_html(share_id: str, result: dict) -> str:
    """What crawlers read (Open Graph tags); people are sent on to the result in the app."""
    title, description = (html.escape(part, quote=True) for part in summary(result))
    url = f"{SITE}/c/{share_id}"
    image = f"{SITE}/api/v2/share/{share_id}/card.jpg"
    target = f"/r/{share_id}"
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · FactSlap</title>
<meta name="description" content="{description}">
<meta property="og:type" content="article"><meta property="og:site_name" content="FactSlap">
<meta property="og:url" content="{url}"><meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{image}"><meta property="og:image:width" content="1200">
<meta property="og:image:height" content="627">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}"><meta name="twitter:image" content="{image}">
<meta http-equiv="refresh" content="0; url={target}">
</head><body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif">
<p><a href="{target}" style="color:#a5b4fc">See the evidence on FactSlap</a></p>
<script>location.replace({json.dumps(target)})</script>
</body></html>"""
