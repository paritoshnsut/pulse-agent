"""
corpus.py — the living voice corpus. Training stops being one-shot.

Before this module, training the voice meant pasting posts into a box that
forgot them the moment extraction finished. Now every sample is KEPT
(voice_samples table), the corpus grows daily, and retraining always runs over
the full accumulated set — 200-300 new pieces a day is the intended usage,
not an edge case.

TWO KINDS OF SAMPLE, deliberately separated:
  own         — things the user wrote. These define the voice: ALL measured
                statistics (length, cadence, punctuation, openers) come from
                these and only these.
  inspiration — editorials, threads, articles the user admires. These are
                directional pull: Claude distills what the user admires into
                genome_a["influences"], but an admired 1200-word editorial
                never contaminates the arithmetic of a 180-char tweet voice.

ANALYTICS-AWARE SELECTION: own samples can carry engagement numbers (append
"| likes retweets replies" to a line, or via the API). When the corpus
outgrows the training cap, selection keeps ALL measured-engagement samples
ranked by performance, then fills the rest with the most recent — your proven
winners always stay in the training set as the corpus scales.

CORPUS SUGGESTIONS, human-gated: the watchers already pull articles,
editorials and reddit threads all day. suggest() finds recent pieces that
match the account's preferred topics + stance history and files them as
PENDING suggestions. Nothing enters the corpus until the user accepts —
the same human-in-the-loop rule as posting, applied to training data.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.context import extract_keywords
from style.dna import StyleDNAExtractor

logger = logging.getLogger("corpus")

# optional analytics suffix on a pasted line: "the tweet text | 120 30 4"
PERF_SUFFIX = re.compile(r"\s*\|\s*(\d+)(?:\s+(\d+))?(?:\s+(\d+))?\s*$")


def parse_own_lines(text: str) -> list[dict]:
    """One tweet per line; optional '| likes retweets replies' suffix."""
    items = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        likes = rts = reps = None
        m = PERF_SUFFIX.search(line)
        if m:
            likes = int(m.group(1))
            rts = int(m.group(2)) if m.group(2) else 0
            reps = int(m.group(3)) if m.group(3) else 0
            line = line[: m.start()].strip()
        if line:
            items.append({"content": line, "kind": "own",
                          "likes": likes, "retweets": rts, "replies": reps})
    return items


def _engagement(sample: dict) -> Optional[float]:
    if sample.get("likes") is None:
        return None
    return (sample.get("likes") or 0) + 2.0 * (sample.get("retweets") or 0) \
        + 1.5 * (sample.get("replies") or 0)


def select_training_set(samples: list[dict], cap: int) -> list[dict]:
    """Within the cap: every sample with measured engagement (best first),
    then the most recent of the rest. Proven winners never age out."""
    if len(samples) <= cap:
        return samples
    with_perf = sorted((s for s in samples if _engagement(s) is not None),
                       key=_engagement, reverse=True)
    without = sorted((s for s in samples if _engagement(s) is None),
                     key=lambda s: s["added_at"], reverse=True)
    chosen = with_perf[:cap]
    chosen += without[: cap - len(chosen)]
    return chosen


def diversify_by_source(samples: list[dict], limit: int,
                        cap_fraction: float) -> list[dict]:
    """Cap any single source (outlet/author) to cap_fraction of the result, so
    a flood of editorials from one columnist during a big-news week can't warp
    `influences`. Caller passes newest-first; this preserves that order and
    fills up to `limit`. Falls back to origin when no source is recorded."""
    if not samples or limit <= 0:
        return []
    per_source = max(1, int(limit * cap_fraction))
    counts: dict[str, int] = {}
    chosen: list[dict] = []
    for s in samples:
        key = (s.get("source") or s.get("origin") or "unknown").strip().lower()
        if counts.get(key, 0) >= per_source:
            continue
        counts[key] = counts.get(key, 0) + 1
        chosen.append(s)
        if len(chosen) >= limit:
            break
    return chosen


def file_posted_draft(post_id: int, db_path: Optional[str] = None) -> bool:
    """The flywheel: a POSTED draft with measured engagement is, by
    definition, an audience-validated sample of your own published voice —
    it was human-approved at posting time, so auto-filing it breaks no
    human-in-the-loop rule. Called whenever /perf lands. Threads file one
    sample per tweet. Re-logging /perf updates the sample's numbers.
    Returns True if anything was filed/updated."""
    post = memory.get_post(post_id, db_path=db_path)
    if not post or post["status"] != "posted":
        return False
    eng = memory.get_engagement_for_post(post_id, db_path=db_path)
    if not eng:
        return False
    texts = (post.get("meta_json") or {}).get("tweets") or \
        [t for t in post["content"].split("\n\n———\n\n") if t.strip()]
    items = [{"content": t, "kind": "own", "origin": "approved_draft",
              "likes": eng["likes"], "retweets": eng["retweets"],
              "replies": eng["replies"]} for t in texts]
    result = memory.add_voice_samples(post["account_id"], items, db_path=db_path)
    if result["duplicates"]:  # already filed — refresh the numbers instead
        for t in texts:
            memory.touch_voice_sample_engagement(
                post["account_id"], t, eng["likes"], eng["retweets"],
                eng["replies"], db_path=db_path)
    logger.info("Flywheel: filed post #%d into the corpus (%d sample(s), "
                "%d updated).", post_id, result["added"], result["duplicates"])
    return True


class CorpusManager:
    """Add to / retrain from / suggest for the voice corpus."""

    def __init__(self, client: Any = None, model: Optional[str] = None,
                 db_path: Optional[str] = None) -> None:
        self._client = client
        self.model = model
        self.db_path = db_path

    # ------------------------------------------------------------- adding
    def add(self, account_id: int, text: str, kind: str = "own",
            origin: str = "manual") -> dict:
        """Add pasted text to the corpus. own: one sample per line (optional
        '| likes rts replies' analytics suffix). inspiration: the whole paste
        is ONE piece (an editorial is a unit, not 40 accidental lines)."""
        if kind == "own":
            items = parse_own_lines(text)
        else:
            content = text.strip()
            items = [{"content": content, "kind": "inspiration",
                      "origin": origin}] if content else []
        result = memory.add_voice_samples(account_id, items, db_path=self.db_path)
        return {**result, "corpus": memory.count_voice_samples(
            account_id, db_path=self.db_path)}

    # ----------------------------------------------------------- retraining
    def retrain(self, account_id: int, blend: Optional[float] = None) -> dict:
        """Re-extract Genome A from the FULL corpus (selection-capped), saving
        a new style_dna version. Genome B and blend carry forward."""
        own = memory.get_voice_samples(account_id, kind="own", db_path=self.db_path)
        if len(own) < 5:
            raise ValueError(f"Corpus has only {len(own)} of your own posts — "
                             "add at least 5 (50-200 is ideal) before training.")
        chosen = select_training_set(own, settings.corpus_max_own)
        # inspiration: newest-first, then capped so no single outlet dominates
        insp_samples = list(reversed(memory.get_voice_samples(
            account_id, kind="inspiration", db_path=self.db_path)))
        insp_samples = diversify_by_source(
            insp_samples, settings.corpus_max_inspiration,
            settings.corpus_source_cap_fraction)
        inspiration = [s["content"] for s in insp_samples]

        extractor = StyleDNAExtractor(client=self._client, model=self.model)
        genome_a = extractor.extract([s["content"] for s in chosen],
                                     inspiration=inspiration or None)
        current = memory.get_style_dna(account_id, db_path=self.db_path)
        memory.save_style_dna(
            account_id=account_id,
            genome_a=genome_a,
            genome_b=current["genome_b"] if current else None,
            blend=blend if blend is not None else (current["blend"] if current else 0.4),
            sample_count=len(chosen),
            db_path=self.db_path,
        )
        logger.info("Account %s retrained on %d own (+%d inspiration) samples.",
                    account_id, len(chosen), len(inspiration))
        return {"genome_a": genome_a, "trained_on": len(chosen),
                "inspiration_used": len(inspiration),
                "corpus": memory.count_voice_samples(account_id, db_path=self.db_path)}

    # ---------------------------------------------------------- suggestions
    def suggest(self, account: dict, hours: int = 48) -> int:
        """File PENDING corpus suggestions from recently ingested articles that
        match this account's topics + stance history. Deterministic and free;
        nothing is added to the corpus without explicit acceptance.
        Returns how many new suggestions were filed."""
        interests = list(account.get("topics") or [])
        dna = memory.get_style_dna(account["id"], db_path=self.db_path)
        if dna:
            interests += dna["genome_a"].get("topics_preferred", [])
        interests += [t["topic"].replace("-", " ")
                      for t in memory.top_stance_topics(account["id"], limit=5,
                                                        db_path=self.db_path)]
        keywords = extract_keywords(" ".join(interests))
        if not keywords:
            return 0
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        candidates = memory.find_articles_fetched_after(
            keywords, since, limit=40, db_path=self.db_path)
        filed = 0
        for art in candidates:
            text = f"{art.get('title') or ''} {art.get('description') or ''}".lower()
            hits = [kw for kw in keywords if kw in text]
            if len(hits) < 2:
                continue
            reason = f"matches your interests: {', '.join(hits[:4])}"
            if memory.insert_corpus_suggestion(account["id"], art["id"], reason,
                                               db_path=self.db_path):
                filed += 1
            if filed >= settings.corpus_suggest_max:
                break
        return filed

    def accept_suggestion(self, suggestion_id: int, account_id: int) -> dict:
        """User said yes: the piece enters the corpus as INSPIRATION (it's
        someone else's writing — it can inform, never define, the voice)."""
        pending = {s["id"]: s for s in memory.get_corpus_suggestions(
            account_id, status="pending", db_path=self.db_path)}
        sug = pending.get(suggestion_id)
        if not sug:
            raise ValueError(f"No pending suggestion #{suggestion_id}")
        content = "\n\n".join(filter(None, [
            sug.get("title"), sug.get("description"), sug.get("content")]))[:4000]
        result = memory.add_voice_samples(
            account_id, [{"content": content, "kind": "inspiration",
                          "origin": f"article:{sug['article_id']}",
                          "source": sug.get("source_name")}],
            db_path=self.db_path)
        memory.set_suggestion_status(suggestion_id, "accepted", db_path=self.db_path)
        return result

    def reject_suggestion(self, suggestion_id: int) -> None:
        memory.set_suggestion_status(suggestion_id, "rejected", db_path=self.db_path)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Voice corpus tools")
    ap.add_argument("--account", required=True, help="handle")
    ap.add_argument("--add", help="file of posts to add (one per line)")
    ap.add_argument("--kind", default="own", choices=["own", "inspiration"])
    ap.add_argument("--retrain", action="store_true")
    ap.add_argument("--suggest", action="store_true")
    args = ap.parse_args()
    memory.init_db()
    acct = next((a for a in memory.list_active_accounts()
                 if a["handle"] == args.account), None)
    if not acct:
        raise SystemExit(f"No active account '{args.account}'")
    mgr = CorpusManager()
    if args.add:
        print(mgr.add(acct["id"], open(args.add).read(), kind=args.kind))
    if args.suggest:
        print(f"{mgr.suggest(acct)} new suggestions filed")
    if args.retrain:
        out = mgr.retrain(acct["id"])
        print(f"trained on {out['trained_on']} own + {out['inspiration_used']} inspiration")
