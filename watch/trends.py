"""
trends.py — Google Trends + Wikipedia watch layers (both keyless).

GOOGLE TRENDS
    https://trends.google.com/trending/rss?geo=GEO
Public RSS of currently-trending search terms per geo (IN, US, ...). Each trend
becomes an article with source='trends'. Trends are inherently velocity signals,
so traffic volume maps to velocity_hint. Geos come from watch_list
(kind='trends_geo'), or default to IN + US.

WIKIPEDIA EDIT STORMS
    https://{lang}.wikipedia.org/w/api.php?action=query&list=recentchanges...
An unusual burst of edits to a single article is a reliable early breaking-event
signal (CLAUDE.md). We pull recent changes, count edits per page in the window,
and surface pages above a threshold as articles with source='wikipedia'. Edit
count maps to velocity_hint.

Neither needs a key. Both are polite, low-frequency polls.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timezone
from time import mktime
from typing import Optional

import feedparser
import requests

from pipeline import memory

logger = logging.getLogger("watch.trends")

TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
USER_AGENT = "pulse-agent/0.1 (single-user content agent)"

DEFAULT_GEOS = [("IN", "india"), ("US", "us")]


def _to_iso(struct_time) -> Optional[str]:
    if not struct_time:
        return None
    return datetime.fromtimestamp(mktime(struct_time), tz=timezone.utc).isoformat()


def _traffic_to_velocity(traffic: str) -> Optional[float]:
    """Map Google's approx traffic string ('20,000+', '1M+') to 0-10."""
    if not traffic:
        return None
    t = traffic.lower().replace("+", "").replace(",", "").strip()
    mult = 1
    if t.endswith("k"):
        mult, t = 1_000, t[:-1]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    try:
        val = float(t) * mult
    except ValueError:
        return None
    # 1k->~3.3, 100k->~6.6, 10M->~10
    import math
    return max(0.0, min(10.0, math.log10(val + 1) / 7.0 * 10.0))


def parse_trends(parsed: feedparser.FeedParserDict, region=None) -> list[dict]:
    """Normalize a trending RSS feed into article dicts (pure, no network)."""
    out: list[dict] = []
    for e in parsed.entries:
        title = e.get("title")
        if not title:
            continue
        # ht namespace fields vary; pull traffic + first news link if present
        traffic = e.get("ht_approx_traffic") or ""
        base_link = e.get("link") or f"https://www.google.com/search?q={title.replace(' ', '+')}"
        # Append today's date so the same trending topic is treated as a fresh
        # article each day — trends represent what's hot RIGHT NOW, not a
        # permanent piece of content, so yesterday's entry shouldn't dedup today's.
        today_str = date.today().isoformat()
        link = f"{base_link}{'&' if '?' in base_link else '?'}_pd={today_str}"
        out.append({
            "source": "trends",
            "source_name": "Google Trends",
            "vertical": None,            # a trend isn't pre-classified; scorer judges relevance
            "region": region,
            "url": link,
            "title": title.strip(),
            "description": (e.get("summary") or "").strip() or f"Trending search: {title}",
            "content": None,
            "author": None,
            "published_at": _to_iso(e.get("published_parsed")),
            "velocity_hint": _traffic_to_velocity(traffic),
            "raw_json": dict(e),
        })
    return out


class TrendsWatcher:
    def __init__(self, db_path: Optional[str] = None, timeout: int = 15):
        self.db_path = db_path
        self.timeout = timeout

    def _geos(self) -> list[tuple[str, Optional[str]]]:
        watched = memory.get_watch(kind="trends_geo", db_path=self.db_path)
        if watched:
            return [(w["ref"], w.get("region")) for w in watched]
        return DEFAULT_GEOS

    def fetch(self) -> list[dict]:
        articles: list[dict] = []
        for geo, region in self._geos():
            try:
                parsed = feedparser.parse(TRENDS_RSS.format(geo=geo), agent=USER_AGENT)
                got = parse_trends(parsed, region=region or geo.lower())
                logger.info("Trends %s -> %d terms", geo, len(got))
                articles.extend(got)
            except Exception as exc:  # noqa: BLE001
                logger.error("Trends fetch failed for %s: %s", geo, exc)
        return articles

    def run(self) -> dict[str, int]:
        articles = self.fetch()
        new = dup = 0
        for art in articles:
            try:
                _, is_new = memory.insert_article(art, db_path=self.db_path)
                new += int(is_new); dup += int(not is_new)
            except Exception as exc:  # noqa: BLE001
                logger.error("Trends persist failed %s: %s", art.get("url"), exc)
        logger.info("Trends: %d new, %d dup", new, dup)
        return {"new": new, "duplicate": dup, "total": len(articles)}


def _fetch_wiki_summary(title: str, lang: str = "en", timeout: int = 8) -> Optional[str]:
    """Wikipedia REST API — free, keyless, no rate limit for reasonable use.
    Returns the lead-paragraph extract (up to 1500 chars) or None on failure.
    Called once per detected edit storm so the article gets real content, not
    just 'edit storm detected' — the decision scorer can then read the summary
    and judge relevance + reaction potential properly."""
    try:
        slug = title.replace(" ", "_")
        resp = requests.get(
            WIKI_SUMMARY.format(lang=lang, title=slug),
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        extract = (data.get("extract") or "").strip()
        if not extract:
            return None
        # Truncate to prompt-safe length — this becomes the article's content field.
        return extract[:1500] + ("…" if len(extract) > 1500 else "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Wikipedia summary failed for '%s': %s", title, exc)
        return None


class WikipediaWatcher:
    """Detects edit storms: pages edited unusually often in a short window."""

    def __init__(self, db_path: Optional[str] = None, lang: str = "en",
                 window_minutes: int = 60, storm_threshold: int = 5, timeout: int = 15):
        self.db_path = db_path
        self.lang = lang
        self.window_minutes = window_minutes
        self.storm_threshold = storm_threshold
        self.timeout = timeout

    def fetch(self) -> list[dict]:
        try:
            resp = requests.get(
                WIKI_API.format(lang=self.lang),
                params={
                    "action": "query", "list": "recentchanges",
                    "rcnamespace": 0, "rctype": "edit",
                    "rclimit": 500, "rcprop": "title|timestamp",
                    "format": "json",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            changes = resp.json().get("query", {}).get("recentchanges", [])
        except Exception as exc:  # noqa: BLE001
            logger.error("Wikipedia fetch failed: %s", exc)
            return []

        counts = Counter(c["title"] for c in changes if c.get("title"))
        storms = [(title, n) for title, n in counts.items() if n >= self.storm_threshold]
        max_n = max((n for _, n in storms), default=1)
        out: list[dict] = []
        for title, n in storms:
            slug = title.replace(" ", "_")
            # Fetch the article's lead paragraph so the scorer can read the actual
            # content — "edit storm detected" alone doesn't tell it what happened.
            summary = _fetch_wiki_summary(title, lang=self.lang)
            out.append({
                "source": "wikipedia",
                "source_name": "Wikipedia edit storm",
                "vertical": None,
                "region": None,
                "url": f"https://{self.lang}.wikipedia.org/wiki/{slug}",
                "title": f"Edit storm: {title} ({n} edits/hr)",
                "description": f"{title} saw {n} edits in the last {self.window_minutes} min — "
                               "often an early signal of a breaking event.",
                "content": summary,   # None on cold start or 404; scorer handles gracefully
                "author": None,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "velocity_hint": round(min(10.0, n / max_n * 10.0), 2),
                "raw_json": {"title": title, "edits": n},
            })
        logger.info("Wikipedia: %d edit storms (>=%d edits)", len(out), self.storm_threshold)
        return out

    def run(self) -> dict[str, int]:
        articles = self.fetch()
        new = dup = 0
        for art in articles:
            try:
                _, is_new = memory.insert_article(art, db_path=self.db_path)
                new += int(is_new); dup += int(not is_new)
            except Exception as exc:  # noqa: BLE001
                logger.error("Wiki persist failed %s: %s", art.get("url"), exc)
        return {"new": new, "duplicate": dup, "total": len(articles)}
