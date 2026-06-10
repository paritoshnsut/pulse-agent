"""
decision.py — Session 3. The importance scorer.

Given an article and your account profile, produce a signal: a 0-10 composite
score, an urgency tier (FIRE/WARM/COOL/SKIP), the five subscores, a suggested
angle, and the reasoning.

HONESTY ABOUT THE FIVE SUBSCORES
--------------------------------
CLAUDE.md's signal model was designed for the Twitter/YouTube watch layer,
where "velocity" means real engagement growth you can measure. For a *news
article* off RSS/NewsAPI, you do not have live share velocity. So this module
is explicit about what each subscore really is here:

  velocity (30%)           -> RECENCY PROXY. A news item's "speed" is approximated
                              by how fresh it is (time-decay). Real velocity comes
                              online when the social watch layer is built; the
                              field and weight stay so nothing downstream changes.
  relevance (25%)          -> REAL. Claude judges fit to your niche/topics.
  reaction_potential (20%) -> REAL. Claude judges whether *this account* has a
                              distinctive take, given your stances.
  window_urgency (15%)     -> REAL (recency). Same decay curve; how much of the
                              first-mover window is left.
  historical_perf (10%)    -> REAL once you review drafts. Filled from your
                              approve/reject history (style/learning.py),
                              per-vertical where evidence exists, shrunk toward
                              neutral 5.0 at low sample counts. Stays exactly
                              5.0 until reviews accumulate; real engagement
                              data slots into the same hook later.

This is the difference between a scorer that works and a demo that pretends a
language model can feel Twitter velocity from a headline. It can't, so we don't.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.generator import CHOOSABLE_FORMATS

logger = logging.getLogger("decision")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You are the editorial judgment of a single social-media commentator. "
    "You decide whether a news item is worth reacting to for THIS account, given "
    "its niche and stated positions. You are decisive and you do not inflate "
    "scores: most news is a SKIP. Respond with ONLY a JSON object, no prose, no "
    "markdown fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


class DecisionAgent:
    """Scores articles for a given account. The Anthropic client is injectable
    so the scoring math can be unit-tested without a key or network."""

    def __init__(self, client: Any = None, model: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model

    @property
    def client(self) -> Any:
        """Lazily build a real Anthropic client only when actually needed."""
        if self._client is None:
            settings.require_anthropic()
            from anthropic import Anthropic  # imported here so tests need no key

            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    # ----------------------------------------------------------- recency
    def recency_scores(self, published_at: Optional[str], now: Optional[datetime] = None) -> tuple[float, float]:
        """
        Map article age to (velocity_proxy, window_urgency) on a 0-10 scale using
        exponential decay: score = 10 * exp(-age_minutes / TAU).

        Unknown/unparseable date -> neutral 5.0 (we don't reward or punish it).
        """
        if not published_at:
            return 5.0, 5.0
        now = now or datetime.now(timezone.utc)
        try:
            pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except ValueError:
            return 5.0, 5.0
        age_min = max(0.0, (now - pub).total_seconds() / 60.0)
        decayed = _clamp(10.0 * math.exp(-age_min / settings.recency_tau_minutes))
        return decayed, decayed

    # ------------------------------------------------------------- Claude
    def _build_user_prompt(self, article: dict, account: dict) -> str:
        topics = account.get("topics") or "[]"
        return (
            f"ACCOUNT NICHE: {account.get('niche') or 'general political commentary'}\n"
            f"PREFERRED TOPICS (JSON): {topics}\n\n"
            f"NEWS ITEM\n"
            f"Title: {article.get('title')}\n"
            f"Source: {article.get('source_name')}\n"
            f"Description: {article.get('description') or '(none)'}\n\n"
            "Rate this item FOR THIS ACCOUNT and return JSON with exactly these keys:\n"
            '  "relevance": 0-10 (fit to the niche/topics),\n'
            '  "reaction_potential": 0-10 (does this account have a distinctive, '
            "non-obvious take, not just a generic reaction),\n"
            '  "angle": one sentence describing the sharpest angle this account '
            "could take (or empty string if none),\n"
            '  "topic": a 2-4 word kebab-case topic slug for filing this in the '
            'memory timeline (e.g. "rbi-rate-policy", "delhi-air-quality"),\n'
            f'  "format": the post format that best fits this story, one of '
            f'{list(CHOOSABLE_FORMATS)} — "thread" only for multi-step stories '
            'with real data density; "data_story" only if a concrete surprising '
            'number exists; "quote_context" only if there is a striking verbatim '
            'quote; "achievement" only if the story is a clear win for a cause '
            'this account openly backs; "hot_take" when in doubt,\n'
            '  "reasoning": one or two sentences justifying the scores.\n'
            "Be stingy: a generic headline with no special angle for this account "
            "should score low on reaction_potential even if relevant."
        )

    def judge(self, article: dict, account: dict) -> dict:
        """Call Claude for the judgment subscores. Returns a dict with relevance,
        reaction_potential, angle, reasoning. Defensive against bad JSON."""
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_user_prompt(article, account)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            data = json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Could not parse model JSON; defaulting to neutral. Raw: %s", text[:200])
            data = {}
        fmt = (data.get("format") or "").strip()
        return {
            "relevance": _clamp(float(data.get("relevance", 5.0))),
            "reaction_potential": _clamp(float(data.get("reaction_potential", 5.0))),
            "angle": (data.get("angle") or "").strip(),
            "topic": (data.get("topic") or "").strip().lower().replace(" ", "-"),
            "format": fmt if fmt in CHOOSABLE_FORMATS else "hot_take",
            "reasoning": (data.get("reasoning") or "").strip(),
        }

    # -------------------------------------------------------- composition
    def composite(self, subscores: dict[str, float]) -> float:
        w = settings.weights
        return round(sum(subscores[k] * w[k] for k in w), 3)

    def tier(self, score: float) -> str:
        if score >= settings.tier_fire:
            return "FIRE"
        if score >= settings.tier_warm:
            return "WARM"
        if score >= settings.tier_cool:
            return "COOL"
        return "SKIP"

    def score_article(self, article: dict, account: dict, now: Optional[datetime] = None,
                      hist_perf: Optional[dict] = None) -> dict:
        """Full score for one article. Returns a signal dict ready for memory.

        If the source supplied a real velocity_hint (reddit upvotes/hr, trends
        traffic, wiki edit burst), that is used as the velocity subscore instead
        of the recency proxy — the point where velocity stops being a guess.
        window_urgency stays recency-based (time left in the first-mover window).

        hist_perf is the account's approve/reject performance map from
        style.learning.historical_performance ({"overall": x, "by_vertical":
        {...}}); the article's vertical is preferred, falling back to overall,
        falling back to neutral 5.0 when no reviews exist yet.
        """
        recency_vel, window = self.recency_scores(article.get("published_at"), now=now)
        hint = article.get("velocity_hint")
        velocity = float(hint) if hint is not None else recency_vel
        hp = 5.0
        if hist_perf:
            hp = hist_perf.get("by_vertical", {}).get(
                article.get("vertical"), hist_perf.get("overall", 5.0))
        judged = self.judge(article, account)
        subscores = {
            "velocity": velocity,
            "relevance": judged["relevance"],
            "reaction_potential": judged["reaction_potential"],
            "window_urgency": window,
            "historical_perf": hp,
        }
        score = self.composite(subscores)
        return {
            "article_id": article.get("id"),
            "account_id": account.get("id"),
            "score": score,
            "tier": self.tier(score),
            **subscores,
            "angle": judged["angle"],
            "topic": judged["topic"],
            "format": judged["format"],
            "reasoning": judged["reasoning"],
            "velocity_is_real": hint is not None,
        }

    def _is_stale(self, article: dict, now: datetime) -> bool:
        """True if older than the staleness cutoff (don't pay to score old news)."""
        cutoff = settings.stale_after_min
        if not cutoff:
            return False
        pub = article.get("published_at")
        if not pub:
            return False
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return (now - dt).total_seconds() / 60.0 > cutoff

    # -------------------------------------------------------------- driver
    def run(self, account: dict, limit: int = 50, db_path: Optional[str] = None,
            per_account: bool = True) -> dict[str, int]:
        """Score articles for this account, store signals, record them as scored.

        per_account=True (default) uses the per-account queue filtered to the
        account's verticals/regions, so each persona scores only its lanes and
        never re-scores (the multi-account path). per_account=False falls back to
        the global unprocessed queue (legacy single-account behavior).
        Articles past the staleness cutoff are skipped (and still marked) so the
        first run doesn't burn Claude calls on yesterday's news.
        """
        now = datetime.now(timezone.utc)
        tally = {"FIRE": 0, "WARM": 0, "COOL": 0, "SKIP": 0, "stale_skipped": 0}
        # One approve/reject performance lookup per run, applied to every
        # article in the batch. Lazy import keeps pipeline->style coupling soft.
        try:
            from style.learning import historical_performance
            hist_perf = historical_performance(account["id"], db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("historical_perf unavailable, using neutral 5.0: %s", exc)
            hist_perf = None
        if per_account:
            queue = memory.get_unscored_for_account(account, limit=limit, db_path=db_path)
        else:
            queue = memory.get_unprocessed_articles(limit=limit, db_path=db_path)

        for art in queue:
            try:
                if self._is_stale(art, now):
                    tally["stale_skipped"] += 1
                    if per_account:
                        memory.mark_scored(account["id"], art["id"], db_path=db_path)
                    else:
                        memory.mark_processed(art["id"], db_path=db_path)
                    continue
                signal = self.score_article(art, account, now=now, hist_perf=hist_perf)
                memory.insert_signal(signal, db_path=db_path)
                # FIRE/WARM stories enter the memory timeline — this is what
                # the context retriever mines later. Deduped by URL, so two
                # personas scoring the same story log one event.
                if signal["tier"] in ("FIRE", "WARM") and signal.get("topic"):
                    memory.seed_event(
                        topic=signal["topic"], summary=art["title"],
                        source_url=art.get("url"),
                        event_date=art.get("published_at"), db_path=db_path,
                    )
                if per_account:
                    memory.mark_scored(account["id"], art["id"], db_path=db_path)
                else:
                    memory.mark_processed(art["id"], db_path=db_path)
                tally[signal["tier"]] += 1
                vflag = "v*" if signal.get("velocity_is_real") else "v~"
                logger.info("[%s %.2f %s] %s", signal["tier"], signal["score"],
                            vflag, art["title"][:64])
            except Exception as exc:  # noqa: BLE001
                logger.error("Scoring failed for article %s: %s", art.get("id"), exc)
        return tally


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    memory.init_db()
    acct = memory.get_account(
        memory.upsert_account(
            handle="me",
            niche="data-backed Indian economic policy commentary, skeptical of govt spin",
            topics=["economic policy", "fiscal data", "BJP criticism"],
        )
    )
    agent = DecisionAgent()
    print(agent.run(acct))
