"""
charts.py — chart-spec extraction for the chart_card visual (VISUALS.md).

"GDP has trended up since 2019" deserves the chart, not just the sentence.
This module turns a post + its source article into a validated spec the
render service can draw deterministically:

    {"kind": "bar"|"line", "title", "labels": [...], "values": [...],
     "unit": "", "source": ""}

Cost posture (measure-then-judge, as everywhere):
  * A free numeric gate runs first — fewer than MIN_NUMBERS distinct numbers
    in the material means there is no series to chart; no Claude call.
  * One bounded Claude call extracts the series; the result (or the explicit
    miss) is CACHED in post meta, so re-renders and template swaps never pay
    twice. Extract, never invent: only numbers present in the material.
  * Any failure anywhere -> None; the caller keeps the stat/insight card.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from config import settings
from pipeline import memory
from pipeline.llm import tracked_create

logger = logging.getLogger("charts")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_NUM = re.compile(r"\d[\d,]*\.?\d*")

MIN_NUMBERS = 3          # fewer distinct numbers than this -> nothing to chart
MAX_POINTS = 10
MIN_POINTS = 3

EXTRACT_PROMPT = """Does this material contain a NUMERIC SERIES worth charting
(values over time, or a comparison across categories)?

If yes, return JSON:
{{"kind": "bar" or "line" (line for trends over time, bar for comparisons),
  "title": "chart headline, max 60 chars",
  "labels": ["3-10 short axis labels"],
  "values": [the numbers, same length as labels],
  "unit": "%" or "₹" or "$" or "" ,
  "source": "where the numbers come from, max 30 chars, or empty"}}

If no real series exists, return exactly: null

Rules: every value must appear in the material — extract, never invent or
extrapolate. Labels under 8 chars each. Return ONLY the JSON or null.

POST:
{post}

SOURCE MATERIAL:
{article}"""


def _numeric_gate(text: str) -> bool:
    """Free pre-check: a chartable series needs several distinct numbers."""
    return len({m.group(0) for m in _NUM.finditer(text or "")}) >= MIN_NUMBERS


def validate_spec(spec: Any) -> Optional[dict]:
    """Normalize + sanity-check a candidate spec. None when unusable."""
    if not isinstance(spec, dict):
        return None
    labels = spec.get("labels") or []
    values = spec.get("values") or []
    if not (MIN_POINTS <= len(values) <= MAX_POINTS) or len(labels) != len(values):
        return None
    try:
        values = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    kind = spec.get("kind") if spec.get("kind") in ("bar", "line") else "bar"
    if any(v < 0 for v in values):
        kind = "line"            # bars can't show negatives honestly
    return {
        "kind": kind,
        "title": str(spec.get("title") or "")[:80],
        "labels": [str(l)[:12] for l in labels],
        "values": values,
        "unit": str(spec.get("unit") or "")[:4],
        "source": str(spec.get("source") or "")[:40],
    }


class ChartExtractor:
    """One Claude call -> a validated chart spec, cached on the post."""

    def __init__(self, client: Any = None, model: Optional[str] = None) -> None:
        self._client = client
        self.model = model or settings.model

    @property
    def client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def spec_for(self, post: dict, db_path: Optional[str] = None) -> Optional[dict]:
        meta = post.get("meta_json") or {}
        if "chart" in meta:                       # cached hit OR cached miss
            return validate_spec(meta["chart"])

        article_text = ""
        try:
            sig = memory.get_signal(post["signal_id"], db_path=db_path) \
                if post.get("signal_id") else None
            art = memory.get_article(sig["article_id"], db_path=db_path) \
                if sig and sig.get("article_id") else None
            if art:
                article_text = " ".join(filter(None, [
                    art.get("title"), art.get("description"),
                    (art.get("content") or "")[:2000]]))
        except Exception:  # noqa: BLE001  (no source — post text may suffice)
            pass

        material = f"{post.get('content') or ''} {article_text}"
        if not _numeric_gate(material):
            self._cache(post, None, db_path)
            return None

        try:
            msg = tracked_create(
                self.client, "charts", model=self.model, max_tokens=400,
                messages=[{"role": "user", "content": EXTRACT_PROMPT.format(
                    post=(post.get("content") or "")[:1500],
                    article=article_text[:3000] or "(none)")}])
            text = _FENCE.sub("", "".join(
                getattr(b, "text", "") for b in msg.content).strip())
            raw = None if text.lower() == "null" else json.loads(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chart extraction failed for post %s: %s",
                           post.get("id"), exc)
            return None           # transient failure: don't cache the miss

        spec = validate_spec(raw)
        self._cache(post, spec, db_path)
        return spec

    @staticmethod
    def _cache(post: dict, spec: Optional[dict],
               db_path: Optional[str]) -> None:
        try:
            if post.get("id"):
                memory.update_post_meta(post["id"], {"chart": spec},
                                        db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chart spec cache write failed: %s", exc)
