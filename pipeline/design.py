"""
design.py — Visuals V2: the AI-imagery design agent (VISUALS.md Phase V2).

Human designers work as: find inspiration → prompt an image model → iterate →
finish typography in Canva. This module automates that loop with one reframe —
the "Canva finish" IS Satori: the deterministic text/brand layer always sits
on top (hero_card template), so the imagery underneath never has to spell.

The pipeline:

    pick a backend          library (keyless: the account's approved
                            backgrounds in visual_refs) or openai (paid
                            gpt-image-1, hard per-day cap, every generation
                            saved back into visual_refs for free reuse)
    build the prompt        brand kit colors/mood/notes + the post's subject +
                            an explicit NO TEXT instruction (text is Satori's)
    generate → critique     Claude vision judges generated imagery (composition,
                            brand palette fit, headline legibility) and feeds
                            specific fixes back into a bounded regenerate loop —
                            the persona-gate shape, with vision as the judge.
                            Library picks skip critique: a human approved them.
    composite               background + scrim + headline + brand footer via
                            the hero_card Satori template.

Posture, as everywhere: fail-safe. No backend, no refs, a dead API, a failed
critique — generate_hero returns None and the caller keeps the flat card.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.llm import tracked_create

logger = logging.getLogger("design")

CRITIQUE_SYSTEM = (
    "You are an art director reviewing a background image for a branded social "
    "graphic. A headline and brand footer will be composited ON TOP of it later "
    "— judge the image as a backdrop, not a finished design."
)


def _strip_fence(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())


def refs_dir() -> Path:
    d = Path(settings.visuals_dir) / "refs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Prompt construction (pure)
# --------------------------------------------------------------------------- #
def build_image_prompt(post: dict, kit: Optional[dict], account: dict) -> str:
    """Deterministic image prompt from brand kit + post subject. The crucial
    constraint: NO text in the image — typography belongs to Satori."""
    content = (post.get("content") or "").strip()
    subject = re.sub(r"(?:\s*#\w+)+\s*$", "", content).split("\n")[0][:200]
    kit = kit or {}
    mood = {"dark": "moody, high-contrast", "light": "clean, airy, minimal",
            "gradient": "vibrant, modern"}.get(kit.get("bg_style") or "dark",
                                               "moody, high-contrast")
    bits = [
        f"Abstract editorial background image for a social media graphic about: {subject}.",
        f"Style: {mood}, premium brand photography / subtle 3D render aesthetic.",
    ]
    palette = [c for c in (kit.get("accent_color"), kit.get("secondary_color")) if c]
    if palette:
        bits.append(f"Color palette anchored on {' and '.join(palette)}.")
    if kit.get("notes"):
        bits.append(f"Brand mood notes: {kit['notes']}.")
    if account.get("niche"):
        bits.append(f"Audience/world: {account['niche']}.")
    bits.append(
        "Composition: generous negative space (a headline will be overlaid), "
        "darker toward the bottom. STRICTLY no text, no letters, no words, no "
        "numbers, no logos, no watermarks, no human faces in close-up."
    )
    return " ".join(bits)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class LibraryBackend:
    """Keyless: picks the best approved background from visual_refs by keyword
    overlap between the prompt and each ref's tags/notes (newest wins ties).
    A human chose these images, so no critique pass is needed."""

    name = "library"

    def __init__(self, account_id: int, db_path: Optional[str] = None):
        self.account_id = account_id
        self.db_path = db_path

    def _refs(self) -> list[dict]:
        return (memory.get_visual_refs(self.account_id, kind="background",
                                       db_path=self.db_path)
                + memory.get_visual_refs(self.account_id, kind="generated",
                                         db_path=self.db_path))

    def available(self) -> bool:
        return bool(self._refs())

    @staticmethod
    def _score(ref: dict, words: set) -> int:
        hay = " ".join([" ".join(ref.get("tags") or []), ref.get("notes") or ""]).lower()
        return sum(1 for w in words if w in hay)

    def generate(self, prompt: str, feedback: str = "") -> Optional[bytes]:
        refs = self._refs()
        if not refs:
            return None
        words = {w for w in re.findall(r"[a-z]{4,}", prompt.lower())}
        best = max(refs, key=lambda r: self._score(r, words))  # ties -> newest
        try:
            if best.get("path"):
                return Path(best["path"]).read_bytes()
            if best.get("url"):
                import requests
                resp = requests.get(best["url"], timeout=15)
                resp.raise_for_status()
                return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Library ref #%s unreadable: %s", best.get("id"), exc)
        return None


class OpenAIImageBackend:
    """Paid generation via gpt-image-1. Hard per-day cap; every result is
    saved into visual_refs (kind='generated') so it can be reused for free
    and so the cap can be counted from the data itself."""

    name = "openai"
    URL = "https://api.openai.com/v1/images/generations"

    def __init__(self, account_id: int, db_path: Optional[str] = None,
                 transport=None):
        self.account_id = account_id
        self.db_path = db_path
        self._transport = transport          # injectable for tests
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()

    def available(self) -> bool:
        if settings.imagegen_backend != "openai" or not self.api_key:
            return False
        used = memory.generated_images_today(db_path=self.db_path)
        if used >= settings.imagegen_daily_cap:
            logger.info("Image generation cap reached (%d/%d today).",
                        used, settings.imagegen_daily_cap)
            return False
        return True

    def generate(self, prompt: str, feedback: str = "") -> Optional[bytes]:
        full = f"{prompt} Revision notes: {feedback}" if feedback else prompt
        try:
            if self._transport:
                png = self._transport(full)
            else:
                import requests
                resp = requests.post(
                    self.URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": "gpt-image-1", "prompt": full,
                          "size": "1536x1024", "n": 1},
                    timeout=120)
                resp.raise_for_status()
                png = base64.b64decode(resp.json()["data"][0]["b64_json"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Image generation failed: %s", exc)
            return None
        # keep it: reusable asset + the daily-cap counter
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%f")
        path = refs_dir() / f"gen-{self.account_id}-{stamp}.png"
        try:
            path.write_bytes(png)
            memory.add_visual_ref(self.account_id, kind="generated",
                                  path=str(path), notes=full[:300],
                                  db_path=self.db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist generated background: %s", exc)
        return png


def pick_backend(account_id: int, db_path: Optional[str] = None):
    """Paid backend when configured and under cap, else the approved library,
    else None (caller keeps the flat-card path)."""
    paid = OpenAIImageBackend(account_id, db_path=db_path)
    if paid.available():
        return paid
    lib = LibraryBackend(account_id, db_path=db_path)
    if lib.available():
        return lib
    return None


# --------------------------------------------------------------------------- #
# Vision critique (the judge in the loop)
# --------------------------------------------------------------------------- #
def critique_image(client: Any, png: bytes, prompt: str) -> tuple[float, str]:
    """Score 0-10 + concrete feedback for a GENERATED background. Fail-open:
    any error returns the accept score — a broken judge must never block."""
    try:
        msg = tracked_create(client, "design",
            model=settings.model,
            max_tokens=300,
            system=CRITIQUE_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(png).decode()}},
                {"type": "text", "text": (
                    f"The brief was: {prompt}\n\n"
                    "Return JSON with exactly these keys:\n"
                    '  "score": 0-10 — fitness as a headline backdrop '
                    "(composition with negative space, on-palette colors, no "
                    "embedded text/logos/garbled artifacts, dark enough at the "
                    "bottom for light text),\n"
                    '  "feedback": one or two SPECIFIC revision instructions '
                    "if score < 8, else empty string."
                )},
            ]}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        data = json.loads(_strip_fence(text))
        return (max(0.0, min(10.0, float(data.get("score", settings.design_accept_score)))),
                str(data.get("feedback") or ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vision critique failed (accepting image): %s", exc)
        return settings.design_accept_score, ""


# --------------------------------------------------------------------------- #
# The orchestrator
# --------------------------------------------------------------------------- #
def _image_asset(png: bytes) -> Optional[dict]:
    """Background bytes -> the {src, width, height} shape Satori needs."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        mime = f"image/{(img.format or 'png').lower()}"
        return {"src": f"data:{mime};base64,{base64.b64encode(png).decode()}",
                "width": img.width, "height": img.height}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Background unreadable as image: %s", exc)
        return None


def _headline(post: dict) -> str:
    meta = post.get("meta_json") or {}
    tweets = meta.get("tweets") or []
    text = tweets[0] if tweets else (post.get("content") or "")
    return re.sub(r"(?:\s*#\w+)+\s*$", "", text).strip()


def generate_hero(post_id: int, db_path: Optional[str] = None,
                  renderer=None, client: Any = None) -> Optional[str]:
    """The full V2 loop for one post. Returns the saved PNG path, or None on
    any miss (no backend, no image, render failure) — never raises."""
    from pipeline import visuals

    post = memory.get_post(post_id, db_path=db_path)
    if not post or not (post.get("content") or "").strip():
        return None
    account = memory.get_account(post["account_id"], db_path=db_path) or {}
    kit = memory.get_brand_kit(post["account_id"], db_path=db_path)

    backend = pick_backend(post["account_id"], db_path=db_path)
    if backend is None:
        logger.info("No image backend for account %s (no refs uploaded, no "
                    "paid backend) — keeping the flat card.", post["account_id"])
        return None

    prompt = build_image_prompt(post, kit, account)
    png: Optional[bytes] = None
    feedback = ""
    iters = 1 if backend.name == "library" else max(1, settings.design_max_iters)
    for attempt in range(iters):
        candidate = backend.generate(prompt, feedback=feedback)
        if candidate is None:
            break
        png = candidate
        if backend.name == "library":      # human-approved: no critique needed
            break
        score, feedback = critique_image(client or _lazy_client(), png, prompt)
        logger.info("Design critique for #%d attempt %d: %.1f %s",
                    post_id, attempt + 1, score, feedback[:120])
        if score >= settings.design_accept_score or not feedback:
            break
    if png is None:
        return None

    asset = _image_asset(png)
    if asset is None:
        return None
    r = renderer or visuals.SatoriRenderer()
    out = r.render("hero_card", {"text": _headline(post), "image": asset},
                   visuals.brand_payload(account, kit))
    if out is None:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = visuals._save(out, f"post{post_id}-{stamp}-hero.png")
    memory.update_post_meta(post_id, {"visual": path.name,
                                      "visual_template": "hero_card"},
                            db_path=db_path)
    logger.info("Hero visual for #%d via %s backend: %s",
                post_id, backend.name, path.name)
    return str(path)


def _lazy_client() -> Any:
    settings.require_anthropic()
    from anthropic import Anthropic
    return Anthropic(api_key=settings.anthropic_api_key)
