"""
context.py — the 6-layer context retriever. The read side of the memory moat.

Before a draft is generated, this loads everything the account already knows
that's relevant to the story, and injects it into the generation prompt. After
a month of running, drafts stop sounding like reactions to a headline and start
sounding like they remember the whole arc — which is exactly the thing a fresh
competitor cannot copy.

THE SIX LAYERS, and what each honestly is here:
  1. historical context   -> REAL. events_timeline rows matching the story
                             (seeded by decision.run for every FIRE/WARM story).
  2. stance memory        -> REAL. stance_history rows for THIS account
                             (written by pipeline/updater.py when you post).
  3. contradiction finder -> MATERIAL, NOT VERDICT. The past events + stances
                             are handed to the generator, whose contradiction
                             format already refuses to invent quotes; we supply
                             the receipts, Claude judges if they conflict.
  4. data enrichment      -> RELATED COVERAGE. No curated stats store exists,
                             so this layer is other already-ingested articles
                             on the story — real, not pretend statistics.
  5. narrative thread     -> REAL. The matched events ordered oldest→newest,
                             rendered as the arc this story continues.
  6. competitor gap       -> NOT BUILT. Needs competitor account tracking
                             (paid X access). The key exists, always None, so
                             downstream code is ready when the watcher lands.

Retrieval is PURE PYTHON (keyword match over the agent's own SQLite memory):
zero Claude calls, zero latency added, runs on every single draft for free.
The model only ever *consumes* the context.
"""

from __future__ import annotations

import re
from typing import Optional

from pipeline import memory
from style.dna import STOPWORDS

WORD = re.compile(r"[A-Za-z][A-Za-z']+")

# Words that match everything in a news DB and nothing in particular.
NEWS_NOISE = {
    "says", "said", "after", "amid", "over", "into", "new", "news", "report",
    "reports", "live", "update", "updates", "today", "year", "years", "day",
    "days", "week", "first", "more", "most", "could", "would", "should", "may",
    "might", "must", "amidst", "between", "during", "against", "india", "indian",
    "us", "world", "government", "minister", "ministry",
}

MAX_KEYWORDS = 8


def extract_keywords(*texts: Optional[str]) -> list[str]:
    """Distinctive lowercase keywords from the given texts, in first-seen
    order. Deterministic; this is what gets matched against the memory."""
    seen: list[str] = []
    for text in texts:
        for tok in WORD.findall(text or ""):
            t = tok.lower()
            if len(t) < 3 or t in STOPWORDS or t in NEWS_NOISE or t in seen:
                continue
            seen.append(t)
            if len(seen) >= MAX_KEYWORDS:
                return seen
    return seen


def _when(row: dict) -> str:
    raw = row.get("event_date") or row.get("created_at") or ""
    return raw[:10] or "?"


class ContextRetriever:
    """Loads the six layers for a signal/article + account. No model calls."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def retrieve(self, signal: dict, account: dict) -> dict:
        """signal needs title (and optionally topic/angle/description/article_id).
        Returns the structured context package; every layer may be empty."""
        keywords = extract_keywords(
            signal.get("topic", "").replace("-", " "),
            signal.get("title"), signal.get("angle"),
        )
        events = memory.find_events(keywords, limit=5, db_path=self.db_path)
        # Don't echo the story back to itself as "history".
        url = signal.get("url")
        events = [e for e in events if not (url and e.get("source_url") == url)]
        return {
            "keywords": keywords,
            "historical_events": events,
            "your_stances": memory.find_stances(
                account["id"], keywords, limit=5, db_path=self.db_path),
            "related_coverage": memory.find_related_articles(
                keywords, exclude_article_id=signal.get("article_id"),
                limit=4, db_path=self.db_path),
            "narrative_thread": sorted(events, key=_when),
            "competitor_gap": None,  # layer 6 — not built (see module docstring)
        }

    @staticmethod
    def render(ctx: dict) -> Optional[str]:
        """The structured package as a compact prompt block, or None when the
        memory has nothing relevant (cold start stays honestly cold)."""
        lines: list[str] = []
        if ctx["historical_events"]:
            lines.append("Past events on this topic (your timeline):")
            lines += [f"  - [{_when(e)}] ({e['topic']}) {e['summary']}"
                      for e in ctx["historical_events"]]
        if ctx["your_stances"]:
            lines.append("Positions YOU have already taken publicly:")
            lines += [f"  - [{_when(s)}] on {s['topic']}: {s['stance']}"
                      for s in ctx["your_stances"]]
        if ctx["related_coverage"]:
            lines.append("Related coverage already seen:")
            lines += [f"  - {a['title']} ({a.get('source_name') or 'unknown'}, "
                      f"{(a.get('published_at') or '?')[:10]})"
                      for a in ctx["related_coverage"]]
        thread = ctx["narrative_thread"]
        if len(thread) >= 2:
            lines.append(
                f"Narrative arc: {len(thread)} related events from "
                f"{_when(thread[0])} to {_when(thread[-1])} — this story continues "
                f"that thread, not a one-off."
            )
        return "\n".join(lines) if lines else None

    def context_for(self, signal: dict, account: dict) -> Optional[str]:
        """retrieve + render in one call — what the drafting loop uses."""
        return self.render(self.retrieve(signal, account))


def transcript_excerpt(article: Optional[dict], max_chars: int = 1500) -> Optional[str]:
    """A prompt-sized block of a video's transcript (articles.content for
    source='youtube'), or None. The video_reaction format quotes from this."""
    if not article or article.get("source") != "youtube":
        return None
    content = (article.get("content") or "").strip()
    if not content:
        return None
    cut = content[:max_chars]
    if len(content) > max_chars:
        cut = cut.rsplit(" ", 1)[0] + "…"
    return f"Transcript of the video (excerpt — quote only from this):\n\"{cut}\""
