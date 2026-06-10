"""
timing.py — the optimal post timing engine (Session 9 / intelligence #1),
adapted for the manual posting flow: it doesn't schedule anything, it ADVISES.
The approval package and the morning briefing say "your best window is
20:00-22:00 IST" and you, the human poster, decide.

Where the numbers come from: every post you mark /posted gets a posted_at
stamp, and every /perf entry gives it an engagement value. Bucket those by
local hour of day, average, and the heat map writes itself.

HONESTY RULE, as everywhere in this codebase: below TIMING_MIN_SAMPLES (8)
posts-with-engagement, the windows shown are explicit niche defaults
(morning commute / lunch / evening prime time — when Indian news Twitter is
actually awake), clearly labeled "default — not yet learned from your data".
No fake personalization from three data points.

Pure Python + SQLite. No model calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from style.learning import _engagement_value

logger = logging.getLogger("timing")

# Niche-default windows in LOCAL hours, used until enough real data exists.
DEFAULT_WINDOWS = ((8, 10), (13, 14), (20, 22))


def _local_hour(posted_at: str) -> Optional[int]:
    """UTC ISO timestamp -> local hour of day (tz offset from config)."""
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return (dt + timedelta(minutes=settings.tz_offset_min)).hour


def hour_performance(account_id: int, db_path: Optional[str] = None) -> dict[int, float]:
    """Mean engagement value per local hour, over posts that have both a
    posted_at stamp and an engagement snapshot."""
    from pipeline import memory

    buckets: dict[int, list[float]] = {}
    for row in memory.get_post_engagement(account_id, db_path=db_path):
        hour = _local_hour(row.get("posted_at") or "")
        if hour is None:
            continue
        buckets.setdefault(hour, []).append(_engagement_value(row))
    return {h: round(sum(v) / len(v), 1) for h, v in buckets.items()}


def _merge_adjacent(hours: list[int]) -> list[tuple[int, int]]:
    """[20, 21, 8] -> [(8, 9), (20, 22)] — contiguous hours become one window
    (end exclusive, so (20, 22) reads as 20:00-22:00)."""
    if not hours:
        return []
    hours = sorted(set(hours))
    windows = []
    start = prev = hours[0]
    for h in hours[1:]:
        if h == prev + 1:
            prev = h
            continue
        windows.append((start, prev + 1))
        start = prev = h
    windows.append((start, prev + 1))
    return windows


def best_windows(account_id: int, top_hours: int = 4,
                 db_path: Optional[str] = None) -> dict:
    """The advice. Returns {"learned": bool, "windows": [(start, end), ...],
    "samples": n}. learned=False means the defaults are showing."""
    from pipeline import memory

    perf = hour_performance(account_id, db_path=db_path)
    samples = len([r for r in memory.get_post_engagement(account_id, db_path=db_path)
                   if _local_hour(r.get("posted_at") or "") is not None])
    if samples < settings.timing_min_samples:
        return {"learned": False, "windows": list(DEFAULT_WINDOWS), "samples": samples}
    ranked = sorted(perf, key=perf.get, reverse=True)[:top_hours]
    return {"learned": True, "windows": _merge_adjacent(ranked), "samples": samples}


def describe_windows(account_id: int, db_path: Optional[str] = None) -> str:
    """One human-readable line for the approval package / briefing."""
    res = best_windows(account_id, db_path=db_path)
    spans = ", ".join(f"{s:02d}:00–{e:02d}:00" for s, e in res["windows"])
    tag = (f"learned from {res['samples']} posts" if res["learned"]
           else "defaults — not yet learned from your data")
    return f"best posting windows ({settings.tz_label}): {spans} ({tag})"
