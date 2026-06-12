"""
reddit.py — Reddit watch layer (keyless).

Reads a subreddit's hot listing via the public JSON endpoint:
    https://www.reddit.com/r/SUB/hot.json?limit=N
No OAuth needed for read-only public listings (a descriptive User-Agent is
required by Reddit etiquette). Posts become articles with source='reddit'.

REAL VELOCITY: unlike a news headline, a Reddit post exposes score (upvotes) and
age, so we can compute genuine engagement velocity = upvotes per hour, and map it
onto 0-10 as velocity_hint. The decision scorer uses this instead of the recency
proxy when present — this is the first place the velocity subscore becomes real.

Subreddits come from watch_list (kind='subreddit'), deduplicated.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

import requests

from pipeline import memory
from watch.reddit_auth import RedditAuth, default_auth

logger = logging.getLogger("watch.reddit")

HOT_JSON = "{base}/r/{sub}/hot.json"   # base filled from auth (oauth or www)


def velocity_from_upvotes(score: int, age_hours: float) -> float:
    """Map upvotes/hour to 0-10 via a log curve.

    Tuned so a post climbing fast scores high and a slow one scores low:
        ~10 upvotes/hr -> ~3.3 | ~100/hr -> ~6.6 | ~1000/hr -> ~10
    log10(uph+1)/3 * 10, clamped. Age floored at 0.25h so brand-new posts with a
    few votes don't show artificially infinite velocity.
    """
    uph = score / max(age_hours, 0.25)
    return max(0.0, min(10.0, math.log10(uph + 1) / 3.0 * 10.0))


def parse_listing(payload: dict, vertical=None, region=None, now=None) -> list[dict]:
    """Normalize a hot.json payload into article dicts (pure, no network)."""
    now = now or datetime.now(timezone.utc)
    out: list[dict] = []
    for child in payload.get("data", {}).get("children", []):
        d = child.get("data", {})
        if d.get("stickied"):
            continue  # pinned mod posts aren't news
        permalink = d.get("permalink")
        title = d.get("title")
        if not permalink or not title:
            continue
        created = d.get("created_utc")
        published_iso, vel = None, None
        if created:
            pub = datetime.fromtimestamp(created, tz=timezone.utc)
            published_iso = pub.isoformat()
            age_h = max(0.0, (now - pub).total_seconds() / 3600.0)
            vel = round(velocity_from_upvotes(int(d.get("score", 0)), age_h), 2)
        # prefer the linked article URL; fall back to the reddit thread
        external = d.get("url_overridden_by_dest")
        link = external if external and not external.endswith(("jpg", "png", "gif")) else \
            f"https://www.reddit.com{permalink}"
        out.append({
            "source": "reddit",
            "source_name": f"r/{d.get('subreddit')}",
            "vertical": vertical,
            "region": region,
            "url": link,
            "title": title.strip(),
            "description": (d.get("selftext") or "").strip()[:500] or None,
            "content": None,
            "author": d.get("author"),
            "published_at": published_iso,
            "velocity_hint": vel,
            "raw_json": {"score": d.get("score"), "num_comments": d.get("num_comments"),
                         "permalink": permalink, "subreddit": d.get("subreddit")},
        })
    return out


class RedditWatcher:
    def __init__(self, db_path: Optional[str] = None, timeout: int = 15,
                 limit: int = 25, auth: Optional[RedditAuth] = None):
        self.db_path = db_path
        self.timeout = timeout
        self.limit = limit
        self._auth = auth or default_auth()

    def fetch(self) -> list[dict]:
        articles: list[dict] = []
        for w in memory.get_watch(kind="subreddit", db_path=self.db_path):
            try:
                resp = requests.get(
                    HOT_JSON.format(base=self._auth.base_url, sub=w["ref"]),
                    params={"limit": self.limit},
                    headers=self._auth.headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                got = parse_listing(resp.json(), vertical=w.get("vertical"), region=w.get("region"))
                logger.info("Reddit r/%s -> %d posts", w["ref"], len(got))
                articles.extend(got)
            except Exception as exc:  # noqa: BLE001
                logger.error("Reddit fetch failed for r/%s: %s", w["ref"], exc)
        return articles

    def run(self) -> dict[str, int]:
        articles = self.fetch()
        new = dup = 0
        for art in articles:
            try:
                _, is_new = memory.insert_article(art, db_path=self.db_path)
                new += int(is_new); dup += int(not is_new)
            except Exception as exc:  # noqa: BLE001
                logger.error("Reddit persist failed %s: %s", art.get("url"), exc)
        logger.info("Reddit: %d new, %d dup", new, dup)
        return {"new": new, "duplicate": dup, "total": len(articles)}
