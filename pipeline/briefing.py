"""
briefing.py — the morning briefing. The COOL tier finally keeps its promise.

CLAUDE.md's urgency model says COOL signals (4.5-6.5) go to a "content ideas
bank, surfaced in morning briefing" — until now they were stored and never
surfaced. This module sends one Telegram digest per account every morning
(BRIEFING_HOUR local, default 8):

  * content ideas — yesterday's COOL signals, best first, with their angles
  * outbox nag — approved drafts you still haven't posted
  * open predictions the callback watcher is holding you to
  * the last 24h in numbers — drafted / approved / rejected / posted
  * your current historical_perf and best posting windows

Pure reads + string formatting. Zero Claude calls; the briefing costs nothing.
Run by hand anytime: python -m pipeline.briefing
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from pipeline import memory, poster, timing
from style.learning import historical_performance

logger = logging.getLogger("briefing")

IDEAS_LIMIT = 5


def _last_24h() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


def _cool_ideas(account_id: int, db_path: Optional[str] = None) -> list[dict]:
    """Yesterday's COOL signals for this account that nobody drafted — the
    ideas bank. Best score first."""
    since = _last_24h()
    drafted_signals = {p.get("signal_id")
                       for p in memory.get_posts(account_id=account_id, db_path=db_path)}
    ideas = [s for s in memory.get_signals_by_tier("COOL", db_path=db_path)
             if s.get("account_id") == account_id
             and s["created_at"] > since
             and s["id"] not in drafted_signals]
    return ideas[:IDEAS_LIMIT]  # get_signals_by_tier is already score-ordered


def _day_stats(account_id: int, db_path: Optional[str] = None) -> dict:
    since = _last_24h()
    posts = memory.get_posts(account_id=account_id, db_path=db_path)
    fresh = [p for p in posts if p["created_at"] > since]
    acted = [p for p in posts if p["updated_at"] > since]
    return {
        "drafted": len(fresh),
        "approved": sum(1 for p in acted if p["status"] in ("approved", "edited")),
        "rejected": sum(1 for p in acted if p["status"] == "rejected"),
        "posted": sum(1 for p in acted if p["status"] == "posted"),
    }


def build(account: dict, db_path: Optional[str] = None) -> str:
    """The briefing text for one account."""
    aid = account["id"]
    lines = [f"☀️ Morning briefing — @{account['handle']}"]

    ideas = _cool_ideas(aid, db_path=db_path)
    if ideas:
        lines.append(f"\n💡 Ideas bank ({len(ideas)} from yesterday's COOL signals):")
        for s in ideas:
            lines.append(f"  • [{s['score']:.1f}] {s['title']}")
            if s.get("angle"):
                lines.append(f"      angle: {s['angle']}")
    else:
        lines.append("\n💡 Ideas bank: empty — quiet day yesterday. "
                     "Good day for /evergreen (a no-news-peg opinion post).")

    outbox = memory.get_outbox(account_id=aid, db_path=db_path)
    if outbox:
        ids = ", ".join(f"#{p['id']}" for p in outbox[:8])
        lines.append(f"\n📤 Outbox: {len(outbox)} approved and unposted ({ids}) — "
                     "post them or they go stale.")

    # corpus suggestions: pieces from the polled stream that look like
    # training material — filed here, accepted/rejected in the web app only
    try:
        from style.corpus import CorpusManager
        CorpusManager(db_path=db_path).suggest(account)
    except Exception:  # noqa: BLE001
        pass
    pending = memory.get_corpus_suggestions(aid, status="pending", db_path=db_path)
    if pending:
        lines.append(f"\n🧬 {len(pending)} writing sample(s) suggested for your "
                     "voice corpus — review them in the web app (Settings).")

    preds = memory.get_open_predictions(aid, db_path=db_path)
    if preds:
        lines.append(f"\n🔮 {len(preds)} open prediction(s) being watched:")
        for p in preds[:3]:
            lines.append(f"  • \"{p['prediction']}\" ({p['made_at'][:10]})")

    st = _day_stats(aid, db_path=db_path)
    hp = historical_performance(aid, db_path=db_path)["overall"]
    lines.append(f"\n📊 Last 24h: {st['drafted']} drafted · {st['approved']} approved · "
                 f"{st['rejected']} rejected · {st['posted']} posted · "
                 f"historical_perf {hp}")
    try:
        from config import settings as cfg
        spent = memory.cost_today(db_path=db_path)
        cap = f" of ${cfg.daily_budget_usd:.2f} cap" if cfg.daily_budget_usd > 0 else ""
        lines.append(f"💰 Claude spend today: ${spent:.2f}{cap}")
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"⏰ {timing.describe_windows(aid, db_path=db_path)}")
    return "\n".join(lines)


def send_briefings(db_path: Optional[str] = None,
                   notifier: Optional[poster.TelegramNotifier] = None) -> int:
    """Build + send one briefing per active account. Returns how many sent."""
    notifier = notifier or poster.TelegramNotifier()
    sent = 0
    for acct in memory.list_active_accounts(db_path=db_path):
        text = build(acct, db_path=db_path)
        if notifier.configured and notifier.send(text):
            sent += 1
        else:
            logger.info("Briefing for @%s (telegram not configured):\n%s",
                        acct["handle"], text)
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    memory.init_db()
    for a in memory.list_active_accounts():
        print(build(a))
        print()
