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


def brand_payload(account: dict, kit: Optional[dict]) -> dict:
    return {
        "accent_color": (kit or {}).get("accent_color"),
        "secondary_color": (kit or {}).get("secondary_color"),
        "bg_style": (kit or {}).get("bg_style"),
        "font_family": (kit or {}).get("font_family"),
        "watermark_text": (kit or {}).get("watermark_text")
                          or (settings.ai_label or "").strip(),
        "handle": account.get("handle") or "",
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
def generate_for_post(post_id: int, db_path: Optional[str] = None,
                      renderer=None) -> Optional[str]:
    """Render the branded visual for a post; saves PNG into visuals_dir and
    returns its filesystem path (None when disabled/failed — never raises)."""
    if not settings.visuals_enabled:
        return None
    post = memory.get_post(post_id, db_path=db_path)
    if not post or not post["content"].strip():
        return None
    account = memory.get_account(post["account_id"], db_path=db_path) or {}
    kit = memory.get_brand_kit(post["account_id"], db_path=db_path)

    template, data = choose_template(post)
    brand = brand_payload(account, kit)

    r = renderer or SatoriRenderer()
    png = r.render(template, data, brand)
    used = template
    if png is None:
        png = PillowRenderer().render(template, data, brand)
        used = f"{template}(pillow-fallback)"
    if png is None:
        return None

    out_dir = Path(settings.visuals_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"post{post_id}-{stamp}.png"
    path.write_bytes(png)
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
