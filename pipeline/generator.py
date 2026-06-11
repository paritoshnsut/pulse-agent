"""
generator.py — Session 5. The content generator. The keystone.

Takes a signal (a story the decision agent flagged) + the account's Genome A
(voice profile) + a requested format, and produces a drafted post in the user's
voice.

DESIGN, consistent with the rest of the pipeline (measure-then-judge):
  * Claude WRITES the post, constrained hard by Genome A injected as rules.
  * Python ENFORCES the measurable parts of the voice afterward — emoji policy,
    hashtag case/count, platform length cap. A model told "no emoji" will still
    occasionally slip one in; we strip it deterministically rather than hope.

Formats implemented (the high-value subset of CLAUDE.md's 12, pluggable via
FORMATS — adding the rest is a new entry, not new engine code):
  hot_take      — single punchy reaction, leads with the angle
  contradiction — "then vs now"; only produced if a credible contradiction exists
  data_story    — leads with the surprising number
  thread        — 3-6 connected tweets

Pairs with style/scorer.py: generate_checked() writes, enforces style, scores
against Genome A, and regenerates with feedback if it misses the >70 gate
(CLAUDE.md rule #9).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory

logger = logging.getLogger("generator")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF]"
)
HASHTAG = re.compile(r"#\w+")

X_CHAR_LIMIT = 280
AI_LABEL_DEFAULT = "🤖 AI-assisted"  # CLAUDE.md rule #10; applied at posting time

# Format registry: name -> (instruction, is_thread). Add formats here.
FORMATS: dict[str, tuple[str, bool]] = {
    "hot_take": (
        "Write a single punchy reaction post. Lead with the sharpest angle. "
        "Immediate, opinionated, no preamble. One post only.",
        False,
    ),
    "contradiction": (
        "Write a 'then vs now' contradiction post: contrast a past position or "
        "promise with the current reality. ONLY write one if a credible, factual "
        "contradiction is actually supported by the story — do NOT invent a past "
        "quote. If none exists, return an empty text and say so in 'note'.",
        False,
    ),
    "data_story": (
        "Write a post that leads with the single most surprising number or "
        "statistic in the story, then lands the point. If the story has no "
        "concrete figure, return empty text and say so in 'note'.",
        False,
    ),
    "thread": (
        "Write a thread of 3 to 6 tweets connecting this event to the larger "
        "ongoing story. First tweet is the hook. Each tweet stands alone and is "
        "under 280 characters. Return the tweets as a JSON array in 'tweets'.",
        True,
    ),
    "callback": (
        "Write a callback post following up on YOUR OWN past prediction (the "
        "prediction, its date, and the outcome are in the angle/memory above). "
        "If the prediction was CONFIRMED: take the win — confident and specific "
        "about what you said and when, not insufferable. If it was REFUTED: own "
        "it cleanly and say what you got wrong — honesty is the brand. Either "
        "way, quote your past claim faithfully; never soften or improve it.",
        False,
    ),
    "explainer": (
        "Write an explainer: what is the thing at the center of this story, and "
        "why does it actually matter to the reader? Assume a smart reader who "
        "missed the context. No jargon without a one-clause translation. End on "
        "the 'so what'.",
        False,
    ),
    "prediction": (
        "Stake a clear, falsifiable position on what happens NEXT because of "
        "this story — a specific claim with a rough timeframe (e.g. 'by the "
        "next quarter'). Confidence without hedging; being checkably wrong "
        "later beats being vague now. Do not predict something the story "
        "already confirms.",
        False,
    ),
    "quote_context": (
        "Extract the single most quotable line or moment from the story — "
        "verbatim, in quotation marks, ONLY if it actually appears in the "
        "headline or summary — then add your pointed commentary on it. If "
        "nothing in the provided text is directly quotable, return empty text "
        "and say so in 'note'. NEVER fabricate or paraphrase a quote.",
        False,
    ),
    "counter_narrative": (
        "Everyone covering this story is saying the same thing — the consensus "
        "is given in the angle/memory above. Write the take NOBODY is taking: "
        "lead with the missing angle, position it explicitly against the herd "
        "('everyone's talking about X; the real story is Y'). The contrarian "
        "angle must be grounded in the provided facts, not invented.",
        False,
    ),
    "video_reaction": (
        "You just watched a new video — transcript excerpts are in your memory "
        "block above. React to its SPECIFIC claims: pick the 1-2 strongest "
        "moments, quote or closely paraphrase them, and take them on in your "
        "voice. NEVER react to a claim that isn't in the transcript; if the "
        "transcript is missing or too thin to quote, return empty text and say "
        "so in 'note'.",
        False,
    ),
    "achievement": (
        "This story is a genuine win for a cause, policy, or position this "
        "account openly backs (check the stances in your memory). Amplify it: "
        "lead with the concrete result and the number that proves it, then tie "
        "it to the longer arc you've been arguing. If it is NOT actually a win "
        "aligned with this voice, return empty text and say so in 'note' — "
        "forced cheerleading reads as spin.",
        False,
    ),
    "evergreen": (
        "No news peg. Write a standalone opinion post on the given topic — "
        "your strongest recurring argument, distilled (your past positions are "
        "in the memory block). Timeless thought leadership: no 'today', no "
        "'breaking', no reference to any specific fresh event.",
        False,
    ),
}

# Formats the decision agent may pick per signal. Excluded: callback (only the
# predictions watcher), counter_narrative (only the detector, which supplies
# the consensus), video_reaction (wired automatically for YouTube articles
# with transcripts), evergreen (not news-tied; produced on demand).
CHOOSABLE_FORMATS = tuple(k for k in FORMATS
                          if k not in ("callback", "counter_narrative",
                                       "video_reaction", "evergreen"))


def _strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


def _style_rules(genome: dict) -> str:
    """Render the genome as an explicit, hard rule block for the prompt.

    Voice identity comes from Genome A. If the learning layer has run, two
    optional blocks appear: learned_preferences (approve/reject lessons —
    learned avoid-rules are already merged into things_to_avoid) and
    crowd_patterns (Genome B via crowd.effective_genome — structure to borrow,
    never voice, pushed proportionally to the blend weight).
    """
    sig = genome.get("signature_phrases") or []
    avoid = genome.get("things_to_avoid") or []
    rules = (
        f"- Sentence style: {genome.get('sentence_length', 'natural')}\n"
        f"- Target length: about {genome.get('avg_post_length', '200 chars')} per post\n"
        f"- Sarcasm level: {genome.get('sarcasm_level', 'moderate')}\n"
        f"- Tone: {genome.get('tone', 'direct')}\n"
        f"- Emoji policy: {genome.get('emoji_usage', 'none')}\n"
        f"- Hashtag style: {genome.get('hashtag_style', 'none')}\n"
        f"- Rhetorical questions: {'use them' if genome.get('uses_rhetorical_questions') else 'avoid'}\n"
        f"- ALL-CAPS for emphasis: {'occasionally ok' if genome.get('caps_for_emphasis') else 'do not use'}\n"
        f"- Hinglish mix (0=pure English, 1=heavy Hindi): {genome.get('hinglish_mix', 0)}\n"
        f"- Signature phrases you may use sparingly (do not force): {sig}\n"
        f"- NEVER do these: {avoid}\n"
    )
    # v2 voice depth (present once the corpus has been retrained)
    mech = genome.get("mechanics") or {}
    if mech:
        rules += (
            f"- Cadence (measured — reproduce it): ~{mech.get('avg_words_per_sentence')} "
            f"words/sentence, {mech.get('short_sentence_rate')} of sentences are "
            f"short fragments; em-dash rate {mech.get('em_dash_rate')}, "
            f"posts with numbers/data {mech.get('data_rate')}"
            + (f", often opens lowercase" if (mech.get('starts_lowercase') or 0) > 0.3 else "")
            + (f", often opens with the number" if (mech.get('starts_with_number') or 0) > 0.2 else "")
            + "\n"
        )
    if genome.get("emotional_palette"):
        rules += f"- Emotional palette (in this order): {genome['emotional_palette']}\n"
    if genome.get("sentiment_baseline"):
        rules += f"- Default sentiment lean: {genome['sentiment_baseline']}\n"
    if genome.get("rhetorical_devices"):
        rules += f"- Rhetorical devices this voice actually uses: {genome['rhetorical_devices']}\n"
    if genome.get("argument_structure"):
        rules += f"- How posts are built: {genome['argument_structure']}\n"
    if genome.get("register"):
        rules += f"- Register: {genome['register']}\n"
    influences = genome.get("influences") or {}
    if influences.get("admired_patterns"):
        rules += (f"- Patterns from writing this author admires (borrow the move, "
                  f"keep the voice above): {influences['admired_patterns']}\n")
    lp = genome.get("learned_preferences") or {}
    if lp.get("emphasize"):
        rules += f"- This writer approves drafts that do this — do MORE of it: {lp['emphasize']}\n"
    if lp.get("preferred_emotions"):
        rules += (f"- Emotional registers that land for this writer (lean toward "
                  f"them when the story allows): {lp['preferred_emotions']}\n")
    cw = genome.get("crowd_patterns")
    if cw:
        strength = "lightly" if cw.get("weight", 0.4) < 0.35 else "actively"
        rules += (
            f"- Crowd-tested patterns from the niche's top posts: {strength} borrow "
            f"their STRUCTURE only — the voice above always wins. "
            f"Hooks: {cw.get('hooks')}. Shapes: {cw.get('structures')}. "
            f"Emotional registers being rewarded: {cw.get('emotional_registers')}.\n"
        )
    return rules


SYSTEM_PROMPT = (
    "You write social media posts in ONE specific person's voice. You are given "
    "that voice as a strict style profile and you match it exactly — sentence "
    "length, sarcasm, emoji policy, hashtag style, signature phrases, and the "
    "list of things to never do. You write the post itself, not commentary about "
    "it. You never fabricate quotes, statistics, or events not supported by the "
    "source. Output ONLY a JSON object, no prose, no markdown fences."
)


class ContentGenerator:
    """Generates drafts. Anthropic client injectable for tests."""

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

    # ------------------------------------------------------------ prompting
    def _build_prompt(self, signal: dict, genome: dict, fmt: str, feedback: str = "",
                      context: Optional[str] = None) -> str:
        instruction, _ = FORMATS[fmt]
        fb = f"\nPREVIOUS ATTEMPT MISSED THE VOICE. Fix this: {feedback}\n" if feedback else ""
        # The 6-layer memory package (pipeline/context.py). Real records only —
        # the model is told to use them, never to extend them.
        ctx = ""
        if context:
            ctx = (
                f"YOUR MEMORY (real records from this account's own history):\n"
                f"{context}\n"
                f"Memory rules: stay consistent with your past stances unless the new "
                f"facts genuinely change the picture (then say so). You may reference "
                f"the past events — continuity is your edge. If a past stance or event "
                f"factually contradicts what the story's subject now claims, that "
                f"contrast may be the angle. NEVER invent memory beyond what's listed.\n\n"
            )
        emotion_key = ('  "emotion": the post\'s dominant emotion, one of '
                       '"outrage" | "curiosity" | "pride" | "humour" | '
                       '"surprise" | "validation" | "neutral",\n')
        keys = ('  "text": the post (empty string if not applicable),\n'
                '  "hashtags": array of hashtags without the # sign,\n'
                + emotion_key +
                '  "note": short reason if you returned empty text, else ""')
        if FORMATS[fmt][1]:  # thread
            keys = ('  "tweets": array of 3-6 tweet strings,\n'
                    '  "hashtags": array of hashtags without the # sign,\n'
                    + emotion_key +
                    '  "note": short reason if you could not write it, else ""')
        return (
            f"STORY\n"
            f"Headline: {signal.get('title')}\n"
            f"Source: {signal.get('source_name')}\n"
            f"Summary: {signal.get('description') or '(none)'}\n"
            f"Suggested angle: {signal.get('angle') or '(none given)'}\n\n"
            f"{ctx}"
            f"VOICE PROFILE (match exactly):\n{_style_rules(genome)}\n"
            f"FORMAT: {instruction}\n{fb}\n"
            f"Return JSON with these keys:\n{keys}"
        )

    def _call(self, prompt: str, max_tokens: int) -> dict:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            return json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            logger.error("Generator returned non-JSON; raw: %s", text[:200])
            return {}

    # -------------------------------------------------- deterministic style
    def enforce_style(self, text: str, genome: dict) -> str:
        """Apply measurable voice rules the model may have missed."""
        if not text:
            return text
        # emoji policy
        if (genome.get("emoji_usage") or "none") == "none":
            text = EMOJI.sub("", text)
        # hashtag case
        style = (genome.get("hashtag_style") or "").lower()
        if "lowercase" in style:
            text = HASHTAG.sub(lambda m: m.group(0).lower(), text)
        # collapse whitespace introduced by stripping
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    def _attach_hashtags(self, text: str, hashtags: list[str], genome: dict) -> str:
        """Append hashtags per the voice's style (count + case), if any."""
        if not hashtags:
            return text
        style = (genome.get("hashtag_style") or "").lower()
        if "rarely" in style or "none" in style:
            return text  # this voice doesn't tag
        # cap count: pull a number out of the style descriptor, default 3
        m = re.search(r"(\d+)", style)
        cap = int(m.group(1)) if m else 3
        tags = hashtags[:cap]
        if "lowercase" in style:
            tags = [t.lower() for t in tags]
        rendered = " ".join(f"#{t.lstrip('#')}" for t in tags)
        # only append if not already present in the body
        if rendered and rendered.split()[0] not in text:
            return f"{text}\n\n{rendered}".strip()
        return text

    def _truncate(self, text: str, limit: int = X_CHAR_LIMIT) -> tuple[str, bool]:
        if len(text) <= limit:
            return text, False
        cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
        return cut, True

    # --------------------------------------------------------------- public
    def generate(self, signal: dict, genome: dict, fmt: str = "hot_take", feedback: str = "",
                 context: Optional[str] = None) -> dict:
        """Produce one draft. Returns a structured dict (not yet persisted).
        context: rendered memory block from pipeline/context.py (optional)."""
        if fmt not in FORMATS:
            raise ValueError(f"Unknown format '{fmt}'. Known: {list(FORMATS)}")
        is_thread = FORMATS[fmt][1]
        raw = self._call(self._build_prompt(signal, genome, fmt, feedback, context=context),
                         max_tokens=900 if is_thread else 400)
        hashtags = raw.get("hashtags") or []
        note = (raw.get("note") or "").strip()
        emotion = (raw.get("emotion") or "").strip().lower()

        if is_thread:
            tweets = [self.enforce_style(t, genome) for t in (raw.get("tweets") or []) if t.strip()]
            tweets = [self._truncate(t)[0] for t in tweets]
            content = "\n\n———\n\n".join(tweets)
            return {
                "format": fmt, "tweets": tweets, "content": content,
                "hashtags": hashtags, "note": note, "emotion": emotion,
                "empty": len(tweets) == 0, "char_count": len(content),
            }

        text = self.enforce_style(raw.get("text") or "", genome)
        if text:
            text = self._attach_hashtags(text, hashtags, genome)
            text, truncated = self._truncate(text)
        else:
            truncated = False
        return {
            "format": fmt, "text": text, "content": text,
            "hashtags": hashtags, "note": note, "emotion": emotion,
            "empty": not text, "truncated": truncated, "char_count": len(text),
        }

    def alt_hooks(self, draft_text: str, signal: dict, genome: dict, n: int = 2) -> list[str]:
        """Alternative opening lines for a draft (Session 33's A/B engine,
        adapted to copilot: the HUMAN picks the hook, not a posting algorithm).
        One cheap call; returns [] on any failure — hooks are a bonus."""
        prompt = (
            f"STORY: {signal.get('title')}\n"
            f"CURRENT DRAFT:\n\"\"\"\n{draft_text}\n\"\"\"\n\n"
            f"VOICE PROFILE (match exactly):\n{_style_rules(genome)}\n"
            f"Write {n} ALTERNATIVE opening lines (hooks) for this exact draft — "
            "same facts, same voice, different attack: e.g. one leading with the "
            "number, one with the question, one with the contrast. Each under "
            "120 characters. Return JSON: {\"hooks\": [\"...\", \"...\"]}"
        )
        try:
            raw = self._call(prompt, max_tokens=300)
            hooks = [h.strip() for h in (raw.get("hooks") or []) if h and h.strip()]
            return [self.enforce_style(h, genome) for h in hooks[:n]]
        except Exception as exc:  # noqa: BLE001
            logger.error("alt_hooks failed: %s", exc)
            return []

    def generate_checked(
        self,
        signal: dict,
        genome: dict,
        fmt: str = "hot_take",
        scorer: Any = None,
        gate: float = 70.0,
        max_retries: int = 2,
        account_id: Optional[int] = None,
        persist: bool = False,
        db_path: Optional[str] = None,
        context: Optional[str] = None,
    ) -> dict:
        """
        Generate -> enforce style -> score against Genome A -> regenerate with
        feedback if below the gate (rule #9). Returns the best draft with its
        score and a needs_review flag. Optionally persists to the posts table.

        scorer: a PersonaConsistencyScorer (or None to skip scoring entirely).
        context: rendered memory block from pipeline/context.py (optional).
        """
        best: dict = {}
        feedback = ""
        for attempt in range(max_retries + 1):
            draft = self.generate(signal, genome, fmt, feedback=feedback, context=context)
            if draft["empty"]:
                draft["persona_score"] = None
                draft["needs_review"] = True
                best = draft
                break
            if scorer is None:
                draft["persona_score"] = None
                draft["needs_review"] = False
                best = draft
                break
            result = scorer.score(draft["content"], genome)
            draft["persona_score"] = result["composite"]
            draft["axes"] = result["axes"]
            draft["mechanical"] = result["mechanical"]
            if not best or result["composite"] > best.get("persona_score", -1):
                best = draft
            logger.info("[%s attempt %d] score=%.1f", fmt, attempt + 1, result["composite"])
            if result["composite"] >= gate:
                draft["needs_review"] = False
                best = draft
                break
            feedback = result.get("weakest_axis_feedback", "match the voice more closely")
        else:
            best["needs_review"] = best.get("persona_score", 0) < gate

        best.setdefault("needs_review", best.get("persona_score") is None
                        or best.get("persona_score", 0) < gate)

        if persist and account_id is not None:
            meta = {k: best.get(k) for k in ("tweets", "hashtags", "axes", "mechanical",
                                             "note", "char_count", "emotion")}
            best["post_id"] = memory.save_post(
                account_id=account_id, fmt=best["format"], content=best["content"],
                meta=meta, signal_id=signal.get("id"), article_id=signal.get("article_id"),
                persona_score=best.get("persona_score"), needs_review=best["needs_review"],
                db_path=db_path,
            )
        return best


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    genome = {
        "sentence_length": "short, punchy, fragments ok", "avg_post_length": "180 chars",
        "sarcasm_level": "high", "tone": "combative", "emoji_usage": "none",
        "hashtag_style": "2-3, lowercase, at end", "uses_rhetorical_questions": True,
        "caps_for_emphasis": True, "hinglish_mix": 0.2,
        "signature_phrases": ["let that sink in", "nobody's talking about this"],
        "things_to_avoid": ["formal language", "passive voice"],
    }
    signal = {
        "title": "India GDP grows 7.2% in Q4, beating estimates",
        "source_name": "Mint", "description": "Growth driven by services; manufacturing flat.",
        "angle": "the 7.2% headline hides a soft manufacturing base — services carried it",
    }
    print(json.dumps(ContentGenerator().generate(signal, genome, "hot_take"), indent=2, ensure_ascii=False))
