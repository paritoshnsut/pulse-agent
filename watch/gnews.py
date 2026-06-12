"""
gnews.py — Google News RSS per-account-topic watcher (keyless).

Google News exposes a public RSS feed for any keyword query:
    https://news.google.com/rss/search?q=QUERY&hl=en-IN&gl=IN&ceid=IN:en

No API key. No scraping. This is an official public endpoint. Google curates
from 500+ Indian and global outlets, so a single query surfaces articles you'd
miss even with 50 manually-tracked RSS feeds. New stories appear within ~5
minutes of being indexed.

The watcher derives queries from each active account's topics — the same
all_queries() used by discover.py (rule #8: one search per unique topic across
all accounts, never duplicate fetches). A political account with topics
["policy", "economy"] gets two Google News searches; the articles land as
source='gnews' so Studio's source health shows them separately from manual feeds.

velocity_hint is None — Google News RSS doesn't expose traffic data. The signal
scorer's recency proxy handles freshness for these items.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import mktime
from typing import Optional
from urllib.parse import quote_plus

import feedparser

from pipeline import memory
from watch.discover import all_queries

logger = logging.getLogger("watch.gnews")

GNEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
USER_AGENT = "pulse-agent/0.1 (single-user content agent)"
MAX_QUERIES = 8   # each query = one HTTP request; 8 is polite for a 30-min cycle


def gnews_url(query: str) -> str:
    return GNEWS_RSS.format(q=quote_plus(query))


def _to_iso(struct_time) -> Optional[str]:
    if not struct_time:
        return None
    return datetime.fromtimestamp(mktime(struct_time), tz=timezone.utc).isoformat()


def parse_gnews(parsed: feedparser.FeedParserDict, query: str) -> list[dict]:
    """Normalize a Google News RSS feed into article dicts (pure, no network)."""
    out: list[dict] = []
    for e in parsed.entries:
        url = e.get("link")
        title = e.get("title")
        if not url or not title:
            continue
        # Google News entries carry a 'source' sub-dict with the outlet name.
        source_name = None
        src = e.get("source")
        if isinstance(src, dict):
            source_name = src.get("title")
        elif isinstance(src, str):
            source_name = src
        out.append({
            "source": "gnews",
            "source_name": source_name or "Google News",
            "vertical": None,
            "region": "india",
            "url": url,
            "title": title.strip(),
            "description": (e.get("summary") or "").strip() or f"Google News: {query}",
            "content": None,
            "author": None,
            "published_at": _to_iso(e.get("published_parsed")),
            "velocity_hint": None,
            "raw_json": {"query": query, "source_name": source_name},
        })
    return out


class GoogleNewsWatcher:
    """Fetches Google News RSS for each active account's topics.
    Injectable for tests: pass max_queries to reduce to a single query, or
    monkeypatch feedparser.parse."""

    def __init__(self, db_path: Optional[str] = None, timeout: int = 15,
                 max_queries: int = MAX_QUERIES):
        self.db_path = db_path
        self.timeout = timeout
        self.max_queries = max_queries

    def _queries(self) -> list[str]:
        accounts = memory.list_active_accounts(db_path=self.db_path)
        return all_queries(accounts, max_total=self.max_queries)

    def fetch(self) -> list[dict]:
        queries = self._queries()
        if not queries:
            logger.info("GNews: no account topics configured yet.")
            return []
        articles: list[dict] = []
        for q in queries:
            try:
                parsed = feedparser.parse(gnews_url(q), agent=USER_AGENT)
                got = parse_gnews(parsed, q)
                logger.info("GNews '%s' -> %d articles", q, len(got))
                articles.extend(got)
            except Exception as exc:  # noqa: BLE001
                logger.error("GNews failed for '%s': %s", q, exc)
        return articles

    def run(self) -> dict[str, int]:
        articles = self.fetch()
        new = dup = 0
        for art in articles:
            try:
                _, is_new = memory.insert_article(art, db_path=self.db_path)
                new += int(is_new); dup += int(not is_new)
            except Exception as exc:  # noqa: BLE001
                logger.error("GNews persist failed %s: %s", art.get("url"), exc)
        logger.info("GNews: %d new, %d dup", new, dup)
        return {"new": new, "duplicate": dup, "total": len(articles)}
