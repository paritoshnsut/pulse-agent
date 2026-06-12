"""
discover.py — autonomous source discovery (keyless).

The watch list is manual: you tell Pulse which channels and subreddits to
watch, and it watches exactly those. Discovery is the inverse: the agent
derives search queries from each account's OWN topics and goes looking —
fresh YouTube videos and Reddit threads about those topics, no matter who
posted them. Set your niche once; the agent finds the sources.

YOUTUBE SEARCH (keyless)
    https://www.youtube.com/results?search_query=Q&sp=CAI%3D   (newest first)
No public RSS or API exists without a key, but the results page embeds its
data as `var ytInitialData = {...}`. We extract that JSON and walk it for
videoRenderer nodes — a generic recursive walk, so cosmetic layout changes
don't break us. "12,345 views" + "3 hours ago" gives a real views-per-hour
velocity_hint. Any parse failure returns [] and logs — never an error upward.

REDDIT SEARCH (keyless)
    https://www.reddit.com/search.json?q=Q&sort=hot&t=day
Same payload shape as a subreddit listing, so we reuse reddit.parse_listing
(real upvotes-per-hour velocity included).

Discovered articles use source='yt_search' / 'reddit_search' so Studio's
source-health panel shows discovery working separately from the manual watch
list. Discovered videos still get the transcript -> video_reaction treatment
(the source checks in scheduler/context accept both youtube sources).

Queries are deduplicated across accounts (rule #8): two personas sharing a
topic trigger one search, fanned out to both by the per-account scorer.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests

from config import settings
from pipeline import memory
from watch.reddit import parse_listing
from watch.reddit_auth import RedditAuth, default_auth
from watch.youtube import fetch_transcript

logger = logging.getLogger("watch.discover")

YT_SEARCH = "https://www.youtube.com/results"
REDDIT_SEARCH_PATH = "/search.json"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_YT_DATA = re.compile(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", re.DOTALL)
_REL_TIME = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago")
_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400,
                 "week": 604800, "month": 2592000, "year": 31536000}

MAX_VIDEOS_PER_QUERY = 10
MAX_TRANSCRIPTS_PER_CYCLE = 3


# ------------------------------------------------------------ query derivation
def account_queries(account: dict, max_queries: int = 4) -> list[str]:
    """Search terms for one account, straight from its topics. No Claude call —
    the topics ARE the niche, and the decision agent judges relevance anyway."""
    topics = account.get("topics") or []
    out = [t.strip() for t in topics if t and len(t.strip()) >= 3]
    if not out and account.get("niche"):
        # no topics set: fall back to the niche's leading phrase
        out = [account["niche"].split(":")[0].split(",")[0].strip()]
    return out[:max_queries]


def all_queries(accounts: list[dict], max_total: Optional[int] = None) -> list[str]:
    """Union of every active account's queries, deduplicated, order preserved."""
    seen, out = set(), []
    for acct in accounts:
        for q in account_queries(acct):
            key = q.lower()
            if key not in seen:
                seen.add(key)
                out.append(q)
    return out[: max_total or settings.discover_max_queries]


# ------------------------------------------------------------- youtube search
def _rel_time_to_iso(text: str, now: Optional[datetime] = None) -> Optional[str]:
    """'3 hours ago' / 'Streamed 2 days ago' -> ISO timestamp, or None."""
    m = _REL_TIME.search((text or "").lower())
    if not m:
        return None
    now = now or datetime.now(timezone.utc)
    secs = int(m.group(1)) * _UNIT_SECONDS[m.group(2)]
    return (now - timedelta(seconds=secs)).isoformat()


def _views_to_int(text: str) -> Optional[int]:
    """'12,345 views' / '1.2M views' -> int, or None."""
    m = re.match(r"([\d.,]+)\s*([KM]?)", (text or "").replace(",", "").strip(),
                 re.IGNORECASE)
    if not m or not m.group(1):
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    mult = {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1)
    return int(val * mult)


def views_velocity(views: Optional[int], published_iso: Optional[str],
                   now: Optional[datetime] = None) -> Optional[float]:
    """views/hour on a log curve, same shape as reddit's upvote velocity:
    ~100/hr -> ~3.3 | ~10k/hr -> ~6.6 | ~1M/hr -> ~10."""
    if views is None or not published_iso:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        pub = datetime.fromisoformat(published_iso)
    except ValueError:
        return None
    age_h = max((now - pub).total_seconds() / 3600.0, 0.25)
    vph = views / age_h
    return round(max(0.0, min(10.0, math.log10(vph + 1) / 6.0 * 10.0)), 2)


def _walk_video_renderers(node) -> list[dict]:
    """Every 'videoRenderer' dict anywhere in ytInitialData. The recursive walk
    is what makes this survive YouTube's layout reshuffles."""
    found: list[dict] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "videoRenderer" and isinstance(v, dict):
                found.append(v)
            else:
                found.extend(_walk_video_renderers(v))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_video_renderers(item))
    return found


def _runs_text(field: Optional[dict]) -> Optional[str]:
    if not isinstance(field, dict):
        return None
    if field.get("simpleText"):
        return field["simpleText"]
    runs = field.get("runs") or []
    return "".join(r.get("text", "") for r in runs) or None


def parse_youtube_results(data: dict, query: str,
                          now: Optional[datetime] = None) -> list[dict]:
    """Normalize ytInitialData into article dicts (pure, no network)."""
    out: list[dict] = []
    for v in _walk_video_renderers(data)[:MAX_VIDEOS_PER_QUERY]:
        vid = v.get("videoId")
        title = _runs_text(v.get("title"))
        if not vid or not title:
            continue
        published = _rel_time_to_iso(_runs_text(v.get("publishedTimeText")) or "", now)
        views = _views_to_int(_runs_text(v.get("viewCountText")) or "")
        out.append({
            "source": "yt_search",
            "source_name": f"YouTube · {_runs_text(v.get('ownerText')) or 'unknown'}",
            "vertical": None,        # discovery isn't pre-classified; scorer judges
            "region": None,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": title.strip(),
            "description": f"Found searching YouTube for: {query}",
            "content": None,
            "author": _runs_text(v.get("ownerText")),
            "published_at": published,
            "velocity_hint": views_velocity(views, published, now),
            "raw_json": {"videoId": vid, "query": query, "views": views},
        })
    return out


def youtube_search(query: str, timeout: int = 15) -> list[dict]:
    """One keyless YouTube search, newest first. [] on any failure."""
    try:
        resp = requests.get(
            YT_SEARCH, params={"search_query": query, "sp": "CAI="},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en"},
            timeout=timeout)
        resp.raise_for_status()
        m = _YT_DATA.search(resp.text)
        if not m:
            logger.warning("YT search '%s': no ytInitialData in page", query)
            return []
        return parse_youtube_results(json.loads(m.group(1)), query)
    except Exception as exc:  # noqa: BLE001
        logger.error("YT search failed for '%s': %s", query, exc)
        return []


# -------------------------------------------------------------- reddit search
def reddit_search(query: str, timeout: int = 15, limit: int = 20,
                  auth: Optional[RedditAuth] = None) -> list[dict]:
    """Site-wide Reddit search (hot, last day). Same shape as a subreddit
    listing, so velocity comes free from parse_listing."""
    _auth = auth or default_auth()
    try:
        resp = requests.get(
            f"{_auth.base_url}{REDDIT_SEARCH_PATH}",
            params={"q": query, "sort": "hot", "t": "day", "limit": limit},
            headers=_auth.headers(), timeout=timeout)
        resp.raise_for_status()
        articles = parse_listing(resp.json())
        for art in articles:
            art["source"] = "reddit_search"
            art["description"] = ((art.get("description") or "")
                                  + f"\n[found searching: {query}]").strip()
        return articles
    except Exception as exc:  # noqa: BLE001
        logger.error("Reddit search failed for '%s': %s", query, exc)
        return []


# ------------------------------------------------------------------- watcher
class DiscoveryWatcher:
    """Derives queries from every active account's topics and searches YouTube
    + Reddit for them. Fetchers are injectable for tests."""

    def __init__(self, db_path: Optional[str] = None,
                 yt_fetch: Optional[Callable[[str], list[dict]]] = None,
                 reddit_fetch: Optional[Callable[[str], list[dict]]] = None,
                 transcript_fetcher: Optional[Callable[[str], Optional[str]]] = None):
        self.db_path = db_path
        self._yt = yt_fetch or youtube_search
        self._reddit = reddit_fetch or reddit_search
        self._transcript = transcript_fetcher or fetch_transcript

    def queries(self) -> list[str]:
        accounts = memory.list_active_accounts(db_path=self.db_path)
        return all_queries(accounts)

    def run(self) -> dict[str, int]:
        queries = self.queries()
        if not queries:
            logger.info("Discovery: no account topics to search for yet.")
            return {"queries": 0, "new": 0, "duplicate": 0, "transcribed": 0}
        new = dup = transcribed = 0
        for q in queries:
            for art in self._yt(q) + self._reddit(q):
                try:
                    art_id, is_new = memory.insert_article(art, db_path=self.db_path)
                    new += int(is_new); dup += int(not is_new)
                    # a few transcripts per cycle: unlocks video_reaction for
                    # discovered videos without hammering YouTube
                    if (is_new and art["source"] == "yt_search"
                            and transcribed < MAX_TRANSCRIPTS_PER_CYCLE):
                        text = self._transcript(art["url"])
                        if text:
                            memory.set_article_content(art_id, text,
                                                       db_path=self.db_path)
                            transcribed += 1
                except Exception as exc:  # noqa: BLE001
                    logger.error("Discovery persist failed %s: %s",
                                 art.get("url"), exc)
        logger.info("Discovery: %d queries -> %d new (%d transcribed), %d dup",
                    len(queries), new, transcribed, dup)
        return {"queries": len(queries), "new": new, "duplicate": dup,
                "transcribed": transcribed}
