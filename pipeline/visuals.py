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


# ---- topic icons (the illustration layer; names match render/icons.mjs).
# First keyword match wins; format default as the fallback. Deterministic and
# free — the icon is decoration, not meaning, so a near-miss is harmless.
_ICON_KEYWORDS = (
    ("trending_down", ("crash", "fall", "drop", "decline", "slump", "loss")),
    ("trending_up", ("market", "stock", "sensex", "nifty", "growth", "rally",
                     "gdp", "economy", "inflation", "rbi", "fed", "rate")),
    ("landmark", ("parliament", "government", "minister", "election", "policy",
                  "congress", "bjp", "bill", "court order", "cabinet")),
    ("scale", ("court", "justice", "verdict", "legal", "lawsuit", "judge")),
    ("coins", ("crore", "funding", "revenue", "profit", "budget", "tax",
               "investment", "ipo")),
    ("trophy", ("match", "cricket", "ipl", "tournament", "champion", "medal",
                "world cup")),
    ("film", ("movie", "film", "box office", "trailer", "bollywood")),
    ("cpu", ("ai ", " ai", "tech", "software", "startup", "chip", "data")),
    ("leaf", ("climate", "environment", "carbon", "renewable", "monsoon")),
    ("heart", ("health", "hospital", "vaccine", "disease")),
    ("shield", ("defence", "defense", "security", "military", "border")),
    ("megaphone", ("campaign", "brand", "marketing", "launch", "advertis")),
    ("users", ("community", "workers", "employment", "jobs", "population")),
    ("globe", ("global", "world", "international", "export", "trade")),
)
_FORMAT_ICONS = {
    "data_story": "bar_chart", "prediction": "target", "explainer": "book",
    "hot_take": "zap", "callback": "check", "thread": "message_square",
    "counter_narrative": "scale", "evergreen": "book", "achievement": "trophy",
}


def pick_icon(post: dict) -> Optional[str]:
    """Icon name for the decor layer: content keywords first, format default
    second, None when nothing fits (the card just skips the glyph)."""
    text = (post.get("content") or "").lower()
    for icon, words in _ICON_KEYWORDS:
        if any(w in text for w in words):
            return icon
    return _FORMAT_ICONS.get(post.get("format") or "")


def choose_template(post: dict) -> tuple[str, dict]:
    """(template, data) for a post. quote-ish content gets the quote card,
    a post built on a number gets the stat card, everything else the insight
    card. Threads/long forms use their first line as the hook. Every card
    carries icon + seed for the decoration layer."""
    meta = post.get("meta_json") or {}
    tweets = meta.get("tweets") or []
    text = _strip_hashtags(tweets[0] if tweets else post["content"])
    decor = {"icon": pick_icon(post), "seed": post.get("id") or 0}

    fmt = post.get("format") or ""
    if fmt == "quote_context":
        return "quote_card", {"text": text, **decor}
    stat = extract_stat(text)
    if fmt == "data_story" or (stat and fmt in ("hot_take", "prediction", "callback")):
        if stat:
            context = text.replace(stat, "").strip(" .—–:,-")
            return "stat_highlight", {"stat": stat, "context": context or text,
                                      **decor}
    title = {"explainer": "Explained", "prediction": "Prediction",
             "callback": "Called it", "counter_narrative": "The other side",
             "evergreen": "Standing take", "linkedin_post": "",
             "newsletter": ""}.get(fmt, "")
    return "insight_card", {"title": title, "text": text, **decor}


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


def custom_font_dir() -> Path:
    return Path(settings.render_dir) / "fonts" / "custom"


def custom_font_key(account_id: Optional[int],
                    font_family: Optional[str]) -> Optional[str]:
    """The render service loads fonts/custom/acct{id}-{weight}.ttf when the
    kit says font_family='custom'. Missing file -> None, so the templates
    fall back to the bundled stack instead of rendering tofu."""
    if font_family != "custom" or not account_id:
        return None
    key = f"acct{account_id}"
    if any((custom_font_dir() / f"{key}-{w}.ttf").exists() for w in (400, 700)):
        return key
    return None


def brand_payload(account: dict, kit: Optional[dict],
                  post: Optional[dict] = None) -> dict:
    font_family = (kit or {}).get("font_family")
    # Emotion lives in meta_json; extract it so the visual layer can pick the
    # right gradient without a separate DB call.
    meta = (post or {}).get("meta_json") or {}
    if isinstance(meta, str):
        try:
            import json as _json
            meta = _json.loads(meta)
        except Exception:
            meta = {}
    return {
        "accent_color": (kit or {}).get("accent_color"),
        "secondary_color": (kit or {}).get("secondary_color"),
        "bg_style": (kit or {}).get("bg_style"),
        "font_family": font_family,
        "custom_font_key": custom_font_key(account.get("id"), font_family),
        "decor_style": settings.visuals_decor,
        "watermark_text": (kit or {}).get("watermark_text")
                          or (settings.ai_label or "").strip(),
        "handle": account.get("handle") or "",
        "logo": logo_asset((kit or {}).get("logo_url")),
        # content-aware theming — format + dominant emotion drive the gradient
        "content_format": (post or {}).get("format") or "",
        "content_emotion": meta.get("dominant_emotion") or meta.get("emotion") or "",
    }


# --------------------------------------------------------------------------- #
# Carousel splitting (pure function)
# --------------------------------------------------------------------------- #
CAROUSEL_FORMATS = ("thread", "linkedin_post", "newsletter")

# Formats that auto-try a visual blueprint (comparison/framework/timeline/
# process/list) before settling for a text card. Carousel formats keep their
# multi-slide treatment; punchy formats (hot_take) stay punchy. Any post can
# still request a blueprint explicitly via the template-swap control.
BLUEPRINT_AUTO_FORMATS = ("explainer", "evergreen", "counter_narrative")


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
            text = data.get("text") or data.get("title") or " ".join(
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


def _narrative_pack(post: dict, kit: Optional[dict],
                    db_path: Optional[str] = None) -> Optional[dict]:
    """A carousel pack built from the post's narrative ARC (hook → beats →
    payoff) instead of paragraph splitting. None -> caller falls back."""
    if not settings.narrative_carousel:
        return None
    try:
        from pipeline.narrative import NarrativeArcExtractor
        arc = NarrativeArcExtractor().arc_for(post, db_path=db_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Narrative arc failed for #%s: %s", post.get("id"), exc)
        return None
    if not arc:
        return None
    return {
        "cover": arc[0]["headline"],
        "slides": [{"headline": s["headline"], "text": s.get("body") or ""}
                   for s in arc[1:]],
        "cta": {"cta_text": (kit or {}).get("cta_text"),
                "cta_url": (kit or {}).get("cta_url")},
    }


def generate_carousel(post: dict, account: dict, kit: Optional[dict],
                      renderer, db_path: Optional[str] = None) -> Optional[str]:
    """Render cover + content slides + CTA as separate square PNGs. Records
    every slide in post meta (visual_slides) and returns the cover's path.
    Narrative arc first (a STORY with a hook and a payoff), paragraph
    splitting as the always-works fallback. Any slide failing -> the whole
    carousel is abandoned (caller falls back to a single card) — a
    half-carousel is worse than none."""
    pack, mode = _narrative_pack(post, kit, db_path), "carousel_narrative"
    if not pack:
        pack, mode = split_into_slides(post, kit), "carousel_split"
    if not pack:
        return None
    brand = brand_payload(account, kit, post)
    total = len(pack["slides"]) + 2  # cover + content + cta
    jobs = [("carousel_cover", {"text": pack["cover"], "total": total})]
    for i, s in enumerate(pack["slides"]):
        data = dict(s) if isinstance(s, dict) else {"text": s}
        jobs.append(("carousel_slide", {**data, "index": i + 2, "total": total}))
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
                                         "visual_slides": names,
                                         "visual_template": mode},
                            db_path=db_path)
    logger.info("Carousel for #%d: %d slides via %s.", post["id"], total, mode)
    return str(Path(settings.visuals_dir) / names[0])


VALID_SIZES = ("square", "story")     # default (None) = 16:9 wide


def generate_for_post(post_id: int, db_path: Optional[str] = None,
                      renderer=None, template: Optional[str] = None,
                      size: Optional[str] = None) -> Optional[str]:
    """Render the branded visual for a post; saves PNG(s) into visuals_dir and
    returns the (cover) path (None when disabled/failed — never raises).
    Multi-idea formats (thread / linkedin_post / newsletter) become square
    carousels; everything else gets a single 16:9 card. An explicit `template`
    overrides auto-pick (the review card's swap-template control); `size`
    ('square' for IG feed, 'story' for 9:16) re-renders the same card on a
    different canvas."""
    if not settings.visuals_enabled:
        return None
    post = memory.get_post(post_id, db_path=db_path)
    if not post or not post["content"].strip():
        return None
    account = memory.get_account(post["account_id"], db_path=db_path) or {}
    kit = memory.get_brand_kit(post["account_id"], db_path=db_path)
    size = size if size in VALID_SIZES else None
    suffix = f"-{size}" if size else ""

    r = renderer or SatoriRenderer()

    if template == "hero_card" and size is None:
        # the V2 design agent (imagery underneath, Satori text on top);
        # falls through to a flat card when no backend/refs are available.
        # Size variants skip the agent and use the procedural hero directly.
        from pipeline import design
        hero = design.generate_hero(post_id, db_path=db_path, renderer=r)
        if hero:
            return hero
        template = None

    def _render_structured(tmpl: str, spec: dict) -> Optional[str]:
        """Render an extracted structure (chart/blueprint) and save it."""
        brand = brand_payload(account, kit, post)
        data = {**spec, "seed": post.get("id") or 0}
        if size:
            data["_size"] = size
        png = r.render(tmpl, data, brand)
        if png is None:
            png = PillowRenderer().render(tmpl, data, brand)
        if png is None:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = _save(png, f"post{post_id}-{stamp}{suffix}.png")
        # size variants live beside the primary visual, never replace it
        key = f"visual_{size}" if size else "visual"
        meta = {key: path.name}
        if not size:
            meta["visual_template"] = tmpl
        memory.update_post_meta(post_id, meta, db_path=db_path)
        logger.info("Visual for #%d: %s via %s", post_id, path.name, tmpl)
        return str(path)

    # visual analytics bias: templates this account keeps rejecting are
    # avoided on the AUTOMATIC paths only — an explicit ask always wins.
    try:
        from pipeline.visual_prefs import shunned_templates
        shunned = shunned_templates(post["account_id"], db_path=db_path) \
            if template is None else set()
    except Exception:  # noqa: BLE001
        shunned = set()

    # data visualization: an explicit chart_card request, or a data_story on
    # auto-pick, tries the chart spec (cached on the post; one Claude call
    # max, behind the free numeric gate). No series -> normal card path.
    if template == "chart_card" or (template is None
                                    and post.get("format") == "data_story"
                                    and "chart_card" not in shunned):
        try:
            from pipeline.charts import ChartExtractor
            spec = ChartExtractor().spec_for(post, db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chart path failed for #%d: %s", post_id, exc)
            spec = None
        if spec:
            out = _render_structured("chart_card", spec)
            if out:
                return out
        if template == "chart_card":
            template = None       # explicit ask but no series: auto-pick card

    # visual blueprints: comparison/framework/timeline/process/list — the
    # structures top creators actually post. Explicit template swap extracts
    # that type; auto-eligible formats let Claude pick (or decline). The
    # blueprint (or the miss) is cached on the post — one call max.
    from pipeline.blueprint import TEMPLATE_FOR, TYPE_FOR
    want = TYPE_FOR.get(template or "")
    if want or (template is None
                and post.get("format") in BLUEPRINT_AUTO_FORMATS):
        try:
            from pipeline.blueprint import BlueprintExtractor
            bp = BlueprintExtractor().blueprint_for(post, want=want,
                                                    db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Blueprint path failed for #%d: %s", post_id, exc)
            bp = None
        if bp and (want or TEMPLATE_FOR[bp["type"]] not in shunned):
            out = _render_structured(TEMPLATE_FOR[bp["type"]], bp)
            if out:
                return out
        if want:
            template = None       # explicit ask, no structure: auto-pick card

    # carousels are already square; size variants apply to single cards only
    if template is None and size is None \
            and (post.get("format") or "") in CAROUSEL_FORMATS:
        cover = generate_carousel(post, account, kit, r, db_path=db_path)
        if cover:
            return cover  # carousel done; otherwise fall through to a card

    auto_template, data = choose_template(post)
    if template is None and auto_template == "insight_card":
        # Visual Genome: when the generic card is the pick, use the template
        # this account demonstrably prefers instead (evidence-gated).
        try:
            from pipeline.visual_prefs import better_generic_card
            preferred = better_generic_card(post["account_id"], db_path=db_path)
        except Exception:  # noqa: BLE001
            preferred = None
        if preferred:
            template = preferred
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
            data = {"title": "", "text": text,
                    "seed": post.get("id") or 0}
    template = template or auto_template
    if size:
        data["_size"] = size
    brand = brand_payload(account, kit, post)
    png = r.render(template, data, brand)
    used = template
    if png is None:
        png = PillowRenderer().render(template, data, brand)
        used = f"{template}(pillow-fallback)"
    if png is None:
        return None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = _save(png, f"post{post_id}-{stamp}{suffix}.png")
    key = f"visual_{size}" if size else "visual"
    meta_update = {key: path.name}
    if not size:
        meta_update["visual_template"] = template
    memory.update_post_meta(post_id, meta_update, db_path=db_path)
    logger.info("Visual for #%d: %s via %s", post_id, path.name, used)
    return str(path)


# --------------------------------------------------------------------------- #
# Visual A/B: alternates (the choose-the-right-visual layer)
# --------------------------------------------------------------------------- #
def _alternate_candidates(post: dict) -> list:
    """Templates this post can render WITHOUT any new Claude call: cached
    structures (chart spec / blueprint) plus the always-free style cards.
    The A/B engine is deliberately zero-marginal-cost."""
    meta = post.get("meta_json") or {}
    out = []
    from pipeline.charts import validate_spec
    if validate_spec(meta.get("chart")):
        out.append("chart_card")
    from pipeline.blueprint import TEMPLATE_FOR, validate_blueprint
    bp = validate_blueprint(meta.get("blueprint"))
    if bp:
        out.append(TEMPLATE_FOR[bp["type"]])
    out.append("hero_card")                       # procedural art: free
    if extract_stat(post.get("content") or ""):
        out.append("stat_highlight")
    out += ["insight_card", "quote_card"]
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def generate_alternates(post_id: int, k: int = 2,
                        db_path: Optional[str] = None,
                        renderer=None) -> list:
    """Render up to k alternate visual approaches for a draft, beyond the
    primary already on it. Returns [{"template", "file"}]; recorded in post
    meta (visual_alternates). The human's eventual pick (via the existing
    swap control) updates visual_template — which is exactly the preference
    signal the Visual Genome learns from. Zero Claude calls by construction."""
    if not settings.visuals_enabled:
        return []
    post = memory.get_post(post_id, db_path=db_path)
    if not post:
        return []
    account = memory.get_account(post["account_id"], db_path=db_path) or {}
    kit = memory.get_brand_kit(post["account_id"], db_path=db_path)
    meta = post.get("meta_json") or {}
    primary = meta.get("visual_template")

    candidates = [t for t in _alternate_candidates(post) if t != primary]
    # genome ordering: the account's proven winners come first
    try:
        from pipeline.visual_prefs import preferred_templates
        ranking = preferred_templates(post["account_id"], db_path=db_path)
        order = {t: i for i, t in enumerate(ranking)}
        candidates.sort(key=lambda t: order.get(t, len(order)))
    except Exception:  # noqa: BLE001
        pass

    r = renderer or SatoriRenderer()
    brand = brand_payload(account, kit, post)
    text = _strip_hashtags((meta.get("tweets") or [post["content"]])[0])
    seed = post.get("id") or 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    from pipeline.blueprint import TEMPLATE_FOR, validate_blueprint
    from pipeline.charts import validate_spec
    out = []
    for tmpl in candidates[: max(0, k)]:
        if tmpl == "chart_card":
            data = {**validate_spec(meta.get("chart")), "seed": seed}
        elif tmpl in TEMPLATE_FOR.values():
            data = {**validate_blueprint(meta.get("blueprint")), "seed": seed}
        elif tmpl == "stat_highlight":
            stat = extract_stat(text) or ""
            data = {"stat": stat, "seed": seed,
                    "context": text.replace(stat, "").strip(" .—–:,-") or text}
        else:                                     # hero / insight / quote
            data = {"text": text, "title": "", "seed": seed,
                    "icon": pick_icon(post)}
        png = r.render(tmpl, data, brand)
        if png is None:
            continue                              # alternates never hard-fail
        name = _save(png, f"post{post_id}-{stamp}-alt-{tmpl}.png").name
        out.append({"template": tmpl, "file": name})

    if out:
        memory.update_post_meta(post_id, {"visual_alternates": out},
                                db_path=db_path)
        logger.info("Alternates for #%d: %s", post_id,
                    [a["template"] for a in out])
    return out


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Render the visual for a post")
    ap.add_argument("post_id", type=int)
    args = ap.parse_args()
    memory.init_db()
    print(generate_for_post(args.post_id) or "no visual produced")
