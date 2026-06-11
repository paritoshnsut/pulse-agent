"""
voice.py — the one place that assembles an account's full generation genome.

Before: every producer (process cycle, repurpose, callbacks, counter,
evergreen, redo) repeated `effective_genome(dna...)`. That worked for voice +
crowd, but the brand kit needs to apply EVERYWHERE too (a banned word must
never appear on any path). So this is the single loader: voice (Genome A) +
crowd (Genome B, blended) + brand kit, in one call.

Returns None when no voice has been trained — callers already handle that.
"""

from __future__ import annotations

from typing import Optional

from pipeline import memory
from style import brand as brand_mod
from style.crowd import effective_genome


def effective_for(account_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    """The complete genome the generator should use for this account, or None
    if no Style DNA exists yet."""
    dna = memory.get_style_dna(account_id, db_path=db_path)
    if not dna:
        return None
    genome = effective_genome(dna["genome_a"], dna["genome_b"], dna["blend"])
    kit = memory.get_brand_kit(account_id, db_path=db_path)
    return brand_mod.apply_to_genome(genome, kit)
