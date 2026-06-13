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

# Story category (the GPT-rules spec): drives the card's kicker label + (later)
# palette. Free-form is collapsed to the closest of these or "" if none fits.
STORY_TYPES = ("breaking_news", "person_news", "money_news", "data_news",
               "comparison", "timeline", "explainer", "quote", "prediction",
               "achievement", "controversy", "policy", "war_conflict", "sports")

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

3) STORY_TYPE — one of: breaking_news, person_news, money_news, data_news,
   comparison, timeline, explainer, quote, prediction, achievement,
   controversy, policy, war_conflict, sports. "" if none fits.

4) HEADLINE — the scroll-stopping line, understandable in ONE second.
   TABLOID-punchy, not magazine-clever. HARD LIMITS: 3-8 words, concrete,
   forceful, front-load the surprising fact, no trailing period.
   GOOD: "Trump's loyalist headed to India" · "Musk becomes world's first
   trillionaire" · "Odisha makes all education free".
   BAD (too magazine/literary — never write like this): "How X is rewriting
   the playbook" · "The quiet revolution in Y" · "What Z tells us about ...".

5) HIGHLIGHT — the 1-3 word phrase INSIDE the headline that matters most, to be
   colour-popped (e.g. "TRILLIONAIRE", "FREE", "INDIA"). MUST be an exact
   substring of the headline. "" if nothing deserves emphasis.

6) SUBHEADLINE — one short supporting line, max 8 words ("Now richer than most
   nations"). "" if the headline stands alone.

7) TAG — a tiny editorial pill that orients the viewer, 1-3 words, often a
   relation or label: "NEW ENVOY", "US → INDIA", "TRUMP ALLY", "₹1 LAKH CR",
   "KG TO PG". "" if none fits. (More specific than the story category.)

8) BIG_NUMBER — if ONE number IS the story (a record, net worth, ranking,
   percentage, count, money), the number formatted for a giant display:
   "$1 TRILLION", "300%", "64", "₹1 LAKH CR", "3rd". "" if no single number
   dominates the story.

9) SYMBOLS — 2-4 concrete, searchable visual concepts that set the SCENE behind
   the subject (buildings, flags, places, objects), most relevant first:
   ["United States Capitol", "Parliament House New Delhi", "American flag"].
   Must be generic and depictable (a landmark/flag/object), NEVER a specific
   copyrighted news scene. [] if nothing obvious.

Return ONLY JSON:
{{"entities": [{{"name": "...", "type": "person", "role": "subject"}}],
  "visual_strategy": "image_vs", "story_type": "breaking_news",
  "headline": "...", "highlight": "...", "subheadline": "...", "tag": "...",
  "big_number": "...", "symbols": ["...", "..."]}}

If the post has no named real-world subject and no data, still return a tight
headline + subheadline for a typography card:
{{"entities": [], "visual_strategy": "typography", "story_type": "",
  "headline": "...", "highlight": "", "subheadline": "...", "tag": "",
  "big_number": "", "symbols": []}}

Rules: extract names, never invent. Max 8 entities. One strategy. Headline 3-8
plain words. Never manufacture drama the post doesn't support.

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
    story = raw.get("story_type")
    if story not in STORY_TYPES:
        story = ""
    # Headline hard-trimmed to 9 words (tabloid-punchy); a long model answer is
    # truncated rather than rejected so a card still gets a tight line.
    headline = " ".join(_clamp(raw.get("headline"), 120).split()[:9])
    # highlight only survives if it's an exact substring of the headline (so the
    # template can colour-pop it safely); else dropped.
    highlight = _clamp(raw.get("highlight"), 40)
    if highlight and highlight.lower() not in headline.lower():
        highlight = ""
    symbols = [_clamp(s, 60) for s in (raw.get("symbols") or [])
               if isinstance(s, str) and s.strip()][:4]
    return {"entities": ents, "visual_strategy": strat, "story_type": story,
            "headline": headline, "highlight": highlight,
            "subheadline": _clamp(raw.get("subheadline"), 80),
            "tag": _clamp(raw.get("tag"), 24),
            "big_number": _clamp(raw.get("big_number"), 14),
            "symbols": symbols}


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
        cached = meta.get("visual_entities")
        # cached hit (incl. the typography verdict) — but a brief from before
        # the latest fields (headline/highlight/tag) existed is treated as a
        # miss so the post upgrades to the richer brief on its next render.
        if isinstance(cached, dict) and "symbols" in cached:
            return validate_visual_brief(cached)

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
