"""
fatigue.py — the audience fatigue detector (CLAUDE.md intelligence #7).

Your audience follows you for range; the agent's nose for one hot topic can
narrow you into "the RBI guy" in a week. This module tracks how many
audience-facing posts (approved/edited/posted — drafts you rejected never
reached anyone) each account has per topic inside a sliding window, and the
process cycle SKIPS DRAFTING when a topic is saturated. That protects the
audience from repetition and your wallet from Claude calls that would be
rejected as "again?" anyway.

Defaults: more than FATIGUE_MAX_POSTS (3) on one topic slug inside
FATIGUE_WINDOW_HOURS (72) -> fatigued. Pure SQL counting — no model, no cost.
The topic slug comes from the decision agent's signal, so the same machinery
that files memory also powers freshness.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from pipeline import memory

logger = logging.getLogger("fatigue")


def topic_freshness(account_id: int, topic: Optional[str],
                    db_path: Optional[str] = None) -> dict:
    """Count + verdict for one (account, topic). Topicless signals (the
    decision model returned no slug) are never suppressed — unknown is not
    the same as stale."""
    if not topic:
        return {"topic": topic, "recent_posts": 0, "fatigued": False}
    since = (datetime.now(timezone.utc)
             - timedelta(hours=settings.fatigue_window_hours)).isoformat()
    n = memory.count_recent_posts_on_topic(account_id, topic, since, db_path=db_path)
    return {
        "topic": topic,
        "recent_posts": n,
        "fatigued": n >= settings.fatigue_max_posts,
    }


def is_fatigued(account_id: int, topic: Optional[str],
                db_path: Optional[str] = None) -> bool:
    return topic_freshness(account_id, topic, db_path=db_path)["fatigued"]


def freshness_multiplier(account_id: int, topic: Optional[str],
                         db_path: Optional[str] = None) -> float:
    """Fatigue folded into SCORING (not just the draft gate): saturated topics
    rank down before any Claude drafting money is spent.
    0-1 recent posts -> x1.0, 2 -> x0.85, >= max -> the configured floor."""
    n = topic_freshness(account_id, topic, db_path=db_path)["recent_posts"]
    if n >= settings.fatigue_max_posts:
        return settings.freshness_floor
    if n == 2:
        return 0.85
    return 1.0
