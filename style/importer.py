"""
importer.py — one-paste voice onboarding.

The onboarding critique this answers: asking a new user for persona + vertical
+ corpus + inspirations before they see any value loses them. The fix: they
paste ONE URL — their blog, Substack, Medium, newsletter archive, or an RSS
feed — and the system does the rest:

    discover the feed     the URL itself if it parses as RSS/Atom, else the
                          <link rel="alternate"> tag in the HTML, else the
                          conventional paths (/feed, /rss, /atom.xml, …)
    pull their writing    each entry, HTML-stripped, becomes a voice sample
                          (kind='own' — it IS their writing), deduplicated by
                          the corpus's content hash so re-imports are no-ops
    train the voice       CorpusManager.retrain as soon as ≥5 own samples
    infer the niche       the freshly judged genome's topics_preferred fills
                          the account's niche/topics IF the user left them
                          blank — never overwrites an explicit choice

Twitter/LinkedIn handles are deliberately NOT scraped: keyless scraping is
ToS-violating and the official read APIs are paid. For tweet-shaped voices the
paste box remains the path; this importer is the long-form/founder/newsletter
path. Everything degrades softly — a URL with no discoverable feed returns a
clear error, never a crash.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from pipeline import memory
from style.corpus import CorpusManager

logger = logging.getLogger("importer")

# conventional feed locations, tried in order after <link> discovery fails
COMMON_FEED_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml",
                     "/index.xml", "/feed/", "/blog/feed")

_LINK_TAG = re.compile(
    r"<link[^>]+rel=[\"']alternate[\"'][^>]*>", re.IGNORECASE)
_TYPE_ATTR = re.compile(r"type=[\"']application/(?:rss|atom)\+xml[\"']",
                        re.IGNORECASE)
_HREF_ATTR = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_ENTITY = re.compile(r"&[#a-z0-9]+;")

MAX_ENTRIES = 40          # newest N entries imported per run
MAX_SAMPLE_CHARS = 4000   # a blog post is a sample, not a database dump


def _clean_html(html: str) -> str:
    text = _TAGS.sub(" ", html or "")
    text = _ENTITY.sub(" ", text)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\s*\n\s*", "\n", text)).strip()


def _parses_as_feed(url: str):
    """feedparser result if the URL is itself a feed with entries, else None."""
    try:
        import feedparser
        parsed = feedparser.parse(url)
        return parsed if parsed.entries else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Feed parse failed for %s: %s", url, exc)
        return None


def discover_feed(url: str) -> Optional[str]:
    """Resolve any blog/site URL to its RSS/Atom feed URL (or None)."""
    url = url.strip()
    if not url.startswith("http"):
        url = f"https://{url}"
    if _parses_as_feed(url):
        return url
    # the page's own <link rel="alternate" type="application/rss+xml"> tag
    try:
        import requests
        html = requests.get(url, timeout=15,
                            headers={"User-Agent": "pulse-agent/1.0"}).text
        for tag in _LINK_TAG.findall(html):
            if _TYPE_ATTR.search(tag):
                m = _HREF_ATTR.search(tag)
                if m:
                    candidate = urljoin(url, m.group(1))
                    if _parses_as_feed(candidate):
                        return candidate
    except Exception as exc:  # noqa: BLE001
        logger.warning("Feed discovery fetch failed for %s: %s", url, exc)
    # conventional locations (Substack/WordPress/Ghost/Hugo all use these)
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for path in COMMON_FEED_PATHS:
        if _parses_as_feed(base + path):
            return base + path
    return None


def extract_entries(feed_url: str, limit: int = MAX_ENTRIES) -> list[dict]:
    """[{title, text, url}] from a feed, newest first, HTML stripped. Entries
    whose body is too thin to carry voice (<200 chars) are skipped."""
    parsed = _parses_as_feed(feed_url)
    if not parsed:
        return []
    out = []
    for e in parsed.entries[:limit]:
        body = ""
        if e.get("content"):
            body = e["content"][0].get("value", "")
        body = body or e.get("summary", "") or ""
        text = _clean_html(body)
        if len(text) < 200:
            continue
        title = _clean_html(e.get("title", ""))
        out.append({"title": title, "text": text[:MAX_SAMPLE_CHARS],
                    "url": e.get("link", "")})
    return out


def import_voice(account_id: int, url: str, kind: str = "own",
                 retrain: bool = True, client: Any = None,
                 db_path: Optional[str] = None) -> dict:
    """The one-paste onboarding entry point. Returns
    {"ok", "feed", "imported", "duplicates", "trained", "niche", ...} or
    {"ok": False, "error": ...} — never raises."""
    feed = discover_feed(url)
    if not feed:
        return {"ok": False,
                "error": "no RSS/Atom feed found at that URL — paste your "
                         "posts directly in the voice box instead"}
    entries = extract_entries(feed)
    if not entries:
        return {"ok": False,
                "error": "found the feed but no readable posts in it"}

    origin = f"import:{urlparse(feed).netloc}"
    items = [{"content": (f"{e['title']}\n\n{e['text']}" if e["title"]
                          else e["text"]),
              "kind": kind, "origin": origin} for e in entries]
    result = memory.add_voice_samples(account_id, items, db_path=db_path)
    summary: dict = {"ok": True, "feed": feed, "imported": result["added"],
                     "duplicates": result["duplicates"], "trained": False}

    own_count = len(memory.get_voice_samples(account_id, kind="own",
                                             db_path=db_path))
    if retrain and kind == "own" and own_count >= 5:
        try:
            mgr = CorpusManager(client=client, db_path=db_path)
            trained = mgr.retrain(account_id)
            summary["trained"] = True
            summary["trained_on"] = trained["trained_on"]
            _autofill_niche(account_id, trained["genome_a"],
                            summary, db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-retrain after import failed: %s", exc)
            summary["train_error"] = str(exc)
    return summary


def _autofill_niche(account_id: int, genome_a: dict, summary: dict,
                    db_path: Optional[str] = None) -> None:
    """Fill blank niche/topics from the judged genome. An explicit user
    choice is never overwritten."""
    account = memory.get_account(account_id, db_path=db_path) or {}
    topics = [t for t in (genome_a.get("topics_preferred") or []) if t][:5]
    if not topics:
        return
    updates = {}
    if not (account.get("niche") or "").strip():
        updates["niche"] = ", ".join(topics[:3])
    if not account.get("topics"):
        updates["topics"] = topics
    if updates:
        memory.upsert_account(handle=account["handle"],
                              platform=account.get("platform") or "twitter",
                              db_path=db_path, **updates)
        summary.update(updates)
        logger.info("Account %s niche auto-filled from imported voice: %s",
                    account_id, updates.get("niche") or topics)
