"""
twitter.py — Twitter/X watch layer (PLUGGABLE STUB, disabled by default).

WHY THIS IS A STUB, NOT A BUILT FETCHER:
Twitter/X read access is no longer free. The official API v2 starts around
$100-200/month (Basic) and climbs to $5,000/month (Pro) for meaningful pull
volume. The only "cheap" routes are third-party scrapers that violate X's ToS,
break whenever X changes its internals, and can get accounts/IPs banned. Baking
one of those in would hand you a fragile, non-compliant dependency disguised as a
feature. So instead: a clean interface you implement with whatever access you
choose — or leave off entirely (Google Trends + Reddit + YouTube already cover
the real-time signal need per your instruction).

TO ENABLE: subclass TwitterWatcher, implement fetch() to return article dicts in
the standard shape (see _example_shape), register tracked accounts in watch_list
(kind='twitter_account'), and add it to the scheduler like the other watchers.
Recommended official path: tweepy with a Basic-tier bearer token.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("watch.twitter")


class TwitterWatcher:
    """Disabled by default. fetch() returns [] until you implement a backend."""

    def __init__(self, db_path: Optional[str] = None, enabled: bool = False):
        self.db_path = db_path
        self.enabled = enabled

    @staticmethod
    def _example_shape() -> dict:
        """The dict fetch() must produce per tweet, to match the pipeline."""
        return {
            "source": "twitter",
            "source_name": "@handle",
            "vertical": None,
            "region": None,
            "url": "https://x.com/handle/status/123",
            "title": "the tweet text (becomes the headline the scorer reads)",
            "description": None,
            "published_at": "ISO8601 UTC",
            "velocity_hint": None,   # likes+RTs per hour mapped to 0-10, if you have it
            "raw_json": {},
        }

    def fetch(self) -> list[dict]:
        if not self.enabled:
            logger.info("Twitter watcher disabled (no API access configured). Skipping.")
            return []
        raise NotImplementedError(
            "Implement fetch() with your chosen X API access. See module docstring."
        )

    def run(self) -> dict[str, int]:
        if not self.enabled:
            return {"new": 0, "duplicate": 0, "total": 0, "skipped": "disabled"}
        from pipeline import memory
        articles = self.fetch()
        new = dup = 0
        for art in articles:
            _, is_new = memory.insert_article(art, db_path=self.db_path)
            new += int(is_new); dup += int(not is_new)
        return {"new": new, "duplicate": dup, "total": len(articles)}
