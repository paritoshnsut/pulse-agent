"""
crowd.py — Session 12. Genome B: crowd wisdom.

Genome A answers "how do YOU sound". Genome B answers "what is WORKING in your
niche right now": it scrapes the week's top-performing posts (1000+ likes) in
the account's keywords and distills the structural patterns — hooks, shapes,
emotional registers — that the crowd is rewarding.

CRITICAL DISTINCTION (this is what keeps the voice yours): Genome B contributes
STRUCTURE, never voice. The generator borrows "lead with the number, one-line
paragraphs, end on a question" from the crowd; sarcasm level, vocabulary,
signature phrases stay 100% Genome A. The `blend` knob (style_dna.blend,
default 0.4 per CLAUDE.md) controls how hard the crowd patterns are pushed in
the prompt, 0 = ignore the crowd entirely.

measure-then-judge, same as dna.py:
  * MEASURED in Python via dna.measure(): lengths, question/caps/emoji rates,
    hashtag habits of the winning posts. Exact, never hallucinated.
  * JUDGED by Claude: hook patterns, structural shapes, emotional registers,
    topics that are landing.

DATA SOURCE: TwitterAPI.io advanced search (~$0.01/call, per CLAUDE.md). The
fetcher is injectable and the module no-ops gracefully without a key — same
posture as watch/twitter.py: no key, no fragile scraper, no pretending.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

from config import settings
from pipeline.llm import tracked_create
from pipeline import memory
from style import dna

logger = logging.getLogger("crowd")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

TWITTERAPI_IO_SEARCH = "https://api.twitterapi.io/twitter/tweet/advanced_search"

SYSTEM_PROMPT = (
    "You are a viral-content analyst. You study a niche's top-performing posts "
    "and extract the STRUCTURAL and LINGUISTIC patterns behind their reach — "
    "hook construction, post shape, emotional register. You describe reusable "
    "patterns, never individual posts, and you never extract anyone's personal "
    "voice or signature phrasing. Respond with ONLY a JSON object, no fences."
)


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


# --------------------------------------------------------------------------- #
# Blending — consumed by the generator
# --------------------------------------------------------------------------- #
def effective_genome(genome_a: dict, genome_b: Optional[dict] = None,
                     blend: float = 0.4) -> dict:
    """Merge the two genomes into the dict the generator prompts with.

    All voice-identity fields come from Genome A untouched. Genome B is folded
    in as a `crowd_patterns` block (structure-only guidance) whose prompt
    emphasis scales with `blend`. blend<=0 or no Genome B -> pure Genome A,
    so everything built before this module keeps working unchanged.
    """
    merged = dict(genome_a)
    if not genome_b or blend <= 0:
        return merged
    merged["crowd_patterns"] = {
        "weight": round(min(blend, 1.0), 2),
        "hooks": (genome_b.get("hook_patterns") or [])[:5],
        "structures": (genome_b.get("structural_patterns") or [])[:5],
        "emotional_registers": (genome_b.get("emotional_registers") or [])[:3],
    }
    return merged


# --------------------------------------------------------------------------- #
# Scraper + extractor
# --------------------------------------------------------------------------- #
class CrowdWisdomScraper:
    """Fetches the niche's top posts and distills Genome B.

    Both the Anthropic client and the HTTP fetcher are injectable for tests.
    A custom `fetcher` takes (query: str, limit: int) and returns a list of
    tweet dicts with at least a "text" key (likeCount optional, for ordering).
    """

    def __init__(self, client: Any = None, model: Optional[str] = None,
                 fetcher: Optional[Callable[[str, int], list[dict]]] = None) -> None:
        self._client = client
        self.model = model or settings.model
        self._fetcher = fetcher

    @property
    def client(self) -> Any:
        if self._client is None:
            settings.require_anthropic()
            from anthropic import Anthropic

            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    # ------------------------------------------------------------- fetching
    @staticmethod
    def build_query(keywords: list[str], min_likes: int) -> str:
        """Twitter advanced-search query: any keyword, likes floor, no replies."""
        kw = " OR ".join(f'"{k}"' if " " in k else k for k in keywords)
        return f"({kw}) min_faves:{min_likes} -filter:replies"

    def _default_fetch(self, query: str, limit: int) -> list[dict]:
        """Pull top tweets from TwitterAPI.io, paginating until `limit`."""
        import requests

        headers = {"X-API-Key": settings.twitter_api_io_key}
        tweets: list[dict] = []
        cursor = ""
        while len(tweets) < limit:
            params = {"query": query, "queryType": "Top"}
            if cursor:
                params["cursor"] = cursor
            resp = requests.get(TWITTERAPI_IO_SEARCH, headers=headers,
                                params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("tweets") or []
            if not batch:
                break
            tweets.extend(batch)
            if not data.get("has_next_page"):
                break
            cursor = data.get("next_cursor") or ""
            if not cursor:
                break
        return tweets[:limit]

    def fetch_top_posts(self, keywords: list[str],
                        min_likes: Optional[int] = None,
                        limit: Optional[int] = None) -> list[dict]:
        """Top posts for the niche keywords. [] (logged) when no key and no
        injected fetcher — callers treat that as 'crowd layer not enabled'."""
        min_likes = min_likes or settings.crowd_min_likes
        limit = limit or settings.crowd_top_k
        query = self.build_query(keywords, min_likes)
        if self._fetcher is not None:
            raw = self._fetcher(query, limit)
        elif settings.twitter_api_io_key:
            raw = self._default_fetch(query, limit)
        else:
            logger.info("No TWITTER_API_IO_KEY set — crowd wisdom skipped.")
            return []
        # Highest-engagement first so prompt truncation keeps the best evidence.
        raw.sort(key=lambda t: t.get("likeCount", 0), reverse=True)
        return [t for t in raw if (t.get("text") or "").strip()]

    # ------------------------------------------------------------ extraction
    def _build_user_prompt(self, texts: list[str], measured: dict) -> str:
        sample = texts[:40]
        joined = "\n".join(f"- {t}" for t in sample)
        return (
            f"MEASURED STATISTICS of the winning posts (ground truth):\n"
            f"  avg length: {measured['avg_post_length']}\n"
            f"  emoji usage: {measured['emoji_usage']}\n"
            f"  rhetorical questions: {measured['uses_rhetorical_questions']}\n"
            f"  ALL-CAPS emphasis: {measured['caps_for_emphasis']}\n"
            f"  hashtag style: {measured['hashtag_style']}\n\n"
            f"TOP-PERFORMING POSTS IN THE NICHE ({len(sample)} of {len(texts)}):\n"
            f"{joined}\n\n"
            "Extract the reusable patterns behind their performance. Return JSON "
            "with exactly these keys:\n"
            '  "hook_patterns": array of 3-5 first-line construction patterns '
            '(e.g. "open with a stark number, no context"),\n'
            '  "structural_patterns": array of 3-5 post-shape patterns '
            '(e.g. "one-line paragraphs", "setup then twist in last line"),\n'
            '  "emotional_registers": array of 1-3 dominant emotions being '
            'rewarded (e.g. "outrage", "curiosity"),\n'
            '  "winning_topics": array of the subjects currently landing.\n'
            "Patterns must be structural and transferable — never quote or "
            "imitate a specific author's voice."
        )

    def judge(self, texts: list[str], measured: dict) -> dict:
        msg = tracked_create(self.client, "crowd",
            
            model=self.model,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_user_prompt(texts, measured)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            return json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Could not parse crowd JSON. Raw: %s", text[:200])
            return {}

    def extract(self, texts: list[str]) -> dict:
        """Winning-post texts -> Genome B. Raises on empty input."""
        texts = [t.strip() for t in texts if t and t.strip()]
        if not texts:
            raise ValueError("No non-empty crowd posts provided.")
        measured = dna.measure(texts)
        judged = self.judge(texts, measured)
        return {
            "hook_patterns": judged.get("hook_patterns", []),
            "structural_patterns": judged.get("structural_patterns", []),
            "emotional_registers": judged.get("emotional_registers", []),
            "winning_topics": judged.get("winning_topics", []),
            "avg_post_length": measured["avg_post_length"],          # measured
            "emoji_usage": measured["emoji_usage"],                  # measured
            "uses_rhetorical_questions": measured["uses_rhetorical_questions"],
            "hashtag_style": measured["hashtag_style"],              # measured
            "sample_count": len(texts),
        }

    # ----------------------------------------------------------- persistence
    def refresh(self, account: dict, db_path: Optional[str] = None) -> Optional[dict]:
        """Scrape the account's niche, extract Genome B, save a new style_dna
        version (Genome A and blend carried forward). Returns the new Genome B,
        or None if the crowd layer isn't enabled / has nothing to learn from.

        Requires an existing Genome A — the crowd layer tunes a voice, it
        doesn't replace building one.
        """
        current = memory.get_style_dna(account["id"], db_path=db_path)
        if not current:
            logger.warning("[%s] no Style DNA yet — build Genome A before Genome B.",
                           account.get("handle"))
            return None
        keywords = account.get("topics") or []
        if not keywords:
            logger.warning("[%s] no topics on the account — nothing to search.",
                           account.get("handle"))
            return None
        tweets = self.fetch_top_posts(keywords)
        if not tweets:
            return None
        genome_b = self.extract([t["text"] for t in tweets])
        memory.save_style_dna(
            account_id=account["id"],
            genome_a=current["genome_a"],
            genome_b=genome_b,
            blend=current["blend"],
            sample_count=current["sample_count"],
            db_path=db_path,
        )
        logger.info("[%s] Genome B refreshed from %d winning posts.",
                    account.get("handle"), genome_b["sample_count"])
        return genome_b


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Refresh Genome B (crowd wisdom) per account")
    ap.add_argument("--account", help="only this handle (default: all active)")
    args = ap.parse_args()
    memory.init_db()
    scraper = CrowdWisdomScraper()
    for acct in memory.list_active_accounts():
        if args.account and acct["handle"] != args.account:
            continue
        gb = scraper.refresh(acct)
        if gb:
            print(f"\n[{acct['handle']}]")
            print(json.dumps(gb, indent=2, ensure_ascii=False))
