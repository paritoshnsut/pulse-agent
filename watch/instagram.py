"""
instagram.py — Instagram inspiration layer (PLUGGABLE STUB, disabled by default).

WHY THIS IS A STUB, NOT A SCRAPER OF "FAMOUS IG PAGES":
The obvious brand-mode wish is "watch the Instagram accounts I admire and learn
from what's working." There is no clean, compliant, keyless way to do that:

  - Instagram has NO public read API for arbitrary accounts. The official Graph
    API only reaches (a) YOUR OWN business/creator account and (b) accounts you
    already manage — it cannot pull a competitor's or an admired brand's feed.
    Business Discovery returns a thin slice (recent media + counts) for public
    business accounts only, behind app review + a connected FB page.
  - Every "scrape any IG page" route relies on undocumented internal endpoints
    or headless browsers. These violate Meta's ToS, break without warning when
    Meta rotates its internals, and reliably get accounts/IPs/devices banned.
    Baking one in would hand brand accounts a fragile, ban-prone dependency
    dressed up as a feature — exactly the trap we refuse elsewhere (see
    watch/twitter.py).

So inspiration from the visual world flows through TWO honest paths instead:

  1. UPLOAD REFERENCES (the real V1 path). The user drops in screenshots/links
     of posts, ads, or layouts they admire — explicit, copyright-aware, zero
     scraping. Those references seed the V2 AI-imagery design agent
     (inspiration -> image-gen -> vision critique loop -> composite). See
     VISUALS.md. This keeps a human in the loop on *what* to be inspired by,
     mirroring how the text corpus separates "own" from "inspiration".

  2. THIS PLUGGABLE STUB, for the one compliant automated slice that exists:
     your OWN connected IG business account (post performance to feed the
     engagement learning loop) and, optionally, Business Discovery on public
     business accounts you legitimately want to benchmark. Both require the
     official Graph API + a token; until that's configured, fetch() returns [].

TO ENABLE: set IG_GRAPH_TOKEN (+ IG_BUSINESS_ID) in .env, subclass and
implement fetch() to return article dicts in the standard shape (see
_example_shape), then register it in the scheduler like the other watchers.
Treat discovered media as INSPIRATION references (route to the visuals
references store / corpus suggestions, human-gated) — never as auto-training.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("watch.instagram")


class InstagramWatcher:
    """Disabled by default. fetch() returns [] until the Graph API is configured.

    Enable only via the official path: your own connected business/creator
    account, or Business Discovery on public business accounts. No scraping of
    arbitrary 'famous pages' — that route is non-compliant and ban-prone (see
    module docstring). Discovered items are inspiration references, not training.
    """

    def __init__(self, db_path: Optional[str] = None, enabled: Optional[bool] = None):
        self.db_path = db_path
        # auto-enable only when a real Graph token is present; never by default
        self.token = os.getenv("IG_GRAPH_TOKEN", "").strip()
        self.business_id = os.getenv("IG_BUSINESS_ID", "").strip()
        self.enabled = bool(self.token) if enabled is None else enabled

    @staticmethod
    def _example_shape() -> dict:
        """The dict fetch() must produce per post, to match the pipeline.

        Note `intent: "inspiration"` — IG items are visual references for the
        design agent / corpus suggestions, not hard-news signals to react to.
        """
        return {
            "source": "instagram",
            "source_name": "@handle",
            "vertical": None,
            "region": None,
            "url": "https://www.instagram.com/p/SHORTCODE/",
            "title": "the caption (first line) — what the post is saying",
            "description": "full caption / our notes on why it's worth a look",
            "published_at": "ISO8601 UTC",
            "velocity_hint": None,   # likes+comments per hour mapped to 0-10, if known
            "media_url": "https://.../image.jpg",  # for the visuals references store
            "intent": "inspiration",
            "raw_json": {},
        }

    def fetch(self) -> list[dict]:
        if not self.enabled:
            logger.info(
                "Instagram watcher disabled (no IG_GRAPH_TOKEN configured). "
                "Use uploaded references for visual inspiration instead. Skipping."
            )
            return []
        raise NotImplementedError(
            "Implement fetch() with the official Instagram Graph API "
            "(your own business account, or Business Discovery on public "
            "business accounts). See module docstring — do NOT scrape arbitrary pages."
        )

    def run(self) -> dict:
        if not self.enabled:
            return {"new": 0, "duplicate": 0, "total": 0, "skipped": "disabled"}
        from pipeline import memory
        articles = self.fetch()
        new = dup = 0
        for art in articles:
            _, is_new = memory.insert_article(art, db_path=self.db_path)
            new += int(is_new); dup += int(not is_new)
        return {"new": new, "duplicate": dup, "total": len(articles)}
