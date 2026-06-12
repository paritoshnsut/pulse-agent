"""
narrative.py — the Narrative Carousel engine (VISUALS.md "attention design").

Paragraph splitting makes a carousel out of TEXT. This makes one out of a
STORY. The difference is the arc top creators use deliberately:

    slide 1   the hook — why anyone would swipe
    slide 2+  one beat per slide, each with its own scannable headline
    last      the payoff — the takeaway / "what to do instead"
    (+ CTA)   appended by the existing carousel renderer from the brand kit

One bounded Claude call converts the post (+ source) into that arc; the
result — or the explicit miss — is CACHED in post meta ("narrative"), same
discipline as charts.py/blueprint.py: re-renders never pay twice, transient
failures aren't cached so the next render retries. Content that doesn't
carry an arc returns null and the carousel falls back to paragraph
splitting, which always works.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.llm import tracked_create

logger = logging.getLogger("narrative")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

MIN_SLIDES = 4          # hook + at least 2 beats + payoff
MAX_SLIDES = 8

ARC_PROMPT = """Turn this content into a swipeable carousel ARC (the structure
top creators use): a hook slide, then one beat per slide, then the payoff.

Return JSON:
{{"slides": [
  {{"kind": "hook", "headline": "the scroll-stopping opener, max 80 chars"}},
  {{"kind": "point", "headline": "scannable, max 40 chars",
    "body": "the substance, conversational, max 200 chars"}},
  ... 2-5 point slides, ONE idea each ...
  {{"kind": "payoff", "headline": "max 40 chars",
    "body": "the takeaway or what-to-do-instead, max 200 chars"}}
]}}

Rules:
- The hook creates tension or surprise — a question, a number, a confession.
  It must come FROM the content; never manufacture drama.
- Every beat must come from the content — extract, never invent.
- Each point slide carries exactly one idea. No "and also".
- The payoff resolves the hook. A reader who only sees slide 1 and the last
  slide should still get the story.
- If the content genuinely has no arc (it's one flat idea), return: null
Return ONLY the JSON or null.

POST:
{post}

SOURCE MATERIAL:
{article}"""


def _clamp(s: Any, n: int) -> str:
    return str(s or "").strip()[:n]


def validate_arc(arc: Any) -> Optional[list]:
    """Normalize + sanity-check a slide arc. None when unusable."""
    if not isinstance(arc, dict):
        return None
    slides = arc.get("slides") or []
    if not (MIN_SLIDES <= len(slides) <= MAX_SLIDES):
        return None
    out = []
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            return None
        head = _clamp(s.get("headline"), 90 if i == 0 else 48)
        if not head:
            return None
        kind = s.get("kind") if s.get("kind") in ("hook", "point", "payoff") \
            else ("hook" if i == 0 else "point")
        out.append({"kind": kind, "headline": head,
                    "body": _clamp(s.get("body"), 220)})
    if out[0]["kind"] != "hook":
        return None
    return out


class NarrativeArcExtractor:
    """One Claude call -> a validated slide arc, cached on the post."""

    def __init__(self, client: Any = None, model: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model

    @property
    def client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def arc_for(self, post: dict, db_path: Optional[str] = None) -> Optional[list]:
        meta = post.get("meta_json") or {}
        if "narrative" in meta:                # cached hit OR cached miss
            return validate_arc({"slides": meta["narrative"]}) \
                if meta["narrative"] else None

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

        try:
            msg = tracked_create(
                self.client, "narrative", model=self.model, max_tokens=900,
                messages=[{"role": "user", "content": ARC_PROMPT.format(
                    post=(post.get("content") or "")[:3000],
                    article=article_text[:2500] or "(none)")}])
            text = _FENCE.sub("", "".join(
                getattr(b, "text", "") for b in msg.content).strip())
            raw = None if text.lower() == "null" else json.loads(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Narrative arc extraction failed for post %s: %s",
                           post.get("id"), exc)
            return None            # transient: don't cache the miss

        arc = validate_arc(raw)
        self._cache(post, arc, db_path)
        return arc

    @staticmethod
    def _cache(post: dict, arc: Optional[list],
               db_path: Optional[str]) -> None:
        try:
            if post.get("id"):
                memory.update_post_meta(post["id"], {"narrative": arc},
                                        db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Narrative cache write failed: %s", exc)
