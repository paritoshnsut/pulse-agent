"""
callbacks.py — the callback generator. The payoff of the predictions tracker.

Every prediction you post is sitting in predictions_tracker (filed by
pipeline/updater.py). This module is the other half: it watches the incoming
article stream for the outcome, and the moment a story resolves one of your
open predictions it drafts the "I called this" post — CLAUDE.md ranks the
callback among the most viral formats, and it only works if someone remembered
what you said. Your agent remembers.

Refuted predictions get drafted too ("I got this one wrong"): owning a miss
publicly is a credibility play the format instruction handles explicitly.

COST DISCIPLINE (measure-then-judge, as everywhere):
  * Deterministic prefilter, free: keyword overlap between the prediction and
    articles fetched since the last check. An article must share at least
    CALLBACK_MIN_KEYWORD_HITS distinct keywords before any model spend.
  * One Claude verification call per prediction per cycle, only when
    candidates survive the prefilter. The verifier is strict: most articles do
    NOT resolve a prediction, and "unresolved" is the expected answer.
  * A per-prediction cursor (last_checked_at) guarantees each article is
    considered at most once per prediction — quiet cycles cost zero.

Resolved predictions flow into the normal copilot lane: the callback draft is
persisted, gated by the persona scorer, and pushed to your Telegram like any
other draft. Predictions older than CALLBACK_EXPIRE_DAYS are marked expired.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from pipeline import memory, poster
from pipeline.context import extract_keywords
from pipeline.generator import ContentGenerator
from style.crowd import effective_genome
from style.scorer import PersonaConsistencyScorer

logger = logging.getLogger("callbacks")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You verify whether news articles resolve a specific past prediction. You "
    "are strict: an article only CONFIRMS a prediction if it clearly reports "
    "the predicted thing happening, and only REFUTES it if it clearly reports "
    "the opposite outcome. Related coverage, speculation, or partial movement "
    "is UNRESOLVED — that is the most common answer and the safe default. "
    "Respond with ONLY a JSON object, no fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


# --------------------------------------------------------------------------- #
# Deterministic prefilter (pure function, unit-testable)
# --------------------------------------------------------------------------- #
def rank_candidates(articles: list[dict], keywords: list[str],
                    min_hits: Optional[int] = None,
                    cap: Optional[int] = None) -> list[dict]:
    """Keep articles sharing >= min_hits distinct keywords with the prediction,
    best-matching first, capped. This gate is what keeps the Claude bill flat."""
    min_hits = min_hits if min_hits is not None else settings.callback_min_keyword_hits
    cap = cap or settings.callback_max_candidates
    min_hits = min(min_hits, len(keywords)) or 1  # short predictions still checkable
    scored = []
    for art in articles:
        text = f"{art.get('title') or ''} {art.get('description') or ''}".lower()
        hits = sum(1 for kw in keywords if kw in text)
        if hits >= min_hits:
            scored.append((hits, art))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:cap]]


class CallbackWatcher:
    """Matches open predictions against incoming news; drafts the callback."""

    def __init__(self, client: Any = None, model: Optional[str] = None,
                 db_path: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model
        self.db_path = db_path

    @property
    def client(self) -> Any:
        if self._client is None:
            settings.require_anthropic()
            from anthropic import Anthropic

            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    # -------------------------------------------------------------- verify
    def _build_prompt(self, pred: dict, candidates: list[dict]) -> str:
        arts = "\n".join(
            f"  {i}. {a['title']} — {a.get('description') or '(no summary)'} "
            f"({a.get('source_name') or 'unknown'}, {(a.get('published_at') or '?')[:10]})"
            for i, a in enumerate(candidates, 1)
        )
        return (
            f"THE PREDICTION (made {pred['made_at'][:10]}"
            + (f", horizon: {pred['horizon']}" if pred.get("horizon") else "")
            + f"):\n  \"{pred['prediction']}\"\n\n"
            f"CANDIDATE ARTICLES:\n{arts}\n\n"
            "Does any article clearly resolve the prediction? Return JSON:\n"
            '  "resolution": "confirmed" | "refuted" | "unresolved",\n'
            '  "article_index": the 1-based index of the resolving article, or null,\n'
            '  "outcome": one sentence stating what actually happened, or "".'
        )

    def verify(self, pred: dict, candidates: list[dict]) -> dict:
        msg = self.client.messages.create(
            model=self.model, max_tokens=250,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(pred, candidates)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            data = json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Verifier returned non-JSON; treating as unresolved. Raw: %s",
                         text[:200])
            return {"resolution": "unresolved", "article_index": None, "outcome": ""}
        resolution = data.get("resolution")
        idx = data.get("article_index")
        valid_idx = isinstance(idx, int) and 1 <= idx <= len(candidates)
        if resolution not in ("confirmed", "refuted") or not valid_idx:
            return {"resolution": "unresolved", "article_index": None, "outcome": ""}
        return {"resolution": resolution, "article_index": idx,
                "outcome": (data.get("outcome") or "").strip()}

    # --------------------------------------------------------------- draft
    def _draft_callback(self, pred: dict, article: dict, verdict: dict,
                        account: dict) -> Optional[dict]:
        dna = memory.get_style_dna(account["id"], db_path=self.db_path)
        if not dna:
            logger.warning("[%s] prediction resolved but no Style DNA — not drafting.",
                           account.get("handle"))
            return None
        genome = effective_genome(dna["genome_a"], dna["genome_b"], dna["blend"])
        word = verdict["resolution"].upper()
        signal = {
            "title": article["title"],
            "source_name": article.get("source_name"),
            "description": article.get("description"),
            "article_id": article.get("id"),
            "angle": (f"callback on your own prediction — it was {word}. "
                      f"You said: \"{pred['prediction']}\""),
        }
        context = (
            f"Your prediction, posted {pred['made_at'][:10]}"
            + (f" (topic: {pred['topic']})" if pred.get("topic") else "")
            + f": \"{pred['prediction']}\"\n"
            f"What just happened: {verdict['outcome'] or article['title']} "
            f"-> prediction {word}."
        )
        gen = ContentGenerator(client=self._client, model=self.model)
        draft = gen.generate_checked(
            signal, genome, fmt="callback", scorer=PersonaConsistencyScorer(
                client=self._client, model=self.model) if self._client else PersonaConsistencyScorer(),
            account_id=account["id"], persist=True, db_path=self.db_path,
            context=context,
        )
        if draft.get("post_id"):
            poster.TelegramNotifier().notify_draft(
                memory.get_post(draft["post_id"], db_path=self.db_path),
                f"CALLBACK ({word}): {article['title']}")
        return draft

    # ----------------------------------------------------------------- run
    def _expire_if_old(self, pred: dict, now: datetime) -> bool:
        made = datetime.fromisoformat(pred["made_at"].replace("Z", "+00:00"))
        if now - made > timedelta(days=settings.callback_expire_days):
            memory.resolve_prediction(
                pred["id"], status="expired",
                outcome=f"expired unresolved after {settings.callback_expire_days} days",
                db_path=self.db_path)
            return True
        return False

    def process_prediction(self, pred: dict, account: dict) -> str:
        """One prediction, one cycle. Returns what happened:
        expired | no_candidates | unresolved | confirmed | refuted."""
        now = datetime.now(timezone.utc)
        if self._expire_if_old(pred, now):
            return "expired"
        keywords = extract_keywords(
            (pred.get("topic") or "").replace("-", " "), pred["prediction"])
        cursor = pred.get("last_checked_at") or pred["made_at"]
        raw = memory.find_articles_fetched_after(keywords, cursor, db_path=self.db_path)
        candidates = rank_candidates(raw, keywords)
        memory.touch_prediction_checked(pred["id"], now.isoformat(), db_path=self.db_path)
        if not candidates:
            return "no_candidates"
        verdict = self.verify(pred, candidates)
        if verdict["resolution"] == "unresolved":
            return "unresolved"
        article = candidates[verdict["article_index"] - 1]
        memory.resolve_prediction(pred["id"], status=verdict["resolution"],
                                  outcome=verdict["outcome"] or article["title"],
                                  db_path=self.db_path)
        logger.info("[%s] prediction #%d %s: %s", account.get("handle"),
                    pred["id"], verdict["resolution"], pred["prediction"][:60])
        self._draft_callback(pred, article, verdict, account)
        return verdict["resolution"]

    def run(self, account: Optional[dict] = None) -> dict[str, int]:
        """Check every open prediction (one account, or all active)."""
        accounts = [account] if account else memory.list_active_accounts(db_path=self.db_path)
        tally = {"checked": 0, "no_candidates": 0, "unresolved": 0,
                 "confirmed": 0, "refuted": 0, "expired": 0}
        for acct in accounts:
            for pred in memory.get_open_predictions(acct["id"], db_path=self.db_path):
                tally["checked"] += 1
                try:
                    outcome = self.process_prediction(pred, acct)
                    tally[outcome] = tally.get(outcome, 0) + 1
                except Exception as exc:  # noqa: BLE001
                    logger.error("Callback check failed for prediction %s: %s",
                                 pred["id"], exc)
        return tally


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    memory.init_db()
    print(CallbackWatcher().run())
