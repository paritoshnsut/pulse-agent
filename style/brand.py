"""
brand.py — the text Brand Kit: the rules a brand's content must obey.

Genome A is HOW the account sounds (voice). The brand kit is WHAT it may and
may not say — the compliance/identity layer that turns a personal-voice engine
into a brand-safe one. Banned words, preferred swaps ("cheap"→"affordable"),
required disclaimers ("not financial advice"), a default CTA, freeform brand
notes.

measure-then-judge, same as everywhere:
  * The model is TOLD the rules (render_rules → into the prompt) so it writes
    on-brand from the start.
  * The rules are also ENFORCED deterministically afterward — word swaps are
    applied for sure, and any banned word that survives is flagged for review.
    A model told "never say cheap" will still occasionally slip; we don't hope.

The kit is merged into the genome under a `brand` key (style/voice.py does this
centrally), so every generation path — process cycle, repurpose, callbacks,
counter, evergreen — gets it for free.
"""

from __future__ import annotations

import re
from typing import Optional


def apply_to_genome(genome: dict, kit: Optional[dict]) -> dict:
    """Fold a brand kit into the genome under `brand`. No kit -> unchanged,
    so every existing (brand-less) account behaves exactly as before."""
    if not kit:
        return genome
    merged = dict(genome)
    merged["brand"] = {
        "banned_words": kit.get("banned_words") or [],
        "word_swaps": kit.get("word_swaps") or {},
        "disclaimers": kit.get("disclaimers") or [],
        "cta_text": kit.get("cta_text") or "",
        "cta_url": kit.get("cta_url") or "",
        "notes": kit.get("notes") or "",
    }
    return merged


def render_rules(brand: dict) -> str:
    """Brand rules as a hard prompt block."""
    lines = ["BRAND RULES (obey exactly — these override style preferences):"]
    if brand.get("banned_words"):
        lines.append(f"- NEVER use these words/phrases: {brand['banned_words']}")
    if brand.get("word_swaps"):
        swaps = ", ".join(f'"{b}"→"{g}"' for b, g in brand["word_swaps"].items())
        lines.append(f"- Always prefer: {swaps}")
    if brand.get("disclaimers"):
        lines.append(f"- When relevant, include a disclaimer like: {brand['disclaimers']}")
    if brand.get("cta_text"):
        cta = brand["cta_text"] + (f" ({brand['cta_url']})" if brand.get("cta_url") else "")
        lines.append(f"- Default call-to-action when one fits: {cta}")
    if brand.get("notes"):
        lines.append(f"- Brand notes: {brand['notes']}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _swap_word(text: str, bad: str, good: str) -> str:
    """Case-aware whole-word replacement (Cheap->Affordable, cheap->affordable)."""
    def repl(m: re.Match) -> str:
        w = m.group(0)
        if w.isupper():
            return good.upper()
        if w[0].isupper():
            return good[:1].upper() + good[1:]
        return good
    return re.sub(rf"\b{re.escape(bad)}\b", repl, text, flags=re.IGNORECASE)


def enforce(text: str, brand: Optional[dict]) -> tuple[str, list[str]]:
    """Apply word swaps deterministically; return (text, surviving_banned).
    Surviving banned words are the ones with no swap defined — they get
    flagged for human review rather than silently mangled."""
    if not brand or not text:
        return text, []
    for bad, good in (brand.get("word_swaps") or {}).items():
        if good:
            text = _swap_word(text, bad, good)
    survivors = []
    for word in (brand.get("banned_words") or []):
        if re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE):
            survivors.append(word)
    return text, survivors
