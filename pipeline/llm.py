"""
llm.py — every Claude call in the system goes through tracked_create().

Two jobs, both invisible until you need them badly:

  LEDGER  — each real API response carries token usage; we log module, model,
            tokens and an estimated cost to claude_logs. That's the audit
            trail Grok asked for and the answer to "what did today cost?"
            (memory.cost_today, surfaced in /api/status and the briefing).

  BUDGET  — before each call, today's spend is checked against
            DAILY_BUDGET_USD. Over budget: the call is refused
            (BudgetExceeded), a Telegram alert fires ONCE per day, and every
            scheduled job degrades gracefully through its existing try/except.
            The watchers keep ingesting (free); only Claude spend stops.
            Set DAILY_BUDGET_USD=0 to disable the cap (logging stays on).

Test-friendliness by design: stub clients return messages without a `usage`
attribute, so tests run through this wrapper without writing ledger rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import settings
from pipeline import memory

logger = logging.getLogger("llm")


class BudgetExceeded(RuntimeError):
    """Raised instead of making a Claude call once the daily cap is hit."""


def _estimate_cost(usage: Any) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return round((inp * settings.cost_in_per_mtok
                  + out * settings.cost_out_per_mtok) / 1_000_000, 6)


def _alert_once(spent: float) -> None:
    """One Telegram budget alert per UTC day, flagged in kv_store."""
    key = f"budget_alert:{datetime.now(timezone.utc).date().isoformat()}"
    try:
        if memory.kv_get(key):
            return
        memory.kv_set(key, "1")
        from pipeline.poster import TelegramNotifier
        TelegramNotifier().send(
            f"🛑 Daily Claude budget hit: ${spent:.2f} of "
            f"${settings.daily_budget_usd:.2f}. Drafting/scoring paused until "
            f"UTC midnight. Raise DAILY_BUDGET_USD if intended.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Budget alert failed: %s", exc)


def ensure_budget() -> None:
    if settings.daily_budget_usd <= 0:
        return
    try:
        spent = memory.cost_today()
    except Exception:  # noqa: BLE001  (fresh DB, missing table — never block)
        return
    if spent >= settings.daily_budget_usd:
        _alert_once(spent)
        raise BudgetExceeded(
            f"daily Claude budget reached (${spent:.2f} >= "
            f"${settings.daily_budget_usd:.2f}); paused until UTC midnight")


def tracked_create(client: Any, module: str, **kwargs: Any) -> Any:
    """Drop-in replacement for client.messages.create with ledger + budget."""
    ensure_budget()
    msg = client.messages.create(**kwargs)
    usage = getattr(msg, "usage", None)
    if usage is not None and getattr(usage, "input_tokens", None) is not None:
        try:
            memory.log_claude_call(module, kwargs.get("model"),
                                   usage.input_tokens, usage.output_tokens or 0,
                                   _estimate_cost(usage))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cost ledger write failed (call succeeded): %s", exc)
    return msg
