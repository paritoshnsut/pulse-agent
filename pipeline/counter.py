"""
counter.py — the counter-narrative detector (Session 11 / intelligence #5).

When a story is big enough that everyone is covering it, the consensus take is
already noise by the time you post it. The contrarian gap is where reach lives.
This module finds FIRE stories with heavy coverage in the articles DB, asks
Claude what the herd is saying and what angle is missing, and — only when a
genuine gap exists — drafts a counter_narrative post into the normal review
lane.

COST DISCIPLINE:
  * Targets are FIRE signals only, from the last 24h, with at least
    COUNTER_MIN_COVERAGE (3) related articles already ingested — coverage
    breadth is measured for free from our own DB, not fetched.
  * One detection call per target per run, and a signal that already has a
    counter_narrative draft is never re-targeted, so each story is analyzed
    at most once.
  * The detector is allowed to say "no real gap" (worth=false) and the prompt
    treats that as the honest common answer — no forced hot contrarianism.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from pipeline.llm import tracked_create
from pipeline import memory, poster
from pipeline.context import ContextRetriever, extract_keywords
from pipeline.generator import ContentGenerator
from style.crowd import effective_genome
from style.scorer import PersonaConsistencyScorer

logger = logging.getLogger("counter")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

SYSTEM_PROMPT = (
    "You analyze press coverage of one story and identify the consensus "
    "narrative and the legitimate angle nobody is covering. You are honest: "
    "if the coverage already spans the story's real angles, you say there is "
    "no gap. A manufactured contrarian take is worse than none. Respond with "
    "ONLY a JSON object, no fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


class CounterNarrativeDetector:
    """Finds the uncovered angle on heavily-covered stories. Client injectable."""

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

    # -------------------------------------------------------------- targets
    def find_targets(self, account: dict, hours: int = 24) -> list[tuple[dict, list[dict]]]:
        """FIRE signals for this account from the last `hours` with enough
        related coverage and no counter draft yet. Returns (signal, coverage)."""
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        countered = {p.get("signal_id")
                     for p in memory.get_posts(account_id=account["id"], db_path=self.db_path)
                     if p["format"] == "counter_narrative"}
        targets = []
        for s in memory.get_signals_by_tier("FIRE", db_path=self.db_path):
            if (s.get("account_id") != account["id"] or s["created_at"] <= since
                    or s["id"] in countered
                    # already analyzed once (verdict was "no gap") — don't re-spend
                    or memory.kv_get(f"counter_seen:{s['id']}", db_path=self.db_path)):
                continue
            keywords = extract_keywords(
                (s.get("topic") or "").replace("-", " "), s.get("title"))
            coverage = memory.find_related_articles(
                keywords, exclude_article_id=s.get("article_id"),
                limit=10, db_path=self.db_path)
            if len(coverage) >= settings.counter_min_coverage:
                targets.append((s, coverage))
        return targets

    # --------------------------------------------------------------- detect
    def detect(self, signal: dict, coverage: list[dict]) -> dict:
        arts = "\n".join(f"  - {a['title']} ({a.get('source_name') or 'unknown'})"
                         for a in coverage[:10])
        prompt = (
            f"THE STORY: {signal.get('title')}\n\n"
            f"EXISTING COVERAGE ({len(coverage)} pieces):\n{arts}\n\n"
            "Return JSON:\n"
            '  "consensus": one sentence — what everyone is saying,\n'
            '  "missing_angle": one sentence — the legitimate angle nobody has '
            "taken, grounded in the story itself,\n"
            '  "worth": true ONLY if the missing angle is genuinely strong; '
            "false if coverage already has the story covered."
        )
        msg = tracked_create(self.client, "counter",
            
            model=self.model, max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            data = json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Detector returned non-JSON; skipping. Raw: %s", text[:200])
            return {"worth": False, "consensus": "", "missing_angle": ""}
        return {
            "worth": bool(data.get("worth")) and bool((data.get("missing_angle") or "").strip()),
            "consensus": (data.get("consensus") or "").strip(),
            "missing_angle": (data.get("missing_angle") or "").strip(),
        }

    # ----------------------------------------------------------------- run
    def _draft(self, signal: dict, found: dict, account: dict) -> Optional[dict]:
        dna = memory.get_style_dna(account["id"], db_path=self.db_path)
        if not dna:
            return None
        genome = effective_genome(dna["genome_a"], dna["genome_b"], dna["blend"])
        counter_signal = {**signal, "angle": found["missing_angle"]}
        base_ctx = ContextRetriever(db_path=self.db_path).context_for(signal, account)
        consensus = f"What every outlet is saying (push against this): {found['consensus']}"
        context = f"{base_ctx}\n{consensus}" if base_ctx else consensus
        gen = ContentGenerator(client=self._client, model=self.model)
        scorer = (PersonaConsistencyScorer(client=self._client, model=self.model)
                  if self._client else PersonaConsistencyScorer())
        from pipeline.grounding import GroundingChecker
        grounding = (GroundingChecker(client=self._client, model=self.model)
                     if settings.grounding_enabled else None)
        draft = gen.generate_checked(
            counter_signal, genome, fmt="counter_narrative", scorer=scorer,
            account_id=account["id"], persist=True, db_path=self.db_path,
            context=context, grounding=grounding,
        )
        if draft.get("post_id"):
            poster.TelegramNotifier().notify_draft(
                memory.get_post(draft["post_id"], db_path=self.db_path),
                f"COUNTER-NARRATIVE: {signal['title']}")
        return draft

    def run(self, account: Optional[dict] = None) -> dict[str, int]:
        accounts = [account] if account else memory.list_active_accounts(db_path=self.db_path)
        tally = {"targets": 0, "no_gap": 0, "drafted": 0}
        for acct in accounts:
            for signal, coverage in self.find_targets(acct):
                tally["targets"] += 1
                try:
                    found = self.detect(signal, coverage)
                    memory.kv_set(f"counter_seen:{signal['id']}", "1",
                                  db_path=self.db_path)
                    if not found["worth"]:
                        tally["no_gap"] += 1
                        continue
                    if self._draft(signal, found, acct):
                        tally["drafted"] += 1
                        logger.info("[%s] counter-narrative drafted: %s",
                                    acct["handle"], found["missing_angle"][:70])
                except Exception as exc:  # noqa: BLE001
                    logger.error("Counter detection failed for signal %s: %s",
                                 signal["id"], exc)
        return tally


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    memory.init_db()
    print(CounterNarrativeDetector().run())
