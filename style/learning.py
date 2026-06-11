"""
learning.py — the approve/reject learning loop. The "keeps learning" pillar.

Every draft you action in review.py leaves a status (approved/edited/posted vs
rejected). This module is what finally CONSUMES that signal, two ways:

1. VOICE LEARNING (apply_learning): contrast what you approve against what you
   reject and fold the lessons back into Genome A as a new style_dna version —
   the generator picks them up on its next draft, no other code changes.

2. SCORING LEARNING (historical_performance): turn approval rates AND real
   engagement (logged via /perf on Telegram or review.py --perf once you post)
   into the historical_perf subscore the decision agent carried as a neutral
   5.0 placeholder since Session 3. Both evidence streams flow through the
   same shrinkage formula; engagement naturally dominates as it accumulates.

measure-then-judge, as everywhere:
  * MEASURED in Python: approval rate overall / per format / per vertical,
    persona-score and length deltas between the two piles. Exact.
  * JUDGED by Claude: WHY the rejected ones lost — phrased as concrete style
    rules ("avoid …", "emphasize …"). Only runs with enough evidence on BOTH
    sides (settings.learn_min_side); below that, only the stats update.

GUARDRAILS (don't learn from noise):
  * No update until settings.learn_min_reviewed drafts have been actioned.
  * Idempotent: re-running without new reviews is a no-op (no version churn).
  * historical_perf shrinks toward neutral 5.0 with low sample counts
    (Bayesian prior, settings.learn_prior_weight) — 1 approval is not a 10.
  * Learned avoid-rules are capped so the genome can't bloat into an
    unfollowable rulebook.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from config import settings
from pipeline.llm import tracked_create
from pipeline import memory
from style import dna

logger = logging.getLogger("learning")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# Statuses that count as a positive signal. 'edited' is positive: you kept it
# (with fixes) rather than throwing it away.
POSITIVE = {"approved", "edited", "posted"}
NEGATIVE = {"rejected"}

MAX_LEARNED_AVOIDS = 8       # cap on rules the loop may add to things_to_avoid
MAX_EMPHASIZE = 6

SYSTEM_PROMPT = (
    "You are a content post-mortem analyst for ONE writer. You are shown drafts "
    "the writer approved and drafts they rejected, all generated in their own "
    "voice profile. Your job is to find what separates the piles and phrase it "
    "as short, concrete, reusable style rules for the next generation run. "
    "Rules must be about the writing (angle, structure, specificity, tone) — "
    "never about the news topic's importance. Respond with ONLY a JSON object, "
    "no fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Deterministic correlation (pure function, unit-testable)
# --------------------------------------------------------------------------- #
def correlate(reviewed: list[dict]) -> dict:
    """Exact stats over actioned drafts. No model, no guessing.

    Returns counts, approval rate, per-format and per-vertical rates, and the
    mean persona-score / length / question-rate of each pile — the measurable
    half of "what do my approvals have in common".
    """
    pos = [p for p in reviewed if p["status"] in POSITIVE]
    neg = [p for p in reviewed if p["status"] in NEGATIVE]

    def _rate(p: int, n: int) -> Optional[float]:
        return round(p / (p + n), 3) if (p + n) else None

    def _mean(vals: list[float]) -> Optional[float]:
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    by_format: dict[str, dict] = {}
    by_vertical: dict[str, dict] = {}
    by_topic: dict[str, dict] = {}
    by_emotion: dict[str, dict] = {}
    for bucket, key in ((by_format, "format"), (by_vertical, "vertical"),
                        (by_topic, "topic")):
        for p in reviewed:
            k = p.get(key) or "unknown"
            d = bucket.setdefault(k, {"approved": 0, "rejected": 0})
            d["approved" if p["status"] in POSITIVE else "rejected"] += 1
        for d in bucket.values():
            d["rate"] = _rate(d["approved"], d["rejected"])
    # emotion lives in the generation metadata (emotion calibration layer)
    for p in reviewed:
        emo = (p.get("meta_json") or {}).get("emotion") or "unknown"
        d = by_emotion.setdefault(emo, {"approved": 0, "rejected": 0})
        d["approved" if p["status"] in POSITIVE else "rejected"] += 1
    for d in by_emotion.values():
        d["rate"] = _rate(d["approved"], d["rejected"])

    return {
        "total_reviewed": len(reviewed),
        "approved": len(pos),
        "rejected": len(neg),
        "approval_rate": _rate(len(pos), len(neg)),
        "by_format": by_format,
        "by_vertical": by_vertical,
        "by_topic": by_topic,
        "by_emotion": by_emotion,
        "persona_score_approved": _mean([p.get("persona_score") for p in pos]),
        "persona_score_rejected": _mean([p.get("persona_score") for p in neg]),
        "avg_len_approved": dna.avg_length([p["content"] for p in pos]),
        "avg_len_rejected": dna.avg_length([p["content"] for p in neg]),
        "question_rate_approved": dna.question_rate([p["content"] for p in pos]),
        "question_rate_rejected": dna.question_rate([p["content"] for p in neg]),
    }


# --------------------------------------------------------------------------- #
# historical_perf — fills the decision agent's placeholder
# --------------------------------------------------------------------------- #
# Engagement value of a post: replies and retweets signal more than likes.
ENG_WEIGHTS = {"likes": 1.0, "retweets": 2.0, "replies": 1.5}


def _engagement_value(row: dict) -> float:
    return sum(row.get(k, 0) * w for k, w in ENG_WEIGHTS.items())


def engagement_scores(account_id: int, db_path: Optional[str] = None) -> dict:
    """Per-post engagement mapped to 0-10 RELATIVE to this account's own median
    (an account with 200 followers shouldn't be punished for not going viral):
    the median post scores 5.0, double the median scores 10. Returns
    {"overall": [scores], "by_vertical": {vertical: [scores]}}.
    """
    import statistics

    rows = memory.get_post_engagement(account_id, db_path=db_path)
    vals = [_engagement_value(r) for r in rows]
    if not vals:
        return {"overall": [], "by_vertical": {}, "by_topic": {}}
    baseline = statistics.median(vals) or (sum(vals) / len(vals)) or 1.0
    out: dict = {"overall": [], "by_vertical": {}, "by_topic": {}}
    for row, v in zip(rows, vals):
        score = round(min(10.0, 5.0 * v / baseline), 2)
        out["overall"].append(score)
        if row.get("vertical"):
            out["by_vertical"].setdefault(row["vertical"], []).append(score)
        if row.get("topic"):
            out["by_topic"].setdefault(row["topic"], []).append(score)
    return out


def historical_performance(account_id: int, db_path: Optional[str] = None) -> dict:
    """The historical_perf subscore, 0-10, from BOTH evidence streams — your
    approve/reject decisions and real post engagement (entered via /perf or
    review.py --perf) — each weighted by how much of it exists, shrunk toward
    neutral 5.0 by a prior so small samples barely move it:

        score = (approved*10 + Σ engagement_scores + prior*5)
                / (n_reviewed + n_engaged + prior)

    Returns {"overall": float, "by_vertical": {vertical: float}}. With no data
    at all this is exactly the original placeholder: 5.0 everywhere. As real
    engagement accumulates it naturally outweighs approve/reject because every
    posted-and-measured post contributes to both streams.
    """
    prior = settings.learn_prior_weight

    def _score(approved: int, rejected: int, eng: list[float]) -> float:
        n = approved + rejected + len(eng)
        if not n:
            return 5.0
        num = approved * 10.0 + sum(eng) + prior * 5.0
        return round(num / (n + prior), 2)

    reviewed = memory.get_reviewed_posts(account_id, db_path=db_path)
    stats = correlate(reviewed)
    eng = engagement_scores(account_id, db_path=db_path)

    def _bucket_scores(stat_bucket: dict, eng_bucket: dict) -> dict:
        keys = {k for k in stat_bucket if k != "unknown"} | set(eng_bucket)
        return {
            k: _score(
                stat_bucket.get(k, {}).get("approved", 0),
                stat_bucket.get(k, {}).get("rejected", 0),
                eng_bucket.get(k, []),
            )
            for k in keys
        }

    return {
        "overall": _score(stats["approved"], stats["rejected"], eng["overall"]),
        "by_vertical": _bucket_scores(stats["by_vertical"], eng["by_vertical"]),
        # topic-level is the sharp end: "rbi-rate-policy", not "politics"
        "by_topic": _bucket_scores(stats["by_topic"], eng["by_topic"]),
    }


# --------------------------------------------------------------------------- #
# The learner
# --------------------------------------------------------------------------- #
class ReviewLearner:
    """Folds approve/reject decisions back into Genome A. Client injectable."""

    def __init__(self, client: Any = None, model: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model

    @property
    def client(self) -> Any:
        if self._client is None:
            settings.require_anthropic()
            from anthropic import Anthropic

            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    # -------------------------------------------------------------- judging
    def _build_user_prompt(self, pos: list[dict], neg: list[dict], stats: dict) -> str:
        def _fmt(posts: list[dict]) -> str:
            return "\n".join(
                f"- [{p['format']}] {p['content']}" for p in posts[:10]
            )

        return (
            f"MEASURED STATS (ground truth):\n"
            f"  approval rate: {stats['approval_rate']}\n"
            f"  per-format rates: { {k: v['rate'] for k, v in stats['by_format'].items()} }\n"
            f"  avg length approved/rejected: "
            f"{stats['avg_len_approved']} / {stats['avg_len_rejected']} chars\n"
            f"  question rate approved/rejected: "
            f"{stats['question_rate_approved']} / {stats['question_rate_rejected']}\n\n"
            f"APPROVED DRAFTS ({len(pos)} shown up to 10):\n{_fmt(pos)}\n\n"
            f"REJECTED DRAFTS ({len(neg)} shown up to 10):\n{_fmt(neg)}\n\n"
            "What separates the piles? Return JSON with exactly these keys:\n"
            '  "avoid": array of 0-4 short rules describing what the rejected '
            'drafts do that the approved ones don\'t (e.g. "vague outrage with '
            'no specific number"),\n'
            '  "emphasize": array of 0-4 short rules describing what the '
            "approved drafts do well,\n"
            '  "summary": one sentence on the clearest pattern.\n'
            "If the piles are too similar to call, return empty arrays — do "
            "NOT invent patterns."
        )

    def judge(self, pos: list[dict], neg: list[dict], stats: dict) -> dict:
        msg = tracked_create(self.client, "learning",
            
            model=self.model,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": self._build_user_prompt(pos, neg, stats)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            return json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Could not parse learning JSON. Raw: %s", text[:200])
            return {}

    # ------------------------------------------------------------- applying
    @staticmethod
    def _merge_avoids(existing: list[str], learned: list[str]) -> tuple[list[str], list[str]]:
        """Append learned avoid-rules, deduped (case-insensitive), capped.
        Returns (merged things_to_avoid, learned subset actually kept)."""
        seen = {a.strip().lower() for a in existing}
        kept: list[str] = []
        for rule in learned:
            r = (rule or "").strip()
            if r and r.lower() not in seen and len(kept) < MAX_LEARNED_AVOIDS:
                kept.append(r)
                seen.add(r.lower())
        return existing + kept, kept

    def apply_learning(self, account_id: int, db_path: Optional[str] = None) -> dict:
        """Run one learning pass for an account. Returns a report dict with
        "updated": bool and "reason" when skipped. Saves a new style_dna
        version only when there is genuinely something new to learn."""
        current = memory.get_style_dna(account_id, db_path=db_path)
        if not current:
            return {"updated": False, "reason": "no style DNA yet"}

        reviewed = memory.get_reviewed_posts(account_id, db_path=db_path)
        stats = correlate(reviewed)
        if stats["total_reviewed"] < settings.learn_min_reviewed:
            return {"updated": False, "stats": stats,
                    "reason": f"only {stats['total_reviewed']} reviewed drafts "
                              f"(need {settings.learn_min_reviewed})"}

        # Idempotency: skip if nothing new was actioned since the last pass.
        genome_a = dict(current["genome_a"])
        prev = (genome_a.get("learned_preferences") or {}).get("learned_from") or {}
        if (prev.get("approved"), prev.get("rejected")) == (stats["approved"], stats["rejected"]):
            return {"updated": False, "stats": stats,
                    "reason": "no new reviews since last learning pass"}

        # Qualitative contrast only with enough evidence on both sides.
        pos = [p for p in reviewed if p["status"] in POSITIVE]
        neg = [p for p in reviewed if p["status"] in NEGATIVE]
        judged: dict = {}
        if len(pos) >= settings.learn_min_side and len(neg) >= settings.learn_min_side:
            judged = self.judge(pos, neg, stats)
        else:
            logger.info("Account %s: %d approved / %d rejected — stats-only "
                        "update (need %d per side for the contrast).",
                        account_id, len(pos), len(neg), settings.learn_min_side)

        avoid_merged, avoid_added = self._merge_avoids(
            genome_a.get("things_to_avoid") or [], judged.get("avoid") or []
        )
        genome_a["things_to_avoid"] = avoid_merged

        rated = {f: d["rate"] for f, d in stats["by_format"].items() if d["rate"] is not None}
        # emotions need a few examples each before they count as a signal
        emo_rated = {e: d["rate"] for e, d in stats["by_emotion"].items()
                     if d["rate"] is not None and e != "unknown"
                     and (d["approved"] + d["rejected"]) >= 3}
        genome_a["learned_preferences"] = {
            "emphasize": (judged.get("emphasize") or [])[:MAX_EMPHASIZE],
            "format_approval_rates": rated,
            "preferred_formats": sorted(rated, key=rated.get, reverse=True)[:3],
            "emotion_approval_rates": emo_rated,
            "preferred_emotions": sorted(emo_rated, key=emo_rated.get, reverse=True)[:2],
            "summary": (judged.get("summary") or "").strip(),
            "learned_from": {"approved": stats["approved"],
                             "rejected": stats["rejected"], "at": _now()},
        }

        memory.save_style_dna(
            account_id=account_id,
            genome_a=genome_a,
            genome_b=current["genome_b"],
            blend=current["blend"],
            sample_count=current["sample_count"],
            db_path=db_path,
        )
        logger.info("Account %s: learned from %d reviews (+%d avoid rules). %s",
                    account_id, stats["total_reviewed"], len(avoid_added),
                    genome_a["learned_preferences"]["summary"])
        return {"updated": True, "stats": stats, "avoid_added": avoid_added,
                "emphasize": genome_a["learned_preferences"]["emphasize"],
                "summary": genome_a["learned_preferences"]["summary"]}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Run the approve/reject learning pass")
    ap.add_argument("--account", help="only this handle (default: all active)")
    args = ap.parse_args()
    memory.init_db()
    learner = ReviewLearner()
    for acct in memory.list_active_accounts():
        if args.account and acct["handle"] != args.account:
            continue
        report = learner.apply_learning(acct["id"])
        print(f"\n[{acct['handle']}] updated={report['updated']}"
              + (f" — {report.get('reason')}" if not report["updated"] else ""))
        if report["updated"]:
            print(json.dumps({k: report[k] for k in ("avoid_added", "emphasize", "summary")},
                             indent=2, ensure_ascii=False))
        hp = historical_performance(acct["id"])
        print(f"historical_perf -> overall {hp['overall']}, by vertical {hp['by_vertical']}")
