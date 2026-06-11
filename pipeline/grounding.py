"""
grounding.py — the verification shield, the honest version.

THE PROBLEM: in political content, one hallucinated number or invented quote
costs more reputation than a hundred good posts earn. Generators drift even
with "never fabricate" instructions.

THE HONEST SCOPE: no vector DB or fact-check API can make a claim TRUE, and
pretending otherwise is how tools get people burned. What CAN be verified
rigorously is GROUNDEDNESS — is every factual claim in the draft supported by
the source material the model was actually given (headline, summary,
transcript, your own memory records)? That catches the dangerous failure mode:
the model asserting things nobody told it.

HOW IT RUNS: one cheap Claude call per surviving draft, after the persona gate
and before persistence. Ungrounded claims are listed in the draft's metadata,
the draft is force-flagged needs_review, and the warning is shown in both the
Telegram alert and the web review card: "⚠️ verify before posting". The human
still decides — this is a spotlight, not a censor.

Claims are: numbers, statistics, quotes, attributions, specific events.
NOT claims: the author's opinions, predictions framed as predictions,
rhetorical flourishes. The auditor errs toward flagging when unsure.

Failure posture: if the check itself errors, the draft proceeds unflagged
(every draft gets human review in this product anyway) with the failure
logged — a broken auditor must not silently block the pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline.llm import tracked_create

logger = logging.getLogger("grounding")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You are a strict fact-grounding auditor for social media drafts. You are "
    "given SOURCE MATERIAL (what the writer actually knows) and a DRAFT. Your "
    "only job: find factual claims in the draft that the source material does "
    "NOT support. A factual claim is a specific assertion — a number, "
    "statistic, quote, attribution, date, or concrete event. Opinions, "
    "judgments, predictions framed as the author's own bet, and rhetorical "
    "flourishes are NOT claims. Paraphrase that preserves the source's meaning "
    "is grounded; a changed number or invented quote is not. When genuinely "
    "unsure whether the source supports a claim, flag it. Respond with ONLY a "
    "JSON object, no fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


def build_source_block(signal: dict, context: Optional[str] = None) -> str:
    """Everything the generator was shown — the grounding universe."""
    parts = [
        f"Headline: {signal.get('title') or ''}",
        f"Summary: {signal.get('description') or ''}",
        f"Suggested angle: {signal.get('angle') or ''}",
    ]
    if context:
        parts.append(f"Memory/context provided:\n{context}")
    return "\n".join(p for p in parts if p.split(":", 1)[-1].strip())


class GroundingChecker:
    """One call: draft + source -> list of unsupported claims."""

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

    def check(self, draft_text: str, source: str) -> dict:
        """Returns {"checked": bool, "ungrounded_claims": [str]}. checked=False
        means the auditor itself failed — the draft proceeds, humans review."""
        prompt = (
            f"SOURCE MATERIAL (everything the writer actually knows):\n"
            f"\"\"\"\n{source}\n\"\"\"\n\n"
            f"DRAFT:\n\"\"\"\n{draft_text}\n\"\"\"\n\n"
            "Return JSON:\n"
            '  "ungrounded_claims": array of the EXACT claims (quoted or '
            "closely paraphrased from the draft) that the source material does "
            "not support — empty array if every factual claim is grounded."
        )
        try:
            msg = tracked_create(self.client, "grounding",
                                 model=self.model, max_tokens=400,
                                 system=SYSTEM_PROMPT,
                                 messages=[{"role": "user", "content": prompt}])
            text = "".join(getattr(b, "text", "") for b in msg.content)
            data = json.loads(_strip_fence(text))
            claims = [c.strip() for c in (data.get("ungrounded_claims") or [])
                      if c and c.strip()]
            return {"checked": True, "ungrounded_claims": claims}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Grounding check failed (draft proceeds to human "
                           "review unflagged): %s", exc)
            return {"checked": False, "ungrounded_claims": []}
