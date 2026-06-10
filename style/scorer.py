"""
scorer.py — the persona consistency scorer (CLAUDE.md Style DNA + rule #9).

Before a draft is shown to you (or posted), score it against Genome A so
off-voice content gets caught. The generator's generate_checked() uses this to
regenerate below the >70 gate.

measure-then-judge again:
  * Claude scores the 5 genuinely-qualitative axes (vocabulary, sentence rhythm,
    tone, topic/stance consistency, emotional register), each 0-100.
  * Python computes MECHANICAL adherence — things we can check exactly: length
    vs the voice's target, emoji-policy adherence, hashtag-style adherence. These
    don't enter the composite (they're hard pass/fail facts), but they're
    surfaced so a "looks fine" score can't hide a concrete style violation.

The composite is the mean of the 5 Claude axes. Bands (cleaned up from the
slightly overlapping ones in CLAUDE.md, with rule #9's >70 gate as the anchor):
    >= 70  pass
    60-69  regenerate once with tightened constraints
    < 60   flag for human review
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings

logger = logging.getLogger("scorer")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF]"
)
HASHTAG = re.compile(r"#\w+")
_INT = re.compile(r"(\d+)")

AXES = ("vocabulary", "sentence_rhythm", "tone", "stance_consistency", "emotional_register")

SYSTEM_PROMPT = (
    "You are a strict style auditor. You compare a draft post against a target "
    "voice profile and score how well it matches, axis by axis, from 0 to 100. "
    "You are not lenient: a competent but generic post that doesn't sound like "
    "THIS voice scores in the 40s-60s. Output ONLY a JSON object, no fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def mechanical_checks(text: str, genome: dict) -> dict:
    """Exact, non-hallucinated adherence facts about the draft vs the voice."""
    # length adherence vs the voice's avg target
    target = _INT.search(str(genome.get("avg_post_length", "")))
    target_len = int(target.group(1)) if target else None
    length_ratio = round(len(text) / target_len, 2) if target_len else None

    # emoji adherence
    wants_no_emoji = (genome.get("emoji_usage") or "none") == "none"
    has_emoji = bool(EMOJI.search(text))
    emoji_ok = (not has_emoji) if wants_no_emoji else True

    # hashtag adherence (case + count)
    style = (genome.get("hashtag_style") or "").lower()
    tags = HASHTAG.findall(text)
    case_ok = True
    if "lowercase" in style and tags:
        case_ok = all(t == t.lower() for t in tags)
    cap_m = _INT.search(style)
    count_ok = (len(tags) <= int(cap_m.group(1))) if cap_m else True
    no_tags_expected = ("none" in style or "rarely" in style)
    hashtag_ok = (len(tags) == 0) if no_tags_expected else (case_ok and count_ok)

    return {
        "length_ratio": length_ratio,        # ~1.0 is on target
        "emoji_ok": emoji_ok,
        "hashtag_ok": hashtag_ok,
        "char_count": len(text),
    }


class PersonaConsistencyScorer:
    """Scores drafts against Genome A. Anthropic client injectable for tests."""

    def __init__(self, client: Any = None, model: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model

    @property
    def client(self) -> Any:
        if self._client is None:
            settings.require_anthropic()
            from anthropic import Anthropic

            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def _build_prompt(self, text: str, genome: dict) -> str:
        return (
            f"TARGET VOICE PROFILE:\n{json.dumps(genome, ensure_ascii=False, indent=2)}\n\n"
            f"DRAFT POST:\n\"\"\"\n{text}\n\"\"\"\n\n"
            "Score the draft against the voice on each axis from 0 to 100, and "
            "name the single weakest axis with one concrete fix. Return JSON:\n"
            '  "vocabulary": 0-100 (word choice matches the voice),\n'
            '  "sentence_rhythm": 0-100 (length/cadence/fragments match),\n'
            '  "tone": 0-100 (sarcasm/combativeness/register match),\n'
            '  "stance_consistency": 0-100 (position fits the voice\'s known stances),\n'
            '  "emotional_register": 0-100 (dominant emotion matches the voice),\n'
            '  "weakest_axis": one of the axis names,\n'
            '  "weakest_axis_feedback": one concrete sentence on how to fix it.'
        )

    def score(self, text: str, genome: dict) -> dict:
        """Return per-axis scores, composite, mechanical checks, and feedback."""
        mech = mechanical_checks(text, genome)
        msg = self.client.messages.create(
            model=self.model, max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(text, genome)}],
        )
        raw_text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            data = json.loads(_strip_fence(raw_text))
        except json.JSONDecodeError:
            logger.error("Scorer returned non-JSON; failing safe to review. Raw: %s", raw_text[:200])
            return {
                "axes": {a: 0.0 for a in AXES}, "composite": 0.0,
                "mechanical": mech, "weakest_axis": None,
                "weakest_axis_feedback": "could not parse score; review manually",
            }
        axes = {a: _clamp(float(data.get(a, 0.0))) for a in AXES}
        composite = round(sum(axes.values()) / len(axes), 1)
        return {
            "axes": axes,
            "composite": composite,
            "mechanical": mech,
            "weakest_axis": data.get("weakest_axis"),
            "weakest_axis_feedback": (data.get("weakest_axis_feedback") or "").strip(),
        }

    @staticmethod
    def band(composite: float, gate: float = 70.0) -> str:
        """Map a composite to an action band."""
        if composite >= gate:
            return "pass"
        if composite >= 60:
            return "regenerate"
        return "flag_for_review"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    genome = {
        "avg_post_length": "180 chars", "emoji_usage": "none",
        "hashtag_style": "2-3, lowercase, at end", "sarcasm_level": "high",
    }
    sample = "RBI holds rates again. 'Inflation under control' — tell that to your grocery bill. let that sink in #rbi #economy"
    print(json.dumps(PersonaConsistencyScorer().score(sample, genome), indent=2, ensure_ascii=False))
