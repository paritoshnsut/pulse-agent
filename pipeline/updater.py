"""
updater.py — System 4, the memory updater. The write side of the memory moat.

When you mark a draft as actually POSTED (/posted on Telegram, or review.py
--posted), this runs once and files what just happened into long-term memory:

  * stance_history       <- the position you just took publicly on the topic
  * events_timeline      <- the event itself (deduped by URL — decision.run may
                            have already logged it when the signal fired)
  * predictions_tracker  <- if the post stakes a verifiable claim about the
                            future, it's recorded so the callback generator can
                            say "I called this" when the outcome lands

One Claude call per POSTED item only (not per draft — rejected drafts cost
nothing here), so the spend scales with what you actually publish.

measure-then-judge: the topic slug usually already exists, measured-ish, from
the decision agent's signal — Claude only refines it and does the two genuinely
qualitative jobs: compressing your post into a one-line stance, and deciding
whether it contains a real, checkable prediction (most posts don't; the prompt
is explicit that null is the common answer).

Failure posture: memory updates must never break the posting flow. on_posted
raises nothing in the wired paths — callers get a report dict or a logged error.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory

logger = logging.getLogger("updater")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You are the archivist for one social-media commentator. Given a post they "
    "just published and the story it reacted to, you file it: a topic slug, a "
    "one-line summary of the stance they took, and — only if the post makes a "
    "concrete, verifiable claim about the future — the prediction. You are "
    "strict about predictions: vague opinion ('this will end badly') is NOT a "
    "prediction; a checkable claim ('RBI will cut rates by March') is. Most "
    "posts contain none. Respond with ONLY a JSON object, no fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


class MemoryUpdater:
    """Files posted content into long-term memory. Client injectable."""

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

    # -------------------------------------------------------------- judging
    def _build_prompt(self, post_content: str, article: Optional[dict],
                      topic_hint: str) -> str:
        story = ""
        if article:
            story = (f"THE STORY IT REACTED TO:\n"
                     f"  {article.get('title')}\n"
                     f"  {article.get('description') or ''}\n\n")
        hint = f'(the signal scorer suggested topic "{topic_hint}" — keep it unless clearly wrong)\n' \
            if topic_hint else ""
        return (
            f"THE PUBLISHED POST:\n\"\"\"\n{post_content}\n\"\"\"\n\n"
            f"{story}{hint}"
            "Return JSON with exactly these keys:\n"
            '  "topic": 2-4 word kebab-case slug,\n'
            '  "stance": one sentence, third person, capturing the position taken '
            '(e.g. "thinks the 7.2% GDP headline hides weak manufacturing"),\n'
            '  "prediction": the exact verifiable future claim made, or null,\n'
            '  "horizon": rough timeframe of the prediction ("weeks", "by Q3 2026"), '
            "or null."
        )

    def extract(self, post_content: str, article: Optional[dict] = None,
                topic_hint: str = "") -> dict:
        msg = self.client.messages.create(
            model=self.model, max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": self._build_prompt(post_content, article, topic_hint)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            data = json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Updater returned non-JSON. Raw: %s", text[:200])
            data = {}
        return {
            "topic": (data.get("topic") or topic_hint or "general")
            .strip().lower().replace(" ", "-"),
            "stance": (data.get("stance") or "").strip(),
            "prediction": (data.get("prediction") or None),
            "horizon": (data.get("horizon") or None),
        }

    # --------------------------------------------------------------- filing
    def on_posted(self, post_id: int, db_path: Optional[str] = None) -> dict:
        """File a just-posted item into memory. Returns a report dict; on any
        failure returns {"ok": False, "error": ...} instead of raising, so the
        posting flow (Telegram reply, CLI) is never broken by the archivist."""
        try:
            post = memory.get_post(post_id, db_path=db_path)
            if not post:
                return {"ok": False, "error": f"no post #{post_id}"}
            article = (memory.get_article(post["article_id"], db_path=db_path)
                       if post.get("article_id") else None)
            signal = (memory.get_signal(post["signal_id"], db_path=db_path)
                      if post.get("signal_id") else None)
            topic_hint = (signal or {}).get("topic") or ""

            filed = self.extract(post["content"], article, topic_hint)
            url = post.get("posted_url") or (article or {}).get("url")

            if filed["stance"]:
                memory.log_stance(post["account_id"], filed["topic"],
                                  filed["stance"], source_url=url, db_path=db_path)
            # Ensure the event is on the timeline (no-op if decision.run
            # already seeded this URL when the signal fired).
            memory.seed_event(
                topic=filed["topic"],
                summary=(article or {}).get("title") or post["content"][:120],
                source_url=url,
                event_date=(article or {}).get("published_at"),
                db_path=db_path,
            )
            prediction_id = None
            if filed["prediction"]:
                prediction_id = memory.insert_prediction(
                    account_id=post["account_id"], post_id=post_id,
                    topic=filed["topic"], prediction=filed["prediction"],
                    horizon=filed["horizon"], db_path=db_path,
                )
            logger.info("Filed post #%d: topic=%s stance=%s prediction=%s",
                        post_id, filed["topic"], bool(filed["stance"]),
                        bool(filed["prediction"]))
            return {"ok": True, **filed, "prediction_id": prediction_id}
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory update failed for post #%s: %s", post_id, exc)
            return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Backfill memory from already-posted items")
    ap.add_argument("--post", type=int, help="file one specific post id")
    args = ap.parse_args()
    memory.init_db()
    up = MemoryUpdater()
    targets = ([memory.get_post(args.post)] if args.post
               else memory.get_posts(status="posted"))
    for p in targets:
        if p:
            print(f"#{p['id']}: {up.on_posted(p['id'])}")
