"""
dna.py — Session 4. The Style DNA extractor. This is the moat.

It turns a pile of your past posts into Genome A: the JSON voice profile from
CLAUDE.md that every generated post is later constrained against.

ARCHITECTURE: hybrid measure-then-judge.
  * MEASURED in Python (deterministic, never hallucinated): average post length,
    emoji usage, hashtag count/case/position, ALL-CAPS-for-emphasis rate,
    rhetorical-question rate, a rough Hinglish ratio, and candidate signature
    phrases (frequent n-grams).
  * JUDGED by Claude (genuine qualitative calls): sarcasm level, sentence
    rhythm, tone, which candidate phrases are real signatures, preferred topics,
    things to avoid.
  * MERGED so measured numbers always win over the model's guesses for anything
    countable. Average length is arithmetic, not vibes.

Why split it this way: an LLM asked "what's the average post length" will make
up a plausible number. Counting characters is free and exact. Reserve the model
for what only judgment can do.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Optional

from config import settings
from pipeline import memory

logger = logging.getLogger("dna")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# Broad emoji coverage (symbols, pictographs, flags, dingbats, variation selectors).
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF]"
)
HASHTAG = re.compile(r"#\w+")
WORD = re.compile(r"[A-Za-z']+")
ALLCAPS = re.compile(r"\b[A-Z]{2,}\b")

# Stopwords for n-gram filtering (English + common romanized Hindi function words).
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "been", "this", "that", "it", "as",
    "at", "by", "from", "you", "your", "we", "our", "they", "their", "i", "me",
    "my", "he", "she", "his", "her", "has", "have", "had", "do", "does", "did",
    "not", "no", "so", "up", "out", "what", "who", "how", "why", "will", "just",
    "hai", "hain", "ka", "ki", "ke", "ko", "se", "mein", "aur", "bhi", "toh",
}

# Seed lexicon for a rough Hinglish ratio. Claude refines the qualitative read;
# this is only a measurable proxy so the number isn't invented.
HINGLISH_SEED = {
    "kya", "nahi", "nahin", "kar", "karo", "karke", "matlab", "yaar", "bhai",
    "sab", "log", "koi", "kuch", "bohot", "bahut", "accha", "theek", "paisa",
    "sarkar", "desh", "kaam", "baat", "dekho", "suno", "abhi", "kyun", "kyu",
    "raha", "rahe", "rahi", "gaya", "gaye", "diya", "liya", "wala", "wale",
    "wali", "hum", "tum", "aap", "unka", "iska", "uska", "jab", "tab", "phir",
}


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


# --------------------------------------------------------------------------- #
# Deterministic feature measurement (pure functions, fully unit-testable)
# --------------------------------------------------------------------------- #
def avg_length(posts: list[str]) -> int:
    return round(sum(len(p) for p in posts) / len(posts)) if posts else 0


def emoji_rate(posts: list[str]) -> float:
    """Fraction of posts containing at least one emoji."""
    if not posts:
        return 0.0
    return round(sum(1 for p in posts if EMOJI.search(p)) / len(posts), 3)


def emoji_band(rate: float) -> str:
    if rate == 0:
        return "none"
    if rate < 0.15:
        return "rare"
    if rate < 0.5:
        return "moderate"
    return "frequent"


def caps_rate(posts: list[str]) -> float:
    """Fraction of posts using an ALL-CAPS word (>=2 letters) for emphasis."""
    if not posts:
        return 0.0
    return round(sum(1 for p in posts if ALLCAPS.search(p)) / len(posts), 3)


def question_rate(posts: list[str]) -> float:
    if not posts:
        return 0.0
    return round(sum(1 for p in posts if "?" in p) / len(posts), 3)


def hinglish_ratio(posts: list[str]) -> float:
    """Share of word tokens that are in the romanized-Hindi seed lexicon."""
    tokens = [w.lower() for p in posts for w in WORD.findall(p)]
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in HINGLISH_SEED)
    return round(hits / len(tokens), 2)


def hashtag_profile(posts: list[str]) -> dict:
    """Average count, dominant case, and dominant position of hashtags."""
    counts, cases, positions = [], [], []
    for p in posts:
        tags = HASHTAG.findall(p)
        counts.append(len(tags))
        if not tags:
            continue
        bodies = [t[1:] for t in tags]
        cases.append("lowercase" if all(b.islower() for b in bodies) else "mixed")
        # position == "end" iff every hashtag sits in the trailing run of tags
        # (i.e. nothing but tags/whitespace after the first of them). Robust to a
        # final tag that begins before the 80% mark but still closes the post.
        trailing = re.search(r"(?:\s*#\w+\s*)+$", p.rstrip())
        in_tail = len(HASHTAG.findall(trailing.group(0))) if trailing else 0
        positions.append("end" if in_tail == len(tags) else "inline")
    nonzero = [c for c in counts if c]
    avg = round(sum(nonzero) / len(nonzero), 1) if nonzero else 0
    dom_case = Counter(cases).most_common(1)[0][0] if cases else "n/a"
    dom_pos = Counter(positions).most_common(1)[0][0] if positions else "n/a"
    return {"avg_count": avg, "case": dom_case, "position": dom_pos}


def hashtag_descriptor(profile: dict) -> str:
    if not profile["avg_count"]:
        return "rarely uses hashtags"
    return f"~{profile['avg_count']}, {profile['case']}, at {profile['position']}"


def ngram_candidates(posts: list[str], n_range=(2, 4), min_doc_freq: int = 2, top_k: int = 15) -> list[str]:
    """Frequent multi-word phrases, by document frequency (posts containing them).

    Document frequency (not raw count) is used so one ranty post can't crown a
    phrase a 'signature'. Grams made entirely of stopwords are dropped.
    """
    doc_freq: Counter[str] = Counter()
    for p in posts:
        toks = [w.lower() for w in WORD.findall(p)]
        seen: set[str] = set()
        for n in range(n_range[0], n_range[1] + 1):
            for i in range(len(toks) - n + 1):
                gram = toks[i : i + n]
                if all(t in STOPWORDS for t in gram):
                    continue
                phrase = " ".join(gram)
                if phrase not in seen:
                    seen.add(phrase)
                    doc_freq[phrase] += 1
    ranked = [(p, f) for p, f in doc_freq.items() if f >= min_doc_freq]
    # Prefer longer, more frequent phrases; trim sub-phrases swallowed by a longer one.
    ranked.sort(key=lambda x: (x[1], len(x[0].split())), reverse=True)
    chosen: list[str] = []
    for phrase, _ in ranked:
        if any(phrase in longer and phrase != longer for longer in chosen):
            continue
        chosen.append(phrase)
        if len(chosen) >= top_k:
            break
    return chosen


def measure(posts: list[str]) -> dict:
    """All deterministic features in one pass."""
    er = emoji_rate(posts)
    ht = hashtag_profile(posts)
    return {
        "avg_post_length": f"{avg_length(posts)} chars",
        "emoji_usage": emoji_band(er),
        "emoji_rate": er,
        "caps_for_emphasis": caps_rate(posts) > 0.15,
        "caps_rate": caps_rate(posts),
        "uses_rhetorical_questions": question_rate(posts) > 0.2,
        "question_rate": question_rate(posts),
        "hinglish_mix": hinglish_ratio(posts),
        "hashtag_style": hashtag_descriptor(ht),
        "_hashtag_profile": ht,
        "_ngram_candidates": ngram_candidates(posts),
    }


# --------------------------------------------------------------------------- #
# Extractor (Claude for the qualitative half)
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "You are a linguistic style analyst. You characterize a writer's voice from "
    "samples and measured statistics. You never invent counts that were already "
    "measured for you. Respond with ONLY a JSON object, no prose, no fences."
)


class StyleDNAExtractor:
    """Builds Genome A from posts. Anthropic client is injectable for testing."""

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

    def _build_user_prompt(self, posts: list[str], measured: dict) -> str:
        sample = posts[:40]  # cap tokens; the stats already summarize the rest
        joined = "\n".join(f"- {p}" for p in sample)
        return (
            f"MEASURED STATISTICS (already computed — treat as ground truth):\n"
            f"  avg length: {measured['avg_post_length']}\n"
            f"  emoji usage: {measured['emoji_usage']}\n"
            f"  ALL-CAPS emphasis: {measured['caps_for_emphasis']}\n"
            f"  rhetorical questions: {measured['uses_rhetorical_questions']}\n"
            f"  hinglish ratio (rough): {measured['hinglish_mix']}\n"
            f"  hashtag style: {measured['hashtag_style']}\n\n"
            f"CANDIDATE RECURRING PHRASES (from frequency analysis):\n"
            f"  {measured['_ngram_candidates']}\n\n"
            f"POST SAMPLES ({len(sample)} of {len(posts)}):\n{joined}\n\n"
            "Return JSON with exactly these keys:\n"
            '  "sentence_length": short description (e.g. "short, punchy, fragments ok"),\n'
            '  "sarcasm_level": one of "none" | "low" | "moderate" | "high",\n'
            '  "tone": 1-3 word tone label,\n'
            '  "signature_phrases": array — ONLY the candidate phrases that are '
            "genuine stylistic signatures (drop generic ones); refine wording if needed,\n"
            '  "topics_preferred": array of the recurring subjects,\n'
            '  "things_to_avoid": array of style rules implied by the voice '
            '(e.g. "formal language", "passive voice").'
        )

    def judge(self, posts: list[str], measured: dict) -> dict:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_user_prompt(posts, measured)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            return json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Could not parse style JSON; using fallbacks. Raw: %s", text[:200])
            return {}

    def merge(self, measured: dict, judged: dict) -> dict:
        """Assemble Genome A. Measured numbers win; Claude fills the qualitative."""
        return {
            "sentence_length": judged.get("sentence_length", "unknown"),
            "avg_post_length": measured["avg_post_length"],          # measured
            "sarcasm_level": judged.get("sarcasm_level", "unknown"),
            "hinglish_mix": measured["hinglish_mix"],                # measured
            "uses_rhetorical_questions": measured["uses_rhetorical_questions"],  # measured
            "caps_for_emphasis": measured["caps_for_emphasis"],      # measured
            "emoji_usage": measured["emoji_usage"],                  # measured
            "hashtag_style": measured["hashtag_style"],              # measured
            "signature_phrases": judged.get("signature_phrases", measured["_ngram_candidates"][:5]),
            "topics_preferred": judged.get("topics_preferred", []),
            "things_to_avoid": judged.get("things_to_avoid", []),
            "tone": judged.get("tone", "unknown"),
        }

    def extract(self, posts: list[str]) -> dict:
        """Posts -> Genome A. Raises on empty input."""
        posts = [p.strip() for p in posts if p and p.strip()]
        if not posts:
            raise ValueError("No non-empty posts provided.")
        measured = measure(posts)
        judged = self.judge(posts, measured)
        return self.merge(measured, judged)

    def extract_and_save(self, account_id: int, posts: list[str], blend: float = 0.4,
                         db_path: Optional[str] = None) -> dict:
        genome_a = self.extract(posts)
        memory.save_style_dna(
            account_id=account_id, genome_a=genome_a, blend=blend,
            sample_count=len(posts), db_path=db_path,
        )
        logger.info("Saved Style DNA for account %s from %d posts.", account_id, len(posts))
        return genome_a


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    memory.init_db()
    acct_id = memory.upsert_account(handle="me", niche="economic policy commentary")
    example_posts = [
        "RBI holds rates again. Inflation 'under control' they say. Tell that to anyone buying groceries. let that sink in",
        "New GDP numbers out. 7.2%. Sounds great until you see the base effect. nobody's talking about this",
        "Another scheme announced. Where's the budget allocation? Show me the line item. your move",
    ]
    dna = StyleDNAExtractor().extract_and_save(acct_id, example_posts)
    print(json.dumps(dna, indent=2, ensure_ascii=False))
