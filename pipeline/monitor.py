"""
monitor.py — Session 2. The news intake layer.

Pulls from two source types and normalizes both into one article dict that
matches the `articles` table exactly:

    RSS feeds   -> feedparser (works offline on a feed string; no key needed)
    NewsAPI     -> newsapi.org REST (needs NEWS_API_KEY)

Design choices that matter:
  * One normalized shape regardless of source, so everything downstream
    (decision scorer, context retriever) never branches on source type.
  * Dedup happens at write time via memory.insert_article (UNIQUE url), so a
    story syndicated across three feeds is stored once. This is the article-level
    version of CLAUDE.md rule #8.
  * Per-source failures are isolated: one dead feed or a NewsAPI 429 does not
    abort the whole run. Everything is logged (rule #12).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import mktime
from typing import Any, Iterable, Optional

import feedparser
import requests

from config import settings
from pipeline import memory

logger = logging.getLogger("monitor")

NEWSAPI_URL = "https://newsapi.org/v2/everything"
USER_AGENT = "pulse-agent/0.1 (+single-user content agent)"


def _to_iso(value: Any) -> Optional[str]:
    """Normalize assorted date representations to ISO8601 UTC, or None."""
    if not value:
        return None
    # feedparser exposes a time.struct_time on *_parsed fields
    if hasattr(value, "tm_year"):
        return datetime.fromtimestamp(mktime(value), tz=timezone.utc).isoformat()
    if isinstance(value, str):
        # NewsAPI already returns ISO8601 (e.g. 2026-06-10T09:30:00Z)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            ).isoformat()
        except ValueError:
            return value  # store as-is rather than lose it
    return None


class NewsMonitor:
    """Fetches and persists news from RSS feeds and NewsAPI.

    Feeds may be plain URL strings or spec dicts from sources.feeds_for():
        {"url": ..., "name": ..., "vertical": ..., "region": ...}
    Spec dicts let each article carry its vertical/region so signals can later
    be filtered by topic area.
    """

    def __init__(
        self,
        rss_feeds: Optional[Iterable] = None,
        db_path: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        if rss_feeds is None:
            rss_feeds = list(settings.default_rss_feeds)
        # normalize every feed to a spec dict
        self.feeds: list[dict] = [
            f if isinstance(f, dict) else {"url": f, "name": None, "vertical": None, "region": None}
            for f in rss_feeds
        ]
        self.db_path = db_path
        self.timeout = timeout

    # ------------------------------------------------------------------ RSS
    def parse_rss_entries(
        self,
        parsed: feedparser.FeedParserDict,
        vertical: Optional[str] = None,
        region: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> list[dict]:
        """Turn a parsed feed into normalized article dicts (pure, no network).
        vertical/region/source_name come from the feed spec and stamp each item."""
        feed_title = source_name or (
            parsed.feed.get("title") if getattr(parsed, "feed", None) else None
        )
        out: list[dict] = []
        for e in parsed.entries:
            url = e.get("link")
            title = e.get("title")
            if not url or not title:
                continue  # an article with no link can't be deduped or opened
            out.append(
                {
                    "source": "rss",
                    "source_name": feed_title,
                    "vertical": vertical,
                    "region": region,
                    "url": url,
                    "title": title.strip(),
                    "description": (e.get("summary") or "").strip() or None,
                    "content": (e.get("content", [{}])[0].get("value")
                                if e.get("content") else None),
                    "author": e.get("author"),
                    "published_at": _to_iso(
                        e.get("published_parsed") or e.get("updated_parsed")
                    ),
                    "raw_json": dict(e),
                }
            )
        return out

    def fetch_rss(self) -> list[dict]:
        """Fetch every configured feed. Bad feeds are skipped, not fatal."""
        articles: list[dict] = []
        for spec in self.feeds:
            url = spec["url"]
            try:
                parsed = feedparser.parse(url, agent=USER_AGENT)
                if parsed.bozo and not parsed.entries:
                    logger.warning("RSS parse issue for %s: %s", url, parsed.bozo_exception)
                    continue
                got = self.parse_rss_entries(
                    parsed, vertical=spec.get("vertical"),
                    region=spec.get("region"), source_name=spec.get("name"),
                )
                logger.info("RSS [%s/%s] %s -> %d entries",
                            spec.get("vertical"), spec.get("region"), url, len(got))
                articles.extend(got)
            except Exception as exc:  # noqa: BLE001 — isolate per-feed failure
                logger.error("RSS fetch failed for %s: %s", url, exc)
        return articles

    def health_check(self) -> list[dict]:
        """Probe every feed once. Returns status per feed: ok / empty / error.
        Needs network; use to prune dead feeds from the catalog."""
        report: list[dict] = []
        for spec in self.feeds:
            row = {"name": spec.get("name"), "url": spec["url"],
                   "vertical": spec.get("vertical"), "region": spec.get("region")}
            try:
                parsed = feedparser.parse(spec["url"], agent=USER_AGENT)
                n = len(parsed.entries)
                row["status"] = "ok" if n else ("error" if parsed.bozo else "empty")
                row["entries"] = n
            except Exception as exc:  # noqa: BLE001
                row["status"] = "error"
                row["entries"] = 0
                row["error"] = str(exc)
            report.append(row)
        return report

    # -------------------------------------------------------------- NewsAPI
    def parse_newsapi_payload(
        self, payload: dict, vertical: Optional[str] = None, region: Optional[str] = None
    ) -> list[dict]:
        """Normalize a NewsAPI /everything response (pure, no network)."""
        out: list[dict] = []
        for a in payload.get("articles", []):
            url = a.get("url")
            title = a.get("title")
            if not url or not title:
                continue
            out.append(
                {
                    "source": "newsapi",
                    "source_name": (a.get("source") or {}).get("name"),
                    "vertical": vertical,
                    "region": region,
                    "url": url,
                    "title": title.strip(),
                    "description": a.get("description"),
                    "content": a.get("content"),
                    "author": a.get("author"),
                    "published_at": _to_iso(a.get("publishedAt")),
                    "raw_json": a,
                }
            )
        return out

    def fetch_newsapi(
        self,
        query: str,
        language: str = "en",
        page_size: int = 50,
        sort_by: str = "publishedAt",
        vertical: Optional[str] = None,
        region: Optional[str] = None,
    ) -> list[dict]:
        """Query NewsAPI /everything. Returns [] (logged) if no key or on error."""
        if not settings.news_api_key:
            logger.warning("NEWS_API_KEY not set — skipping NewsAPI fetch.")
            return []
        try:
            resp = requests.get(
                NEWSAPI_URL,
                params={
                    "q": query,
                    "language": language,
                    "pageSize": page_size,
                    "sortBy": sort_by,
                    "apiKey": settings.news_api_key,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
            got = self.parse_newsapi_payload(payload, vertical=vertical, region=region)
            logger.info("NewsAPI '%s' -> %d articles", query, len(got))
            return got
        except Exception as exc:  # noqa: BLE001
            logger.error("NewsAPI fetch failed for '%s': %s", query, exc)
            return []

    # --------------------------------------------------------------- driver
    def persist(self, articles: list[dict]) -> dict[str, int]:
        """Write articles to the DB. Returns counts of new vs duplicate."""
        new = dup = 0
        for art in articles:
            try:
                _, is_new = memory.insert_article(art, db_path=self.db_path)
                new += int(is_new)
                dup += int(not is_new)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to persist %s: %s", art.get("url"), exc)
        logger.info("Persisted: %d new, %d duplicate", new, dup)
        return {"new": new, "duplicate": dup, "total": len(articles)}

    def run(self, newsapi_queries: Optional[list[str]] = None) -> dict[str, int]:
        """One full intake cycle: RSS + (optional) NewsAPI queries -> DB."""
        batch = self.fetch_rss()
        for q in newsapi_queries or []:
            batch.extend(self.fetch_newsapi(q))
        return self.persist(batch)


if __name__ == "__main__":
    # Manual smoke run. Needs network. Pulls IN + US politics from the catalog.
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    from sources import feeds_for

    memory.init_db()
    mon = NewsMonitor(rss_feeds=feeds_for(["politics"], ["india", "us"]))
    result = mon.run()
    print(result)
