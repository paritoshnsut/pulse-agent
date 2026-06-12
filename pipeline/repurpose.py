"""
repurpose.py — the Content Squeezer. The blank-page killer.

Every other producer in this system REACTS to an external signal. The Squeezer
is the opposite mode: the user hands it ONE thing they already made — a blog
post, a podcast/YouTube link, a launch announcement, a newsletter — and it
expands it into a whole pack of platform-shaped drafts in the account's voice
and brand.

v2 — the content graph. "Input → LLM → outputs" produces drafts that all
chase the same obvious point. Instead the squeeze now runs:

    ingest          paste, URL, or a YouTube link (keyless transcript)
    persist         the source is filed into `content_assets` — a durable
                    library, re-squeezable months later with a better voice
    decompose       ONE Claude call extracts typed insight nodes — ideas
                    (each with suggested angles), claims, stories, statistics,
                    quotes, opinions — stored in `content_insights`
    expand          each draft is generated from ONE idea + ONE angle with
                    supporting nodes attached, not from the undigested blob;
                    drafts are grouped into one content pack PER IDEA
    voice + guards  unchanged: genome at generation, persona gate >70,
                    grounding against the source, brand kit

A novelty check (deterministic word overlap vs your recent posts) flags ideas
you've already published — flag, never block, like every guard here.

Fail-safe: decomposition off (SQUEEZE_DECOMPOSE=false) or any failure in it
falls back to the v1 whole-source squeeze. Cost: exactly one extra Claude
call per squeeze when decomposition is on.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory, poster
from pipeline.generator import REPURPOSE_FORMATS, ContentGenerator
from pipeline.llm import tracked_create
from style.voice import effective_for

logger = logging.getLogger("repurpose")

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]*\n[ \t]*")
_WORDS = re.compile(r"[a-z]{4,}")
_FENCE = re.compile(r"^```[a-z]*\n?|\n?```$", re.MULTILINE)
_YOUTUBE = re.compile(r"(youtube\.com/watch|youtube\.com/shorts|youtu\.be/)",
                      re.IGNORECASE)

INSIGHT_KINDS = ("idea", "claim", "story", "statistic", "quote", "opinion")

DECOMPOSE_PROMPT = """Understand this content. Do NOT write posts yet.

Extract its reusable substance as JSON:
{{
  "ideas": [{{"idea": "one self-contained main idea, stated as a sentence",
             "angles": ["2-3 distinct angles to present it: contrarian /
                         story / educational / hot take / data-led — phrased
                         as a one-line framing, not a label"]}}],
  "claims": ["specific assertions the content makes"],
  "stories": ["anecdotes or narratives, one line each"],
  "statistics": ["every number/metric with its meaning"],
  "quotes": ["verbatim quotable lines"],
  "opinions": ["the author's subjective positions"]
}}

Rules: maximum 6 ideas, ranked strongest first. Every item must come from the
content — extract, never invent. Empty arrays are fine. Return ONLY the JSON.

TITLE: {title}

CONTENT:
\"\"\"
{source}
\"\"\""""


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


def fetch_youtube_text(url: str) -> Optional[str]:
    """A YouTube link IS a podcast input: the keyless caption transcript
    (same fetcher the watch layer uses). None when no captions exist."""
    from watch.youtube import fetch_transcript
    return fetch_transcript(url)


def _tokens(text: str) -> set:
    return set(_WORDS.findall((text or "").lower()))


class ContentSqueezer:
    """Expands one source into idea-grouped packs of platform-shaped drafts."""

    def __init__(self, client: Any = None, model: Optional[str] = None,
                 db_path: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model
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

    # ------------------------------------------------------- decomposition
    def decompose(self, source: str, title: str, gen: ContentGenerator) -> Optional[dict]:
        """One Claude call → typed insight nodes, or None (fail-safe)."""
        try:
            msg = tracked_create(
                gen.client, "squeezer",
                model=self.model, max_tokens=1500,
                messages=[{"role": "user", "content": DECOMPOSE_PROMPT.format(
                    title=title, source=source)}])
            text = "".join(getattr(b, "text", "") for b in msg.content)
            data = json.loads(_FENCE.sub("", text.strip()))
            ideas = [i for i in (data.get("ideas") or [])
                     if isinstance(i, dict) and (i.get("idea") or "").strip()]
            if not ideas:
                return None
            data["ideas"] = ideas[:6]
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Decomposition failed (falling back to direct "
                           "squeeze): %s", exc)
            return None

    @staticmethod
    def _support_for(idea: str, insights: dict, per_kind: int = 2) -> list[str]:
        """Deterministic: the insight nodes most word-overlapping this idea.
        Statistics and quotes are the highest-value attachments."""
        idea_tok = _tokens(idea)
        lines = []
        for kind in ("statistic", "quote", "claim", "story", "opinion"):
            items = insights.get(kind + "s") or []
            scored = sorted(items, key=lambda t: -len(idea_tok & _tokens(str(t))))
            for item in scored[:per_kind]:
                if item:
                    lines.append(f"- ({kind}) {item}")
        return lines

    def _novelty_note(self, account_id: int, idea: str) -> Optional[str]:
        """Have you already published this idea? Word-overlap vs recent posts
        the human actioned. A note for the reviewer — never a block."""
        idea_tok = _tokens(idea)
        if len(idea_tok) < 4:
            return None
        try:
            for p in memory.get_reviewed_posts(account_id, db_path=self.db_path)[-60:]:
                if p.get("status") in ("rejected",):
                    continue
                overlap = idea_tok & _tokens(p.get("content"))
                if len(overlap) >= max(4, int(len(idea_tok) * 0.6)):
                    when = (p.get("posted_at") or p.get("created_at") or "")[:10]
                    return f"you covered a very similar idea on {when}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Novelty check failed: %s", exc)
        return None

    # ------------------------------------------------------------- squeeze
    def squeeze(self, account: dict, text: Optional[str] = None,
                url: Optional[str] = None, title: Optional[str] = None,
                plan: Optional[list] = None,
                asset_id: Optional[int] = None) -> dict:
        """Expand a source into idea-grouped content packs. Returns
        {"ok", "asset_id", "pack_id", "packs", "ideas", "drafts", "live"}
        or {"ok": False, "error"}. `asset_id` re-squeezes a library asset."""
        genome = effective_for(account["id"], db_path=self.db_path)
        if not genome:
            return {"ok": False, "error": "train a voice for this account first"}

        source_type = "paste"
        if asset_id:
            asset = memory.get_content_asset(asset_id, db_path=self.db_path)
            if not asset or asset["account_id"] != account["id"]:
                return {"ok": False, "error": "no such asset in your library"}
            text, title = asset["raw_content"], title or asset["title"]
            url, source_type = asset["source_url"], asset["source_type"]
        elif url and not text:
            if _YOUTUBE.search(url):
                source_type, text = "youtube", fetch_youtube_text(url)
                if not text:
                    return {"ok": False, "error": "that video has no captions "
                            "we can read — paste the transcript instead"}
            else:
                source_type = "url"
                fetched_title, text = fetch_url_text(url)
                title = title or fetched_title
        source = (text or "").strip()
        if len(source) < 80:
            return {"ok": False, "error": "give at least a paragraph to repurpose "
                                          "(paste the text, or a URL we can read)"}
        source = source[: settings.repurpose_max_chars]
        title = (title or source[:60]).strip()

        if not asset_id:
            asset_id = memory.save_content_asset(
                account["id"], source, title=title, source_type=source_type,
                source_url=url, db_path=self.db_path)

        gen = ContentGenerator(client=self._client, model=self.model)
        insights = self.decompose(source, title, gen) \
            if settings.squeeze_decompose else None
        if insights:
            memory.save_insights(asset_id, account["id"], insights,
                                 db_path=self.db_path)
            return self._squeeze_graph(account, gen, source, title, url,
                                       asset_id, insights, plan)
        return self._squeeze_direct(account, gen, source, title, url,
                                    asset_id, plan)

    # ------------------------------------------- v2: idea → angle → format
    def _squeeze_graph(self, account: dict, gen: ContentGenerator, source: str,
                       title: str, url: Optional[str], asset_id: int,
                       insights: dict, plan: Optional[list]) -> dict:
        ideas = insights["ideas"][: max(1, settings.squeeze_max_ideas)]
        packs, pack_meta = [], []
        for i in ideas:
            pid = memory.create_content_pack(
                account["id"], source_title=title, source_url=url,
                source_excerpt=i["idea"][:500], asset_id=asset_id,
                idea=i["idea"], db_path=self.db_path)
            packs.append(pid)
            pack_meta.append({"pack_id": pid, "idea": i["idea"], "drafts": 0,
                              "novelty": self._novelty_note(account["id"],
                                                            i["idea"])})

        scorer, grounding = self._scorer(), self._grounding()
        genome = effective_for(account["id"], db_path=self.db_path)
        drafts, slot = [], 0
        for fmt, count in (plan or list(settings.repurpose_plan)):
            if fmt not in REPURPOSE_FORMATS:
                continue
            for _ in range(count):
                k = slot % len(ideas)
                idea = ideas[k]
                angles = [a for a in (idea.get("angles") or []) if a]
                angle = angles[(slot // len(ideas)) % len(angles)] if angles \
                    else "present this idea your way"
                support = self._support_for(idea["idea"], insights)
                context = (
                    "SOURCE CONTENT TO REPURPOSE (extract and repackage "
                    "faithfully — never invent facts beyond this):\n"
                    f"\"\"\"\n{source}\n\"\"\"\n\n"
                    "BUILD THIS DRAFT AROUND ONE IDEA ONLY:\n"
                    f"IDEA: {idea['idea']}\nANGLE: {angle}\n"
                    + ("SUPPORTING MATERIAL from the source (use what helps):\n"
                       + "\n".join(support) if support else ""))
                signal = {"title": idea["idea"], "source_name": "your own content",
                          "description": source[:300], "angle": angle}
                draft = gen.generate_checked(
                    signal, genome, fmt=fmt, scorer=scorer,
                    account_id=account["id"], persist=True, db_path=self.db_path,
                    context=context, grounding=grounding)
                if draft.get("post_id"):
                    memory.set_post_pack(draft["post_id"], packs[k],
                                         db_path=self.db_path)
                    meta = {"asset_id": asset_id, "idea": idea["idea"],
                            "angle": angle}
                    if pack_meta[k]["novelty"]:
                        meta["novelty"] = pack_meta[k]["novelty"]
                    memory.update_post_meta(draft["post_id"], meta,
                                            db_path=self.db_path)
                    pack_meta[k]["drafts"] += 1
                    drafts.append({"post_id": draft["post_id"], "format": fmt,
                                   "content": draft["content"],
                                   "empty": draft["empty"],
                                   "idea": idea["idea"], "angle": angle})
                slot += 1
        live = [d for d in drafts if not d["empty"]]
        logger.info("[%s] squeezed '%s' → %d ideas, %d insight nodes, %d "
                    "drafts in %d packs.", account.get("handle"), title[:40],
                    len(ideas), sum(len(insights.get(k + "s") or [])
                                    for k in INSIGHT_KINDS), len(live), len(packs))
        if live:
            poster.TelegramNotifier().send(
                f"📦 Squeezed '{title[:50]}' into {len(ideas)} ideas / "
                f"{len(live)} drafts — review the packs in the app.")
        return {"ok": True, "mode": "graph", "asset_id": asset_id,
                "pack_id": packs[0], "packs": pack_meta,
                "ideas": [i["idea"] for i in ideas],
                "drafts": drafts, "live": len(live)}

    # --------------------------------------------------- v1: whole source
    def _squeeze_direct(self, account: dict, gen: ContentGenerator, source: str,
                        title: str, url: Optional[str], asset_id: int,
                        plan: Optional[list]) -> dict:
        pack_id = memory.create_content_pack(
            account["id"], source_title=title, source_url=url,
            source_excerpt=source[:500], asset_id=asset_id, db_path=self.db_path)

        # the source IS the material; pass it as context with strict framing
        context = ("SOURCE CONTENT TO REPURPOSE (extract and repackage "
                   f"faithfully — never invent facts beyond this):\n\"\"\"\n{source}\n\"\"\"")
        signal = {"title": title, "source_name": "your own content",
                  "description": source[:300],
                  "angle": "repurpose this source into the requested format"}

        scorer, grounding = self._scorer(), self._grounding()
        genome = effective_for(account["id"], db_path=self.db_path)
        drafts = []
        for fmt, count in (plan or list(settings.repurpose_plan)):
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
        return {"ok": True, "mode": "direct", "asset_id": asset_id,
                "pack_id": pack_id, "packs": [{"pack_id": pack_id,
                                               "idea": None,
                                               "drafts": len(drafts)}],
                "ideas": [], "drafts": drafts, "live": len(live)}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Repurpose one input into content packs")
    ap.add_argument("--account", required=True)
    ap.add_argument("--file", help="text file to repurpose")
    ap.add_argument("--url", help="URL (article or YouTube) to repurpose")
    args = ap.parse_args()
    memory.init_db()
    acct = next((a for a in memory.list_active_accounts()
                 if a["handle"] == args.account), None)
    if not acct:
        raise SystemExit(f"No active account '{args.account}'")
    text = open(args.file).read() if args.file else None
    out = ContentSqueezer().squeeze(acct, text=text, url=args.url)
    print(out if not out.get("ok") else
          f"{len(out['ideas']) or 1} ideas → {out['live']} drafts ready in review")
