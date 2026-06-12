"""
youtube.py — YouTube watch layer (keyless).

Uses YouTube's public per-channel upload feed:
    https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
This needs NO API key and NO quota — it just lists a channel's recent uploads as
RSS. New uploads become articles with source='youtube', so they flow through the
exact same decision -> generator pipeline as news (a "video_reaction" angle is a
natural format to add later).

Channels come from the watch_list table (kind='youtube_channel'), deduplicated,
so a channel tracked for two personas is fetched once (rule #8).

A real view-velocity detector needs the YouTube Data API (quota'd, keyed); that's
a documented later upgrade. Upload *detection* — the thing that matters for
first-mover reaction — is fully covered here for free.

TRANSCRIPTS (the video_reaction unlock): CLAUDE.md assumed paid Whisper, but
YouTube serves its own captions (manual or auto-generated) keylessly via
youtube-transcript-api. New uploads get one transcript fetch at ingest; when it
succeeds, the text lands in articles.content and the process cycle drafts a
video_reaction that quotes the video's actual claims. When captions are
unavailable (some videos, occasional blocking) the video still flows through
as a normal headline reaction — graceful, never blocking.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from time import mktime
from typing import Callable, Optional

import feedparser

from pipeline import memory

logger = logging.getLogger("watch.youtube")

CHANNEL_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
USER_AGENT = "pulse-agent/0.1"

VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")
TRANSCRIPT_LANGS = ("en", "en-IN", "en-US", "hi")
TRANSCRIPT_MAX_CHARS = 6000  # stored cap; the prompt uses a smaller excerpt


def video_id_from_url(url: str) -> Optional[str]:
    m = VIDEO_ID.search(url or "")
    return m.group(1) if m else None


def fetch_transcript(video_url: str) -> Optional[str]:
    """Transcribe a YouTube video. Delegates to watch.transcribe which routes
    to the configured backend (captions → AssemblyAI → OpenAI → local)."""
    from watch.transcribe import transcribe_url
    return transcribe_url(video_url)


def _to_iso(struct_time) -> Optional[str]:
    if not struct_time:
        return None
    return datetime.fromtimestamp(mktime(struct_time), tz=timezone.utc).isoformat()


def parse_channel(parsed: feedparser.FeedParserDict, vertical=None, region=None) -> list[dict]:
    """Normalize a channel upload feed into article dicts (pure, no network)."""
    channel = parsed.feed.get("title") if getattr(parsed, "feed", None) else None
    out: list[dict] = []
    for e in parsed.entries:
        url = e.get("link")
        title = e.get("title")
        if not url or not title:
            continue
        out.append({
            "source": "youtube",
            "source_name": channel,
            "vertical": vertical,
            "region": region,
            "url": url,
            "title": title.strip(),
            "description": (e.get("summary") or "").strip() or None,
            "content": None,
            "author": e.get("author"),
            "published_at": _to_iso(e.get("published_parsed") or e.get("updated_parsed")),
            "raw_json": dict(e),
        })
    return out


class YouTubeWatcher:
    def __init__(self, db_path: Optional[str] = None, timeout: int = 15,
                 transcript_fetcher: Optional[Callable[[str], Optional[str]]] = None):
        self.db_path = db_path
        self.timeout = timeout
        self._transcript = transcript_fetcher or fetch_transcript

    def fetch(self) -> list[dict]:
        """Fetch every active youtube_channel in the watch list."""
        articles: list[dict] = []
        for w in memory.get_watch(kind="youtube_channel", db_path=self.db_path):
            try:
                parsed = feedparser.parse(CHANNEL_FEED.format(cid=w["ref"]), agent=USER_AGENT)
                got = parse_channel(parsed, vertical=w.get("vertical"), region=w.get("region"))
                logger.info("YT %s -> %d uploads", w.get("label") or w["ref"], len(got))
                articles.extend(got)
            except Exception as exc:  # noqa: BLE001
                logger.error("YouTube fetch failed for %s: %s", w["ref"], exc)
        return articles

    def run(self) -> dict[str, int]:
        articles = self.fetch()
        new = dup = transcribed = 0
        for art in articles:
            try:
                art_id, is_new = memory.insert_article(art, db_path=self.db_path)
                new += int(is_new); dup += int(not is_new)
                # one transcript attempt per NEW video — unlocks video_reaction
                if is_new:
                    transcript = self._transcript(art["url"])
                    if transcript:
                        memory.set_article_content(art_id, transcript, db_path=self.db_path)
                        transcribed += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("YT persist failed %s: %s", art.get("url"), exc)
        logger.info("YouTube: %d new (%d with transcript), %d dup", new, transcribed, dup)
        return {"new": new, "duplicate": dup, "transcribed": transcribed,
                "total": len(articles)}
