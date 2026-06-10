"""
evergreen.py — the evergreen / thought-leadership format (CLAUDE.md format #11).

Every other format in the pipeline reacts to a signal. Evergreen is the
opposite: no news peg, just this account's strongest recurring argument,
distilled into a standalone post. It exists for slow news days, for feed
consistency, and because the takes you've repeated across months ARE your
brand — the stance memory already knows which ones they are.

HOW THE TOPIC IS PICKED (no model call needed):
  * explicit topic ("/evergreen fiscal policy") wins, always;
  * otherwise the account's most-recurring stance_history topic that hasn't
    had an evergreen drafted in the last 14 days (don't repeat yourself);
  * otherwise the account's configured preferred topics;
  * with no memory and no topics, it declines honestly.

The draft itself uses the normal machinery: memory context (your past
positions on the topic ARE the content), persona gate, persistence into the
review lane, Telegram push. Triggered on demand — /evergreen on Telegram or
`python -m pipeline.evergreen` — never on a schedule; nobody needs automated
filler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from pipeline import memory, poster
from pipeline.context import ContextRetriever
from pipeline.generator import ContentGenerator
from style.crowd import effective_genome
from style.scorer import PersonaConsistencyScorer

logger = logging.getLogger("evergreen")

REPEAT_GUARD_DAYS = 14  # don't auto-pick a topic evergreened this recently


class EvergreenGenerator:
    """Drafts a no-news-peg opinion post from the account's stance memory."""

    def __init__(self, client: Any = None, model: Optional[str] = None,
                 db_path: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model
        self.db_path = db_path

    # ----------------------------------------------------------- topic pick
    def _recently_evergreened(self, account_id: int) -> set:
        since = (datetime.now(timezone.utc)
                 - timedelta(days=REPEAT_GUARD_DAYS)).isoformat()
        topics = set()
        for p in memory.get_posts(account_id=account_id, db_path=self.db_path):
            if p["format"] == "evergreen" and p["created_at"] > since:
                t = (p.get("meta_json") or {}).get("evergreen_topic")
                if t:
                    topics.add(t)
        return topics

    def pick_topic(self, account: dict) -> Optional[dict]:
        """Returns {"topic": str, "stance": str|None} or None if nothing to say."""
        recent = self._recently_evergreened(account["id"])
        for row in memory.top_stance_topics(account["id"], limit=8, db_path=self.db_path):
            if row["topic"] not in recent:
                return {"topic": row["topic"], "stance": row["latest_stance"]}
        for t in (account.get("topics") or []):
            slug = t.strip().lower().replace(" ", "-")
            if slug and slug not in recent:
                return {"topic": slug, "stance": None}
        return None

    # ----------------------------------------------------------------- draft
    def generate_for(self, account: dict, topic: Optional[str] = None) -> Optional[dict]:
        """One evergreen draft for the account. Returns the draft dict (with
        post_id) or None when there's no voice/topic to work with."""
        dna = memory.get_style_dna(account["id"], db_path=self.db_path)
        if not dna:
            logger.warning("[%s] no Style DNA — evergreen needs a voice first.",
                           account.get("handle"))
            return None
        if topic:
            picked = {"topic": topic.strip().lower().replace(" ", "-"), "stance": None}
        else:
            picked = self.pick_topic(account)
        if not picked:
            logger.info("[%s] nothing to evergreen — no stances or topics yet.",
                        account.get("handle"))
            return None

        genome = effective_genome(dna["genome_a"], dna["genome_b"], dna["blend"])
        readable = picked["topic"].replace("-", " ")
        signal = {
            "title": f"(evergreen — no news peg) Your standing argument on {readable}",
            "source_name": "your own stance memory",
            "angle": picked["stance"] or f"your distilled position on {readable}",
        }
        ctx = ContextRetriever(db_path=self.db_path).context_for(
            {"title": readable, "topic": picked["topic"]}, account)

        gen = ContentGenerator(client=self._client, model=self.model)
        scorer = (PersonaConsistencyScorer(client=self._client, model=self.model)
                  if self._client else PersonaConsistencyScorer())
        draft = gen.generate_checked(
            signal, genome, fmt="evergreen", scorer=scorer,
            account_id=account["id"], persist=True, db_path=self.db_path,
            context=ctx,
        )
        if draft.get("post_id"):
            memory.update_post_meta(draft["post_id"],
                                    {"evergreen_topic": picked["topic"]},
                                    db_path=self.db_path)
            poster.TelegramNotifier().notify_draft(
                memory.get_post(draft["post_id"], db_path=self.db_path),
                f"EVERGREEN: {readable}")
            logger.info("[%s] evergreen drafted on %s", account.get("handle"),
                        picked["topic"])
        return draft


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Draft an evergreen post")
    ap.add_argument("--account", help="handle (default: first active)")
    ap.add_argument("--topic", help="topic override (default: picked from memory)")
    args = ap.parse_args()
    memory.init_db()
    accounts = memory.list_active_accounts()
    target = next((a for a in accounts if a["handle"] == args.account), None) \
        if args.account else (accounts[0] if accounts else None)
    if not target:
        print("No matching active account.")
    else:
        d = EvergreenGenerator().generate_for(target, topic=args.topic)
        print(d["content"] if d and not d.get("empty") else "No draft produced.")
