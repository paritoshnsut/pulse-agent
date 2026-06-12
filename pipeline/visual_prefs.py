"""
visual_prefs.py — visual analytics v1 (VISUALS.md: the future visual moat).

Every render logs which template produced the visual (meta.visual_template,
written by pipeline/visuals.py). This module reads that log against the
human's approve/reject verdicts and answers one question for the auto-pick:

    "does THIS account keep rejecting drafts that came with THIS visual?"

Posture: deterministic, free (pure SQLite), and conservative — a template is
only shunned after enough evidence (min_shown) of a clearly-bad approval
rate, and an explicit template request from the user is ALWAYS honored; the
bias applies to the automatic paths only. This is the same shape as the
writing feedback loop: collect first, bias gently, let the data compound.
"""

from __future__ import annotations

import logging
from typing import Optional

from pipeline import memory

logger = logging.getLogger("visual_prefs")

_APPROVED = ("approved", "posted")
_REJECTED = ("rejected",)

MIN_SHOWN = 6           # evidence floor before any bias kicks in
MAX_RATE = 0.34         # approval rate below this -> shunned


def template_stats(account_id: int,
                   db_path: Optional[str] = None) -> dict:
    """{template: {"shown": n, "approved": n, "rate": float}} over every
    human-actioned draft that carried a visual."""
    stats: dict = {}
    try:
        for p in memory.get_reviewed_posts(account_id, db_path=db_path):
            tmpl = (p.get("meta_json") or {}).get("visual_template")
            if not tmpl:
                continue
            status = p.get("status")
            if status not in _APPROVED + _REJECTED:
                continue
            s = stats.setdefault(tmpl, {"shown": 0, "approved": 0})
            s["shown"] += 1
            if status in _APPROVED:
                s["approved"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("template_stats failed: %s", exc)
        return {}
    for s in stats.values():
        s["rate"] = round(s["approved"] / s["shown"], 3) if s["shown"] else 0.0
    return stats


def shunned_templates(account_id: int, db_path: Optional[str] = None,
                      min_shown: int = MIN_SHOWN,
                      max_rate: float = MAX_RATE) -> set:
    """Templates this account has seen enough of and keeps rejecting.
    Auto-pick avoids these; explicit requests still work."""
    return {tmpl for tmpl, s in template_stats(account_id, db_path).items()
            if s["shown"] >= min_shown and s["rate"] < max_rate}


# ------------------------------------------------------------ Genome v1
# Beyond shunning losers: rank winners. Evidence floors are lower here
# because ordering alternates is low-stakes (the human still picks), while
# overriding the default card is gated harder.
RANK_MIN_SHOWN = 4
PREFER_MIN_RATE = 0.6
PREFER_MARGIN = 0.15

# templates safe to substitute for the generic insight card: they need only
# the post text, nothing structured.
_GENERIC_SWAPS = ("hero_card", "quote_card")


def preferred_templates(account_id: int,
                        db_path: Optional[str] = None,
                        min_shown: int = RANK_MIN_SHOWN) -> list:
    """Every template with enough evidence, best approval rate first.
    Used to ORDER alternates — never to exclude anything."""
    stats = template_stats(account_id, db_path)
    ranked = [(tmpl, s) for tmpl, s in stats.items() if s["shown"] >= min_shown]
    ranked.sort(key=lambda kv: (-kv[1]["rate"], -kv[1]["shown"]))
    return [tmpl for tmpl, _ in ranked]


def better_generic_card(account_id: int,
                        db_path: Optional[str] = None) -> Optional[str]:
    """When auto-pick lands on the generic insight_card, is there a
    text-only template this account DEMONSTRABLY prefers? Requires real
    evidence on the challenger AND a clear margin over the incumbent."""
    stats = template_stats(account_id, db_path)
    base = stats.get("insight_card", {}).get("rate", 0.5) \
        if stats.get("insight_card", {}).get("shown", 0) >= RANK_MIN_SHOWN else 0.5
    best, best_rate = None, 0.0
    for tmpl in _GENERIC_SWAPS:
        s = stats.get(tmpl)
        if not s or s["shown"] < RANK_MIN_SHOWN:
            continue
        if s["rate"] >= PREFER_MIN_RATE and s["rate"] >= base + PREFER_MARGIN \
                and s["rate"] > best_rate:
            best, best_rate = tmpl, s["rate"]
    return best
