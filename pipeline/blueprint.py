"""
blueprint.py — the Visual Blueprint extractor (VISUALS.md "visual intelligence").

The premise (proven by chart_card): users don't need "images", they need
VISUAL COMMUNICATION of ideas — and the highest-performing organic visuals on
LinkedIn/X/Instagram are structured graphics, not artwork: comparisons,
frameworks, timelines, process flows, lists. LLMs are good at structure, bad
at design; so Claude extracts a typed blueprint and the deterministic Satori
templates own every pixel.

    post (+ source)
        ↓ one bounded Claude call: "which structure lives in this content?"
    {"type": "comparison" | "framework" | "timeline" | "process" | "list",
     ...typed fields}                                  (or null — most posts!)
        ↓ validated, clamped, CACHED in post meta ("blueprint")
    render via the matching template

Cost posture, identical to charts.py: the call is bounded, the answer —
including the explicit miss — is cached on the post, so a re-render or
template swap never pays twice. "Extract, never invent": every label and
point must come from the material. Any failure -> None, caller keeps the
normal card. A transient failure is NOT cached (retry next render).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.llm import tracked_create

logger = logging.getLogger("blueprint")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

# template name <-> blueprint type
BLUEPRINT_TYPES = ("comparison", "framework", "timeline", "process", "list")
TEMPLATE_FOR = {t: f"{t}_card" for t in BLUEPRINT_TYPES}
TYPE_FOR = {v: k for k, v in TEMPLATE_FOR.items()}

EXTRACT_PROMPT = """Does this content contain a STRUCTURE worth visualizing?
Pick the single best fit, or null if none genuinely fits:

- comparison: two things contrasted (X vs Y, before/after, old way/new way)
- framework: 3-5 named pillars/components of one idea
- timeline: 3-6 dated milestones (years, months, quarters)
- process: 3-5 sequential steps (do A, then B, then C)
- list: 3-6 parallel tips/mistakes/reasons/rules

Return JSON for the chosen type:

comparison: {{"type":"comparison","title":"...","left_title":"...","right_title":"...",
  "left_points":["2-4 short points"],"right_points":["same count as left"]}}
framework:  {{"type":"framework","title":"...","items":[{{"label":"...","desc":"one line"}}]}}
timeline:   {{"type":"timeline","title":"...","milestones":[{{"period":"2024","text":"..."}}]}}
process:    {{"type":"process","title":"...","steps":[{{"label":"...","desc":"one line or empty"}}]}}
list:       {{"type":"list","title":"...","items":["3-6 short items"]}}

If nothing fits, return exactly: null

Rules: every label, point and date must come from the content — extract,
never invent. Titles max 70 chars; points/labels max 60 chars; desc max 80.
Prefer null over forcing a weak structure. Return ONLY the JSON or null.

{want}POST:
{post}

SOURCE MATERIAL:
{article}"""


def _clamp(s: Any, n: int) -> str:
    return str(s or "").strip()[:n]


def validate_blueprint(bp: Any) -> Optional[dict]:
    """Normalize + sanity-check a candidate blueprint. None when unusable.
    Clamps lengths so no template ever overflows its canvas."""
    if not isinstance(bp, dict):
        return None
    t = bp.get("type")
    title = _clamp(bp.get("title"), 80)

    if t == "comparison":
        left = [_clamp(p, 64) for p in (bp.get("left_points") or []) if _clamp(p, 64)]
        right = [_clamp(p, 64) for p in (bp.get("right_points") or []) if _clamp(p, 64)]
        if not (2 <= len(left) <= 4 and 2 <= len(right) <= 4):
            return None
        return {"type": t, "title": title,
                "left_title": _clamp(bp.get("left_title"), 28) or "Before",
                "right_title": _clamp(bp.get("right_title"), 28) or "After",
                "left_points": left, "right_points": right}

    if t == "framework":
        items = [{"label": _clamp(i.get("label"), 40),
                  "desc": _clamp(i.get("desc"), 90)}
                 for i in (bp.get("items") or []) if isinstance(i, dict)
                 and _clamp(i.get("label"), 40)]
        if not (3 <= len(items) <= 5):
            return None
        return {"type": t, "title": title, "items": items}

    if t == "timeline":
        ms = [{"period": _clamp(m.get("period"), 12),
               "text": _clamp(m.get("text"), 70)}
              for m in (bp.get("milestones") or []) if isinstance(m, dict)
              and _clamp(m.get("period"), 12)]
        if not (3 <= len(ms) <= 6):
            return None
        return {"type": t, "title": title, "milestones": ms}

    if t == "process":
        steps = [{"label": _clamp(s.get("label"), 36),
                  "desc": _clamp(s.get("desc"), 80)}
                 for s in (bp.get("steps") or []) if isinstance(s, dict)
                 and _clamp(s.get("label"), 36)]
        if not (3 <= len(steps) <= 5):
            return None
        return {"type": t, "title": title, "steps": steps}

    if t == "list":
        items = [_clamp(i, 80) for i in (bp.get("items") or []) if _clamp(i, 80)]
        if not (3 <= len(items) <= 6):
            return None
        return {"type": t, "title": title, "items": items}

    return None


class BlueprintExtractor:
    """One Claude call -> a validated visual blueprint, cached on the post."""

    def __init__(self, client: Any = None, model: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model

    @property
    def client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def blueprint_for(self, post: dict, want: Optional[str] = None,
                      db_path: Optional[str] = None) -> Optional[dict]:
        """The blueprint for a post. `want` (a BLUEPRINT_TYPES member) is an
        explicit user ask via template swap — it biases the prompt but the
        'prefer null over a weak structure' rule still holds."""
        meta = post.get("meta_json") or {}
        if "blueprint" in meta:                # cached hit OR cached miss
            bp = validate_blueprint(meta["blueprint"])
            if bp is None or want is None or bp["type"] == want:
                return bp
            # cached blueprint is a different type than the explicit ask:
            # fall through and extract for the requested type.

        article_text = ""
        try:
            sig = memory.get_signal(post["signal_id"], db_path=db_path) \
                if post.get("signal_id") else None
            art = memory.get_article(sig["article_id"], db_path=db_path) \
                if sig and sig.get("article_id") else None
            if art:
                article_text = " ".join(filter(None, [
                    art.get("title"), art.get("description"),
                    (art.get("content") or "")[:2000]]))
        except Exception:  # noqa: BLE001
            pass

        want_line = (f"The user specifically wants a {want} visual — extract "
                     f"that structure if it honestly exists.\n\n") if want else ""
        try:
            msg = tracked_create(
                self.client, "blueprint", model=self.model, max_tokens=600,
                messages=[{"role": "user", "content": EXTRACT_PROMPT.format(
                    want=want_line,
                    post=(post.get("content") or "")[:2500],
                    article=article_text[:3000] or "(none)")}])
            text = _FENCE.sub("", "".join(
                getattr(b, "text", "") for b in msg.content).strip())
            raw = None if text.lower() == "null" else json.loads(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Blueprint extraction failed for post %s: %s",
                           post.get("id"), exc)
            return None            # transient: don't cache the miss

        bp = validate_blueprint(raw)
        self._cache(post, bp, db_path)
        return bp

    @staticmethod
    def _cache(post: dict, bp: Optional[dict], db_path: Optional[str]) -> None:
        try:
            if post.get("id"):
                memory.update_post_meta(post["id"], {"blueprint": bp},
                                        db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Blueprint cache write failed: %s", exc)
