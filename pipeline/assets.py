"""assets.py — licensed portrait resolver (VISUALS.md Phase V3, Step 2).

Given a named person/org, fetch a clean, LICENSED portrait from Wikipedia's
REST summary API — the same endpoint watch/trends.py already uses — and return
it as the {src, width, height} data-URL shape Satori needs. Wikipedia's lead
image is editor-curated (the official portrait ~80% of the time) and licensed
(CC / public-domain), unlike press-agency photos. Keyless, no rate limit for
reasonable use.

Honest scope (stated in VISUALS.md): this resolves PORTRAITS OF NAMED
people/orgs, never the specific event scene — only press agencies hold that.
Any miss → None and the caller keeps today's card (the safe default across V3).

Cost posture: per-name in-process cache, negative results (a 404 page) cached
too so a missing entity is never re-fetched. A transient network failure is
NOT cached (retry next render). No Claude calls — pure HTTP + Pillow.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Optional

import requests

logger = logging.getLogger("assets")

WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
USER_AGENT = "PulseAgent/1.0 (autonomous content tool; +https://github.com/paritoshnsut/pulse-agent)"
_MAX_DIM = 1000  # cap the portrait so the base64 data-URL stays render-friendly

# name(lowercased) -> asset dict or None. None is a real (negative) answer for a
# 404 page; transient failures return None WITHOUT caching so they retry.
_CACHE: dict[str, Optional[dict]] = {}
_SYMBOL_CACHE: dict[str, Optional[dict]] = {}

# Wikimedia Commons search → a CC/PD-licensed concept image (Capitol, flag, a
# parliament building) for the storytelling backdrop. Only licenses that permit
# reuse; the credit string is carried so CC-BY attribution can be shown.
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_OK_LICENSE = ("public domain", "cc0", "cc-by", "cc by", "attribution",
               "no restrictions")


def _to_asset(raw: bytes) -> Optional[dict]:
    """Image bytes → {src(dataURL), width, height}, downscaled + re-encoded so a
    multi-MB Wikipedia original doesn't bloat the payload. None if unreadable
    (e.g. an SVG logo Pillow can't open) — the caller falls back."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        if max(img.width, img.height) > _MAX_DIM:
            img.thumbnail((_MAX_DIM, _MAX_DIM))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85)
            raw = buf.getvalue()
            return {"src": "data:image/jpeg;base64," + base64.b64encode(raw).decode(),
                    "width": img.width, "height": img.height}
        mime = f"image/{(img.format or 'jpeg').lower()}"
        return {"src": f"data:{mime};base64," + base64.b64encode(raw).decode(),
                "width": img.width, "height": img.height}
    except Exception as exc:  # noqa: BLE001
        logger.debug("portrait bytes unreadable: %s", exc)
        return None


def resolve_portrait(name: str, lang: str = "en", timeout: int = 8) -> Optional[dict]:
    """A named person/org → a licensed portrait {src, width, height}, or None.

    Prefers the full-resolution `originalimage` (capped to _MAX_DIM), falling
    back to the `thumbnail`. Only `type == 'standard'` pages are used so a
    disambiguation page never yields the wrong face — the wrong-image risk that
    makes scraping unacceptable for a news account."""
    key = (name or "").strip().lower()
    if not key:
        return None
    if key in _CACHE:
        return _CACHE[key]
    try:
        slug = name.strip().replace(" ", "_")
        resp = requests.get(WIKI_SUMMARY.format(lang=lang, title=slug),
                            headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if resp.status_code == 404:
            _CACHE[key] = None          # permanent: no such page
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("type", "standard") != "standard":
            _CACHE[key] = None          # disambiguation/list page — don't guess a face
            return None
        src = ((data.get("originalimage") or {}).get("source")
               or (data.get("thumbnail") or {}).get("source"))
        if not src:
            _CACHE[key] = None
            return None
        img = requests.get(src, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        img.raise_for_status()
        asset = _to_asset(img.content)
    except Exception as exc:  # noqa: BLE001
        logger.debug("portrait fetch failed for '%s': %s", name, exc)
        return None                     # transient: do NOT cache, retry later
    _CACHE[key] = asset
    return asset


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s or "").strip()


def resolve_symbol(query: str, width: int = 1200, timeout: int = 8) -> Optional[dict]:
    """A concept ("US Capitol", "Indian flag", "parliament building") → a
    CC/PD-licensed Commons image as {src, width, height, credit}, or None.

    This is the LEGAL background path: Commons images carry an explicit license,
    so (unlike a Google-Images press photo) reuse is permitted; CC-BY ones get a
    credit string the card can show. Filtered to reuse-permitting licenses and
    raster formats Pillow can read. Per-query cached (negative results too).

    `width` is the thumbnail width fetched — a small value (e.g. 420) yields a
    soft, slightly-blurred backdrop when the template upscales it (Satori has no
    blur filter, so downscaling is the blur)."""
    key = f"{(query or '').strip().lower()}@{width}"
    if not key.strip("@"):
        return None
    if key in _SYMBOL_CACHE:
        return _SYMBOL_CACHE[key]
    asset = None
    try:
        resp = requests.get(COMMONS_API, headers={"User-Agent": USER_AGENT},
                            timeout=timeout, params={
                                "action": "query", "format": "json",
                                "generator": "search", "gsrnamespace": 6,
                                "gsrsearch": query, "gsrlimit": 8,
                                "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
                                "iiurlwidth": width})
        resp.raise_for_status()
        pages = (resp.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime", "")
            if mime not in ("image/jpeg", "image/png"):
                continue
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName", {}).get("value", "")
                   or meta.get("UsageTerms", {}).get("value", "")).lower()
            if not any(ok in lic for ok in _OK_LICENSE):
                continue
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            img = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            img.raise_for_status()
            asset = _to_asset(img.content)
            if asset:
                artist = _strip_html(meta.get("Artist", {}).get("value", ""))[:60]
                short = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
                asset["credit"] = " / ".join(filter(None, [artist, short, "Wikimedia"]))
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("symbol fetch failed for '%s': %s", query, exc)
        return None
    _SYMBOL_CACHE[key] = asset
    return asset
