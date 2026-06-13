"""
entities.py — the visual entity + strategy extractor (VISUALS.md Phase V3, Step 1).

The "brain" of the Visual Intelligence Engine. Before any portrait or
image-led card can be built (Steps 2-4), the system must know WHO and WHAT a
post is about and WHICH kind of visual fits. This module answers both in one
bounded, cached Claude call — the exact cost posture of charts.py and
blueprint.py:

    post (+ source article)
        ↓ one bounded call: "who/what is this about, and what visual fits?"
    {"entities": [{name, type, role}], "visual_strategy": "image_vs" | ...}
        ↓ validated, clamped, CACHED in post meta ("visual_entities")
    read by the render router (Step 4) to pick a portrait/product template

Cost posture, identical to blueprint.py: the call is bounded, the answer —
including the "typographic, no entities" verdict — is cached on the post, so a
re-render or template swap never pays twice. "Extract, never invent": every
entity must be NAMED in the material. Any hard failure -> None (caller keeps
the normal card); a transient failure is NOT cached (retry next render).

Scope discipline: this module only DECIDES. It fetches no images and changes
no rendering. Asset resolution (Step 2) and the render router (Step 4) are
separate, so the brain is testable and shippable on its own.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.llm import tracked_create

logger = logging.getLogger("entities")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

# What a fetched/rendered entity can be. Drives Step 2 asset resolution:
# person/org -> portrait, product -> product shot, location -> backdrop.
ENTITY_TYPES = ("person", "org", "product", "location")
ENTITY_ROLES = ("subject", "mentioned")

# The visual strategy enum (VISUALS.md Layer 3). Three already render today
# (typography / blueprint / data); the image_* + product + hybrid branches are
# what Steps 2-4 add. The render router (Step 4) reads this field.
VISUAL_STRATEGIES = ("typography", "blueprint", "data",
                     "image_portrait", "image_vs", "product", "hybrid")

EXTRACT_PROMPT = """Analyze this social post and decide its best VISUAL approach.

1) ENTITIES — the named real-world things the post is centrally about. Only
   extract names that ACTUALLY APPEAR in the content; never invent. For each:
   - name: the proper name ("Narendra Modi", "Apple", "iPhone 16", "New Delhi")
   - type: one of person | org | product | location
   - role: "subject" if the post is centrally about them, else "mentioned"

2) VISUAL_STRATEGY — the single best visual approach for this post:
   - image_vs: TWO+ people/orgs in opposition or together (a call, a clash,
     X responds to Y, a meeting) — the dual-portrait card
   - image_portrait: ONE person/org is the clear subject — a single hero portrait
   - product: a product or company launch/showcase is the subject
   - data: the post leads with numbers/statistics worth charting
   - blueprint: the post is a framework/comparison/timeline/list/process of ideas
   - typography: a pure opinion/quote/hot-take with no strong visual subject
   - hybrid: a person/product subject AND a key statistic both matter

Return ONLY JSON:
{{"entities": [{{"name": "...", "type": "person", "role": "subject"}}],
  "visual_strategy": "image_vs"}}

If the post has no named real-world subject and no data, return exactly:
{{"entities": [], "visual_strategy": "typography"}}

Rules: extract names, never invent. Max 8 entities. Choose exactly one strategy.

POST:
{post}

SOURCE MATERIAL:
{article}"""


def _clamp(s: Any, n: int) -> str:
    return str(s or "").strip()[:n]


def _infer_strategy(entities: list[dict]) -> str:
    """Deterministic fallback when the model's strategy is missing/invalid —
    derive it from the extracted SUBJECT entities (measure-then-judge: the
    countable inference stays in Python). Two+ people/orgs -> a vs card; one ->
    a portrait; a product -> product; otherwise typographic."""
    subjects = [e for e in entities if e["role"] == "subject"]
    people = [e for e in subjects if e["type"] in ("person", "org")]
    products = [e for e in subjects if e["type"] == "product"]
    if len(people) >= 2:
        return "image_vs"
    if len(people) == 1:
        return "image_portrait"
    if products:
        return "product"
    return "typography"


def validate_visual_brief(raw: Any) -> Optional[dict]:
    """Normalize + sanity-check a candidate brief. None only when the payload
    is structurally unusable (not a dict) — that's a transient miss the caller
    won't cache. A genuine "typographic, no entities" verdict is a VALID brief
    (cached), not a None: we looked, there's nothing to fetch.

    Clamps names and caps the list so Step 3 templates never overflow."""
    if not isinstance(raw, dict):
        return None
    ents: list[dict] = []
    for e in (raw.get("entities") or []):
        if not isinstance(e, dict):
            continue
        name = _clamp(e.get("name"), 80)
        etype = e.get("type")
        if not name or etype not in ENTITY_TYPES:
            continue
        role = e.get("role") if e.get("role") in ENTITY_ROLES else "mentioned"
        ents.append({"name": name, "type": etype, "role": role})
        if len(ents) >= 8:
            break
    strat = raw.get("visual_strategy")
    if strat not in VISUAL_STRATEGIES:
        strat = _infer_strategy(ents)
    return {"entities": ents, "visual_strategy": strat}


# A multi-word proper noun ("Narendra Modi") or an all-caps acronym ("RBI").
_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b|\b[A-Z]{2,6}\b")
# Capitalized function/opener words that aren't entities — so a sentence-initial
# "The"/"Why" doesn't read as a name in the cheap pre-gate.
_CAP_STOPWORDS = frozenset((
    "The", "A", "An", "This", "That", "These", "Those", "It", "We", "You",
    "I", "If", "But", "And", "So", "Or", "Why", "How", "What", "When", "Where",
    "Here", "There", "Your", "My", "Our", "Their", "His", "Her", "Its", "No",
    "Yes", "Not", "Now", "Then", "Stop", "Just", "Every", "Most", "Some",
))


def looks_entity_rich(text: str) -> bool:
    """Cheap, FREE pre-gate (no Claude call): does the text plausibly name a
    real-world subject? Step 4 uses this to SKIP the extraction call on clearly
    abstract opinion posts. Biased toward the cost decision, not correctness —
    a multi-word proper noun or an acronym, or ≥2 non-opener capitalized tokens.
    A false positive costs one bounded call; a false negative just falls back to
    today's card (the safe default everywhere in V3)."""
    text = (text or "").strip()
    if not text:
        return False
    if _PROPER_NOUN.search(text):
        return True
    tokens = re.findall(r"\b[A-Za-z][A-Za-z'\-]*\b", text)
    caps = sum(1 for tok in tokens
               if tok and tok[0].isupper() and tok not in _CAP_STOPWORDS)
    return caps >= 2


def _source_text(post: dict, db_path: Optional[str]) -> str:
    """The source article behind a post (title + description + lead content),
    so the extractor reads what the draft is reacting to, not just the draft.
    Best-effort: any failure -> '' and the post text alone is used."""
    try:
        sig = memory.get_signal(post["signal_id"], db_path=db_path) \
            if post.get("signal_id") else None
        art = memory.get_article(sig["article_id"], db_path=db_path) \
            if sig and sig.get("article_id") else None
        if art:
            return " ".join(filter(None, [
                art.get("title"), art.get("description"),
                (art.get("content") or "")[:1500]]))
    except Exception:  # noqa: BLE001
        pass
    return ""


class VisualEntityExtractor:
    """One Claude call -> a validated {entities, visual_strategy} brief, cached
    on the post. Mirrors BlueprintExtractor's lifecycle exactly."""

    def __init__(self, client: Any = None, model: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model

    @property
    def client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def brief_for(self, post: dict, db_path: Optional[str] = None) -> Optional[dict]:
        """The visual brief for a post: {entities, visual_strategy} or None.
        Cached on first extraction (hit OR the typographic verdict); only a
        structurally-broken response stays uncached so it retries."""
        meta = post.get("meta_json") or {}
        if "visual_entities" in meta:                 # cached hit (incl. typography)
            return validate_visual_brief(meta["visual_entities"])

        article_text = _source_text(post, db_path)
        try:
            msg = tracked_create(
                self.client, "visual_entities", model=self.model, max_tokens=400,
                messages=[{"role": "user", "content": EXTRACT_PROMPT.format(
                    post=(post.get("content") or "")[:2000],
                    article=article_text[:2500] or "(none)")}])
            text = _FENCE.sub("", "".join(
                getattr(b, "text", "") for b in msg.content).strip())
            raw = None if text.lower() == "null" else json.loads(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Visual-entity extraction failed for post %s: %s",
                           post.get("id"), exc)
            return None            # transient: don't cache the miss

        brief = validate_visual_brief(raw)
        self._cache(post, brief, db_path)
        return brief

    @staticmethod
    def _cache(post: dict, brief: Optional[dict], db_path: Optional[str]) -> None:
        try:
            if post.get("id"):
                memory.update_post_meta(post["id"], {"visual_entities": brief},
                                        db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Visual-entity cache write failed: %s", exc)
