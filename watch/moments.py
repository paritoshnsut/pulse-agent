"""
moments.py (watcher) — surfaces upcoming marketing moments as articles.

The one PROACTIVE watcher: everything else reacts to the world; this one looks
at the calendar (see top-level moments.py) and says "Mother's Day is 16 days
out — start planning." Each moment occurrence is inserted ONCE, when its lead
window opens (dedup via the moment:// URL carrying the occurrence date), then
flows through the normal pipeline: the decision agent judges relevance to each
account's niche, brand-safety is trivially high, and the briefing/ideas bank
carries it forward. Zero network, zero keys, zero Claude calls here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import moments as calendar_mod

logger = logging.getLogger("watch.moments")


def _article(m: dict) -> dict:
    when = m["date"].strftime("%A, %B %-d")
    days = ("today" if m["days_out"] == 0
            else "tomorrow" if m["days_out"] == 1
            else f"in {m['days_out']} days")
    return {
        "source": "moments",
        "source_name": "Moments calendar",
        "vertical": m["vertical"],          # None = every account sees it
        "region": m["region"],              # None = everywhere
        "url": f"moment://{m['slug']}/{m['date'].isoformat()}",
        "title": f"{m['name']} is {days} ({when})",
        "description": (
            f"Planned marketing moment ({m['kind']}). {m['blurb']} "
            "This is a plan-ahead prompt, not breaking news — judge whether "
            "this account should build content for it."
        ),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "velocity_hint": None,
        "raw_json": {"slug": m["slug"], "kind": m["kind"],
                     "date": m["date"].isoformat(), "days_out": m["days_out"]},
    }


class MomentsWatcher:
    """Inserts in-window calendar moments as articles (idempotent daily run)."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def fetch(self, today=None) -> list[dict]:
        today = today or datetime.now(timezone.utc).date()
        return [_article(m) for m in calendar_mod.upcoming(today)]

    def run(self, today=None) -> dict[str, int]:
        from pipeline import memory
        articles = self.fetch(today)
        new = dup = 0
        for art in articles:
            _, is_new = memory.insert_article(art, db_path=self.db_path)
            new += int(is_new); dup += int(not is_new)
        if new:
            logger.info("moments: %d new planning prompts surfaced", new)
        return {"new": new, "duplicate": dup, "total": len(articles)}
