"""
visuals.py — branded graphics for drafts (the Satori pipeline; see VISUALS.md).

The architecture in one line: templates live in render/ as flexbox layouts,
a persistent localhost Node service (satori → resvg) turns them into PNGs,
and this module is the Python side — pick the right template for a post,
build its payload from the content + the account's brand kit, render, save.

Renderer posture (the usual discipline):
  * SatoriRenderer talks to the local service; ensure_service() spawns it on
    first use and health-checks thereafter.
  * PillowRenderer (the old image/cards.py) is the FAIL-SAFE: if node or the
    service is unavailable, you still get a card. A visual must never block
    the posting flow.
  * Everything stays behind render() so the backend remains swappable
    (hosted API or Chromium later, per VISUALS.md, without touching callers).
"""

from __future__ import annotations

import atexit
import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import settings
from pipeline import memory

logger = logging.getLogger("visuals")

# The most prominent number in a post — currency, percent, or large figure.
STAT = re.compile(r"(?:₹|\$|€)\s?[\d,.]+\s*(?:lakh|crore|cr|k|m|bn|billion|million)?"
                  r"|\d[\d,.]*\s*%"
                  r"|\b\d[\d,]{3,}\b")

_service_proc: Optional[subprocess.Popen] = None


# --------------------------------------------------------------------------- #
# Template choice + payload (pure functions)
# --------------------------------------------------------------------------- #
def extract_stat(text: str) -> Optional[str]:
    m = STAT.search(text or "")
    return m.group(0).strip() if m else None


def _strip_hashtags(text: str) -> str:
    text = re.sub(r"(?:\s*#\w+)+\s*$", "", text or "").strip()
    return text


def choose_template(post: dict) -> tuple[str, dict]:
    """(template, data) for a post. quote-ish content gets the quote card,
    a post built on a number gets the stat card, everything else the insight
    card. Threads/long forms use their first line as the hook."""
    meta = post.get("meta_json") or {}
    tweets = meta.get("tweets") or []
    text = _strip_hashtags(tweets[0] if tweets else post["content"])

    fmt = post.get("format") or ""
    if fmt == "quote_context":
        return "quote_card", {"text": text}
    stat = extract_stat(text)
    if fmt == "data_story" or (stat and fmt in ("hot_take", "prediction", "callback")):
        if stat:
            context = text.replace(stat, "").strip(" .—–:,-")
            return "stat_highlight", {"stat": stat, "context": context or text}
    title = {"explainer": "Explained", "prediction": "Prediction",
             "callback": "Called it", "counter_narrative": "The other side",
             "evergreen": "Standing take", "linkedin_post": "",
             "newsletter": ""}.get(fmt, "")
    return "insight_card", {"title": title, "text": text}


_LOGO_CACHE: dict = {}


def logo_asset(logo_url: Optional[str], height: int = 40) -> Optional[dict]:
    """Fetch a brand logo and prepare it for Satori: a data URL plus explicit
    width/height (Satori requires both; Pillow measures the aspect ratio).
    Cached per URL; any failure -> None (logo is decoration, never a blocker)."""
    if not logo_url:
        return None
    if logo_url in _LOGO_CACHE:
        return _LOGO_CACHE[logo_url]
    try:
        import base64
        import io

        import requests
        from PIL import Image

        resp = requests.get(logo_url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        w = max(1, round(img.width * height / img.height))
        mime = resp.headers.get("Content-Type", "").split(";")[0] or "image/png"
        if not mime.startswith("image/"):
            mime = "image/png"
        asset = {
            "src": f"data:{mime};base64,{base64.b64encode(resp.content).decode()}",
            "width": w, "height": height,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Logo fetch failed for %s: %s", logo_url, exc)
        asset = None
    _LOGO_CACHE[logo_url] = asset
    return asset


def brand_payload(account: dict, kit: Optional[dict]) -> dict:
    return {
        "accent_color": (kit or {}).get("accent_color"),
        "secondary_color": (kit or {}).get("secondary_color"),
        "bg_style": (kit or {}).get("bg_style"),
        "font_family": (kit or {}).get("font_family"),
        "watermark_text": (kit or {}).get("watermark_text")
                          or (settings.ai_label or "").strip(),
        "handle": account.get("handle") or "",
        "logo": logo_asset((kit or {}).get("logo_url")),
    }


# --------------------------------------------------------------------------- #
# Carousel splitting (pure function)
# --------------------------------------------------------------------------- #
CAROUSEL_FORMATS = ("thread", "linkedin_post", "newsletter")


def split_into_slides(post: dict, kit: Optional[dict] = None) -> Optional[dict]:
    """Break a multi-idea post into carousel slides:
    {"cover": hook, "slides": [body...], "cta": {cta_text, cta_url}} — or None
    when the content is too thin to deserve a carousel (single card instead).

    Threads map naturally: tweet 1 is the cover, the rest are slides.
    Long-form (linkedin_post/newsletter): first paragraph (or its first
    sentence, if huge) is the cover; remaining paragraphs are greedily packed
    into slides under the per-slide character budget.
    """
    meta = post.get("meta_json") or {}
    tweets = [_strip_hashtags(t) for t in (meta.get("tweets") or []) if t.strip()]

    if tweets:
        if len(tweets) < 2:
            return None
        cover, slides = tweets[0], tweets[1:]
    else:
        paras = [p.strip() for p in re.split(r"\n{2,}|\n", post["content"])
                 if p.strip()]
        paras = [_strip_hashtags(p) for p in paras if _strip_hashtags(p)]
        if len(paras) < 2 or len(post["content"]) < 350:
            return None
        cover = paras[0]
        if len(cover) > 160:  # huge opener: hook = its first sentence
            first = re.split(r"(?<=[.!?])\s+", cover, maxsplit=1)
            if len(first) == 2:
                cover, rest = first[0], first[1]
                paras = [rest] + paras[1:]
            else:
                paras = paras[1:]
        else:
            paras = paras[1:]
        # greedy pack paragraphs into slides under the budget
        budget = settings.carousel_slide_chars
        slides: list[str] = []
        current = ""
        for p in paras:
            if current and len(current) + len(p) + 2 > budget:
                slides.append(current)
                current = p
            else:
                current = f"{current}\n\n{p}".strip()
        if current:
            slides.append(current)
    slides = slides[: settings.carousel_max_slides]
    if not slides:
        return None
    return {
        "cover": cover,
        "slides": slides,
        "cta": {"cta_text": (kit or {}).get("cta_text"),
                "cta_url": (kit or {}).get("cta_url")},
    }


# --------------------------------------------------------------------------- #
# The render service lifecycle
# --------------------------------------------------------------------------- #
def _health_url() -> str:
    return f"http://127.0.0.1:{settings.visuals_port}/health"


def _is_healthy(timeout: float = 1.5) -> bool:
    try:
        import requests
        return requests.get(_health_url(), timeout=timeout).json().get("ok") is True
    except Exception:  # noqa: BLE001
        return False


def ensure_service() -> bool:
    """Spawn the Node render service if it isn't running. Returns healthy?"""
    global _service_proc
    if _is_healthy():
        return True
    server = Path(settings.render_dir) / "server.mjs"
    if not server.exists():
        logger.info("render/server.mjs not found — visuals will use the Pillow fallback.")
        return False
    try:
        _service_proc = subprocess.Popen(
            ["node", str(server)],
            cwd=settings.render_dir,
            env={"VISUALS_PORT": str(settings.visuals_port), "PATH": "/usr/local/bin:/usr/bin:/bin"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        atexit.register(lambda: _service_proc and _service_proc.terminate())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not start render service: %s", exc)
        return False
    for _ in range(20):  # up to ~4s for node to boot
        if _is_healthy(timeout=0.5):
            return True
        time.sleep(0.2)
    logger.warning("Render service did not become healthy.")
    return False


# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #
class SatoriRenderer:
    """Renders via the local Node service. transport injectable for tests."""

    def __init__(self, transport=None) -> None:
        self._transport = transport

    def render(self, template: str, data: dict, brand: dict) -> Optional[bytes]:
        if self._transport is None:
            if not ensure_service():
                return None
        try:
            if self._transport:
                return self._transport(template, data, brand)
            import requests
            resp = requests.post(
                f"http://127.0.0.1:{settings.visuals_port}/render",
                json={"template": template, "data": data, "brand": brand},
                timeout=20)
            if resp.status_code != 200:
                logger.warning("Render failed (%s): %s", resp.status_code,
                               resp.text[:200])
                return None
            return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Satori render failed: %s", exc)
            return None


class PillowRenderer:
    """The fail-safe: the original simple text card. Always works."""

    def render(self, template: str, data: dict, brand: dict) -> Optional[bytes]:
        try:
            from image.cards import render_card
            text = data.get("text") or " ".join(
                filter(None, [data.get("stat"), data.get("context")]))
            path = render_card(text, handle=brand.get("handle", ""))
            return Path(path).read_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.error("Pillow fallback failed too: %s", exc)
            return None


# --------------------------------------------------------------------------- #
# The public entry point
# --------------------------------------------------------------------------- #
def _save(png: bytes, name: str) -> Path:
    out_dir = Path(settings.visuals_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_bytes(png)
    return path


def generate_carousel(post: dict, account: dict, kit: Optional[dict],
                      renderer, db_path: Optional[str] = None) -> Optional[str]:
    """Render cover + content slides + CTA as separate square PNGs. Records
    every slide in post meta (visual_slides) and returns the cover's path.
    Any slide failing -> the whole carousel is abandoned (caller falls back
    to a single card) — a half-carousel is worse than none."""
    pack = split_into_slides(post, kit)
    if not pack:
        return None
    brand = brand_payload(account, kit)
    total = len(pack["slides"]) + 2  # cover + content + cta
    jobs = [("carousel_cover", {"text": pack["cover"], "total": total})]
    jobs += [("carousel_slide", {"text": s, "index": i + 2, "total": total})
             for i, s in enumerate(pack["slides"])]
    jobs.append(("carousel_cta", {**pack["cta"], "index": total, "total": total}))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    names: list[str] = []
    for n, (template, data) in enumerate(jobs, 1):
        png = renderer.render(template, data, brand)
        if png is None:
            logger.warning("Carousel slide %d/%d failed — falling back to a "
                           "single card.", n, total)
            return None
        names.append(_save(png, f"post{post['id']}-{stamp}-slide{n}.png").name)

    memory.update_post_meta(post["id"], {"visual": names[0],
                                         "visual_slides": names},
                            db_path=db_path)
    logger.info("Carousel for #%d: %d slides.", post["id"], total)
    return str(Path(settings.visuals_dir) / names[0])


def generate_for_post(post_id: int, db_path: Optional[str] = None,
                      renderer=None, template: Optional[str] = None) -> Optional[str]:
    """Render the branded visual for a post; saves PNG(s) into visuals_dir and
    returns the (cover) path (None when disabled/failed — never raises).
    Multi-idea formats (thread / linkedin_post / newsletter) become square
    carousels; everything else gets a single 16:9 card. An explicit `template`
    overrides auto-pick (the review card's swap-template control)."""
    if not settings.visuals_enabled:
        return None
    post = memory.get_post(post_id, db_path=db_path)
    if not post or not post["content"].strip():
        return None
    account = memory.get_account(post["account_id"], db_path=db_path) or {}
    kit = memory.get_brand_kit(post["account_id"], db_path=db_path)

    r = renderer or SatoriRenderer()

    if template is None and (post.get("format") or "") in CAROUSEL_FORMATS:
        cover = generate_carousel(post, account, kit, r, db_path=db_path)
        if cover:
            return cover  # carousel done; otherwise fall through to a card

    auto_template, data = choose_template(post)
    if template and template != auto_template:
        # swapping template: rebuild the data shape the target template expects
        text = data.get("text") or " ".join(
            filter(None, [data.get("stat"), data.get("context")]))
        if template == "stat_highlight":
            stat = extract_stat(text)
            data = {"stat": stat or "", "context": text.replace(stat, "").strip(" .—–:,-")
                    if stat else text}
        elif template == "quote_card":
            data = {"text": text}
        else:
            data = {"title": "", "text": text}
    template = template or auto_template
    brand = brand_payload(account, kit)
    png = r.render(template, data, brand)
    used = template
    if png is None:
        png = PillowRenderer().render(template, data, brand)
        used = f"{template}(pillow-fallback)"
    if png is None:
        return None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = _save(png, f"post{post_id}-{stamp}.png")
    memory.update_post_meta(post_id, {"visual": path.name}, db_path=db_path)
    logger.info("Visual for #%d: %s via %s", post_id, path.name, used)
    return str(path)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Render the visual for a post")
    ap.add_argument("post_id", type=int)
    args = ap.parse_args()
    memory.init_db()
    print(generate_for_post(args.post_id) or "no visual produced")
