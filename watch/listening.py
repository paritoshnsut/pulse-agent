"""
listening.py — per-brand listening: custom feeds + keyword tracking.

The global catalog (sources.py) can never enumerate every brand's world. Nike
doesn't read "lifestyle (us)" — it reads sneaker trade press, its competitors'
newsrooms, and every mention of "Air Jordan". This module turns two watch_list
kinds into feed specs the existing NewsMonitor consumes:

    kind='rss_feed'    ref = any RSS url (trade press, competitor newsroom,
                       a Substack, a niche blog). label names it.
    kind='news_query'  ref = a keyword/phrase ("adidas samba", "Nike lawsuit",
                       your own brand name). Compiled to a Google News search
                       RSS url — keyless social-listening-lite that tracks ANY
                       topic, competitor, or brand mention across the news web.

Both ride the existing /api/watch endpoints (arbitrary kinds were already
allowed) and the existing watch_list dedup. vertical/region on the row stamp
the resulting articles, so per-account scoping keeps working. Adding a feed
here is the onboarding answer to "my category isn't in the catalog."
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus

# region -> Google News locale params. Default mirrors the catalog's US lean.
_GNEWS_LOCALE = {
    "india": "hl=en-IN&gl=IN&ceid=IN:en",
    "us": "hl=en-US&gl=US&ceid=US:en",
}


def google_news_rss_url(query: str, region: Optional[str] = None) -> str:
    """Keyless Google News search RSS for a keyword/phrase."""
    locale = _GNEWS_LOCALE.get((region or "").lower(), _GNEWS_LOCALE["us"])
    return f"https://news.google.com/rss/search?q={quote_plus(query.strip())}&{locale}"


def custom_feed_specs(db_path: Optional[str] = None) -> list[dict]:
    """watch_list rows (rss_feed + news_query) as NewsMonitor feed specs."""
    from pipeline import memory

    specs: list[dict] = []
    for row in memory.get_watch(kind="rss_feed", db_path=db_path):
        specs.append({"url": row["ref"], "name": row["label"] or row["ref"],
                      "vertical": row["vertical"], "region": row["region"]})
    for row in memory.get_watch(kind="news_query", db_path=db_path):
        specs.append({"url": google_news_rss_url(row["ref"], row["region"]),
                      "name": row["label"] or f"News: {row['ref']}",
                      "vertical": row["vertical"], "region": row["region"]})
    return specs


def merge_feed_specs(catalog: list[dict], custom: list[dict]) -> list[dict]:
    """Catalog + custom, deduplicated by url (custom never double-fetches a
    feed already in the catalog — rule #8 at the feed level)."""
    seen = {f["url"] for f in catalog}
    return catalog + [f for f in custom if f["url"] not in seen]
