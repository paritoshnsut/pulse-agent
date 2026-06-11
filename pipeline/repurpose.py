"""
repurpose.py — the Content Squeezer. The blank-page killer.

Every other producer in this system REACTS to an external signal. The Squeezer
is the opposite mode: the user hands it ONE thing they already made — a blog
post, a launch announcement, a podcast transcript, a newsletter — and it
expands it into a whole pack of platform-shaped drafts in the account's voice
and brand:

    one input  ->  1 LinkedIn post + 2 threads + 3 standalone insights
                   + 1 newsletter blurb + 1 short-video script

This is the feature that makes Pulse useful to ANY brand on day one, with zero
polling setup: paste your blog, get a month of content. It reuses the entire
generation stack — voice genome, brand kit, grounding (so it repackages the
source faithfully and never invents) — and the drafts land in the normal
review lane, grouped as a content pack.

Input is paste-text (reliable) or a URL (best-effort HTML→text extraction).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory, poster
from pipeline.generator import REPURPOSE_FORMATS, ContentGenerator
from style.voice import effective_for

logger = logging.getLogger("repurpose")

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]*\n[ \t]*")


def fetch_url_text(url: str, timeout: int = 15) -> tuple[Optional[str], Optional[str]]:
    """Best-effort (title, text) from a URL. Paste is the reliable path; this
    is convenience. Returns (None, None) on failure."""
    try:
        import requests

        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": "pulse-agent/1.0"})
        resp.raise_for_status()
        html = resp.text
        title = None
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        if m:
            title = _TAGS.sub("", m.group(1)).strip()
        body = _TAG.sub(" ", html)
        body = _TAGS.sub(" ", body)
        body = re.sub(r"&[a-z]+;", " ", body)
        body = _WS.sub("\n", re.sub(r"[ \t]{2,}", " ", body)).strip()
        return title, body or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("URL fetch failed for %s: %s", url, exc)
        return None, None


class ContentSqueezer:
    """Expands one source into a pack of platform-shaped drafts."""

    def __init__(self, client: Any = None, model: Optional[str] = None,
                 db_path: Optional[str] = None) -> None:
        self._client = client
        self.model = model
        self.db_path = db_path

    def _scorer(self):
        from style.scorer import PersonaConsistencyScorer
        return PersonaConsistencyScorer(client=self._client, model=self.model) \
            if self._client else PersonaConsistencyScorer()

    def _grounding(self):
        if not settings.grounding_enabled:
            return None
        from pipeline.grounding import GroundingChecker
        return GroundingChecker(client=self._client, model=self.model)

    def squeeze(self, account: dict, text: Optional[str] = None,
                url: Optional[str] = None, title: Optional[str] = None,
                plan: Optional[list] = None) -> dict:
        """Expand a source into a content pack. Returns
        {"ok", "pack_id", "drafts": [...]} or {"ok": False, "error"}."""
        genome = effective_for(account["id"], db_path=self.db_path)
        if not genome:
            return {"ok": False, "error": "train a voice for this account first"}

        if url and not text:
            fetched_title, text = fetch_url_text(url)
            title = title or fetched_title
        source = (text or "").strip()
        if len(source) < 80:
            return {"ok": False, "error": "give at least a paragraph to repurpose "
                                          "(paste the text, or a URL we can read)"}
        source = source[: settings.repurpose_max_chars]
        title = (title or source[:60]).strip()

        pack_id = memory.create_content_pack(
            account["id"], source_title=title, source_url=url,
            source_excerpt=source[:500], db_path=self.db_path)

        # the source IS the material; pass it as context with strict framing
        context = ("SOURCE CONTENT TO REPURPOSE (extract and repackage "
                   f"faithfully — never invent facts beyond this):\n\"\"\"\n{source}\n\"\"\"")
        signal = {"title": title, "source_name": "your own content",
                  "description": source[:300],
                  "angle": "repurpose this source into the requested format"}

        gen = ContentGenerator(client=self._client, model=self.model)
        scorer, grounding = self._scorer(), self._grounding()
        plan = plan or list(settings.repurpose_plan)
        drafts = []
        for fmt, count in plan:
            if fmt not in REPURPOSE_FORMATS:
                continue
            for _ in range(count):
                draft = gen.generate_checked(
                    signal, genome, fmt=fmt, scorer=scorer,
                    account_id=account["id"], persist=True, db_path=self.db_path,
                    context=context, grounding=grounding)
                if draft.get("post_id"):
                    memory.set_post_pack(draft["post_id"], pack_id, db_path=self.db_path)
                    drafts.append({"post_id": draft["post_id"], "format": fmt,
                                   "content": draft["content"],
                                   "empty": draft["empty"]})
        live = [d for d in drafts if not d["empty"]]
        logger.info("[%s] squeezed '%s' into %d drafts (pack %d).",
                    account.get("handle"), title[:40], len(live), pack_id)
        if live:
            poster.TelegramNotifier().send(
                f"📦 Repurposed '{title[:50]}' into {len(live)} drafts — "
                f"review them in the app (content pack #{pack_id}).")
        return {"ok": True, "pack_id": pack_id, "drafts": drafts,
                "live": len(live)}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Repurpose one input into a content pack")
    ap.add_argument("--account", required=True)
    ap.add_argument("--file", help="text file to repurpose")
    ap.add_argument("--url", help="URL to repurpose")
    args = ap.parse_args()
    memory.init_db()
    acct = next((a for a in memory.list_active_accounts()
                 if a["handle"] == args.account), None)
    if not acct:
        raise SystemExit(f"No active account '{args.account}'")
    text = open(args.file).read() if args.file else None
    out = ContentSqueezer().squeeze(acct, text=text, url=args.url)
    print(out if not out.get("ok") else
          f"pack {out['pack_id']}: {out['live']} drafts ready in review")
