"""
integrity.py — two pre-review judgment checks, both protection not censorship.

These run after a draft passes the persona gate and the grounding shield, and
like grounding they flag for the human rather than block. They're the
"co-pilot watching your back" layer.

  StanceArcGuard — does this draft CONTRADICT a position you've taken before?
    A flip-flop is the cardinal sin in political content: "you said the exact
    opposite in March" is the dunk that ends accounts. We already store every
    public stance (stance_history); this compares the draft against your past
    positions on the topic and flags genuine reversals. Free at cold start —
    only spends a Claude call when you actually HAVE prior stances on the
    topic. A real change of mind is allowed; the guard's job is to make sure
    it's deliberate, surfacing "you're reversing — say so on purpose."

  RiskSimulator — how could this be screenshotted, misread, or turned against
    you? One "red-team" call on high-stakes drafts that lists concrete
    backlash vectors and a risk level. The downside in politics is asymmetric;
    a 10-second check before a spicy post is cheap insurance. Targeted to FIRE
    and inherently-contrarian formats so the spend stays where stakes are high.

Both are failure-safe: if the check errors, the draft proceeds (humans review
everything here) with the failure logged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.context import extract_keywords
from pipeline.llm import tracked_create

logger = logging.getLogger("integrity")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


# --------------------------------------------------------------------------- #
# Stance arc guard
# --------------------------------------------------------------------------- #
ARC_SYSTEM = (
    "You guard one commentator's consistency. Given their PAST PUBLIC STANCES "
    "and a NEW DRAFT on the same topic, you find genuine contradictions — "
    "places where the draft argues the opposite of a position they've taken "
    "before. A sharper or softer version of the SAME position is not a "
    "contradiction; only a real reversal is. People are allowed to change "
    "their minds — your job is to catch UNINTENTIONAL flip-flops so the writer "
    "can own the change on purpose. Respond with ONLY a JSON object, no fences."
)


class StanceArcGuard:
    """Flags drafts that reverse a position the account has taken before."""

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

    def check(self, draft_text: str, account_id: int, topic: Optional[str],
              title: Optional[str] = None, db_path: Optional[str] = None) -> dict:
        """Returns {"checked": bool, "conflicts": [{"past","now"}]}. checked is
        False when there's nothing to check (no past stances) or the call
        failed — either way the draft proceeds, the human reviews."""
        keywords = extract_keywords(
            (topic or "").replace("-", " "), title, draft_text)
        stances = memory.find_stances(account_id, keywords, limit=6, db_path=db_path) \
            if keywords else []
        if not stances:
            return {"checked": False, "conflicts": []}
        past = "\n".join(f"- [{s['created_at'][:10]}] on {s['topic']}: {s['stance']}"
                         for s in stances)
        prompt = (
            f"PAST PUBLIC STANCES:\n{past}\n\n"
            f"NEW DRAFT:\n\"\"\"\n{draft_text}\n\"\"\"\n\n"
            "Return JSON:\n"
            '  "conflicts": array of {"past": the prior position quoted/'
            'paraphrased, "now": what the draft argues instead} — ONLY genuine '
            "reversals, empty array if the draft is consistent with all of them."
        )
        try:
            msg = tracked_create(self.client, "arc_guard",
                                 model=self.model, max_tokens=400,
                                 system=ARC_SYSTEM,
                                 messages=[{"role": "user", "content": prompt}])
            text = "".join(getattr(b, "text", "") for b in msg.content)
            data = json.loads(_strip_fence(text))
            conflicts = [c for c in (data.get("conflicts") or [])
                         if isinstance(c, dict) and c.get("now")]
            return {"checked": True, "conflicts": conflicts}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Arc guard failed (draft proceeds): %s", exc)
            return {"checked": False, "conflicts": []}


# --------------------------------------------------------------------------- #
# Backlash / risk simulator
# --------------------------------------------------------------------------- #
RISK_SYSTEM = (
    "You are a sharp political comms risk advisor. Given a draft post, you "
    "red-team it: how could it be screenshotted out of context, misread, "
    "factually nitpicked, or turned against the author by a hostile reply? "
    "You are concrete and unsentimental, but you do not invent risks that "
    "aren't there — a clean post is low risk and you say so. Respond with "
    "ONLY a JSON object, no fences."
)


class RiskSimulator:
    """Red-teams high-stakes drafts for backlash vectors before review."""

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

    def assess(self, draft_text: str, signal: Optional[dict] = None) -> dict:
        """Returns {"checked", "risk_level": low|medium|high, "vectors": [str]}."""
        prompt = (
            f"DRAFT POST:\n\"\"\"\n{draft_text}\n\"\"\"\n\n"
            "Red-team it. Return JSON:\n"
            '  "risk_level": "low" | "medium" | "high",\n'
            '  "vectors": array of 0-3 short, concrete ways this could backfire '
            "(empty if genuinely low risk)."
        )
        try:
            msg = tracked_create(self.client, "risk",
                                 model=self.model, max_tokens=350,
                                 system=RISK_SYSTEM,
                                 messages=[{"role": "user", "content": prompt}])
            text = "".join(getattr(b, "text", "") for b in msg.content)
            data = json.loads(_strip_fence(text))
            level = data.get("risk_level")
            if level not in ("low", "medium", "high"):
                level = "low"
            vectors = [v.strip() for v in (data.get("vectors") or []) if v and v.strip()]
            return {"checked": True, "risk_level": level, "vectors": vectors}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Risk simulator failed (draft proceeds): %s", exc)
            return {"checked": False, "risk_level": "low", "vectors": []}
