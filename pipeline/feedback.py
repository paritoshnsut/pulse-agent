"""
feedback.py — richer-than-binary feedback: steer a draft and have it redone.

Approve/reject is a thumbs up/down; a steer is a DIRECTION. "make it more
savage", "too preachy", "lead with the number" — these regenerate the draft
immediately AND accumulate so a recurring steer becomes a standing preference
(the learning loop folds recent notes into the voice on its next pass).

regenerate_with_steer rewrites the EXISTING draft per the instruction rather
than re-running the whole pipeline — the steer is about tone/style, not facts,
so editing the draft in place is both correct and works for every format
(callbacks, evergreen, threads included). The regenerated draft re-enters the
review lane (status reset to draft) with prior warnings cleared and
needs_review set, so you re-check the new version.
"""

from __future__ import annotations

import logging
from typing import Optional

from pipeline import memory
from pipeline.generator import ContentGenerator
from style.crowd import effective_genome

logger = logging.getLogger("feedback")

THREAD_SEP = "\n\n———\n\n"


def record_reject(post_id: int, reason: str, db_path: Optional[str] = None) -> None:
    """A rejection with a reason is far richer training signal than a bare no."""
    post = memory.get_post(post_id, db_path=db_path)
    if post and reason.strip():
        memory.record_feedback(post["account_id"], post_id, "reject_note",
                               reason, db_path=db_path)


def regenerate_with_steer(post_id: int, instruction: str,
                          db_path: Optional[str] = None) -> dict:
    """Rewrite a draft per a human steer. Returns {"ok", "content"} or
    {"ok": False, "error"}. Records the steer for the learning loop."""
    post = memory.get_post(post_id, db_path=db_path)
    if not post:
        return {"ok": False, "error": f"no draft #{post_id}"}
    if not instruction.strip():
        return {"ok": False, "error": "empty instruction"}
    dna = memory.get_style_dna(post["account_id"], db_path=db_path)
    if not dna:
        return {"ok": False, "error": "no voice trained for this account"}

    genome = effective_genome(dna["genome_a"], dna["genome_b"], dna["blend"])
    is_thread = post["format"] == "thread" or THREAD_SEP in post["content"]
    try:
        new = ContentGenerator().rewrite(post["content"], instruction, genome,
                                         is_thread=is_thread)
    except Exception as exc:  # noqa: BLE001
        logger.error("Rewrite failed for #%s: %s", post_id, exc)
        return {"ok": False, "error": f"rewrite failed: {exc}"}
    if new["empty"]:
        return {"ok": False, "error": "rewrite produced nothing — try rephrasing"}

    # carry forward neutral meta, but DROP stale warnings (content changed) and
    # require a fresh human look at the new version
    meta = dict(post.get("meta_json") or {})
    for stale in ("ungrounded_claims", "stance_conflicts", "risk_level",
                  "risk_vectors", "alt_hooks"):
        meta.pop(stale, None)
    meta["tweets"] = new.get("tweets")
    meta["hashtags"] = new.get("hashtags")
    meta["emotion"] = new.get("emotion")
    meta["redone_with"] = instruction.strip()
    memory.update_post_content(post_id, new["content"], meta,
                               needs_review=True, db_path=db_path)
    memory.record_feedback(post["account_id"], post_id, "redo",
                           instruction, db_path=db_path)
    logger.info("Redid #%s with steer: %s", post_id, instruction[:60])
    return {"ok": True, "content": new["content"]}
