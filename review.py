"""
review.py — review drafts and run the manual posting flow from the terminal.

    python review.py                 # list pending drafts (status=draft)
    python review.py --account markets_take
    python review.py --approve 12    # approve: final text + tap-to-compose X link
    python review.py --reject 12     # reject (feeds the learning loop)
    python review.py --outbox        # approved drafts you haven't posted yet
    python review.py --posted 12 --url https://x.com/...   # you posted it
    python review.py --perf 12 --likes 120 --retweets 30 --replies 4
    python review.py --all           # include already-actioned drafts

THE FLOW (no auto-posting to X — by design, so you're never flagged):
approve → the final, AI-labeled text is printed + copied to your clipboard +
an X intent link opens the compose box pre-filled → YOU press Post → --posted
closes the loop → --perf logs engagement, which sharpens future scoring.
The same flow works from your phone via the Telegram bot (see pipeline/telegram_bot.py).

Every status you set is a learning signal: approve/reject trains the voice
(style/learning.py), engagement trains the news judgment (historical_perf).
"""

from __future__ import annotations

import argparse

from pipeline import memory, poster


def _print_post(p: dict) -> None:
    score = f"{p['persona_score']:.0f}" if p.get("persona_score") is not None else "-"
    flag = " ⚠️ REVIEW" if p.get("needs_review") else ""
    print(f"\n#{p['id']}  [{p['format']}]  persona={score}{flag}  status={p['status']}")
    print(f"  {p['content']}")


def _approve(post_id: int) -> None:
    post = memory.get_post(post_id)
    if not post:
        print(f"No draft #{post_id}.")
        return
    memory.set_post_status(post_id, "approved")
    post = memory.get_post(post_id)
    result = poster.dispatch_approved(post)
    texts, urls = result["texts"], result["intent_urls"]
    print(f"Draft #{post_id} approved. Post it yourself:\n")
    for i, (t, u) in enumerate(zip(texts, urls), 1):
        prefix = f"[{i}/{len(texts)}] " if len(texts) > 1 else ""
        print(f"{prefix}{t}\n  ({len(t)}/{poster.X_CHAR_LIMIT} chars)")
        print(f"  compose link: {u}\n")
    if poster.copy_to_clipboard(texts[0]):
        print("(first tweet copied to clipboard)")
    if result.get("card"):
        print(f"image card: {result['card']}"
              + (" (also sent to Telegram)" if result.get("card_sent") else ""))
    if result["telegram"]:
        print("(sent to your Telegram too)")
    if result["channel"]:
        print("(published to your Telegram channel)")
    print(f"\nAfter posting:  python review.py --posted {post_id} [--url LIVE_URL]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Review drafts + manual posting flow")
    ap.add_argument("--account", help="filter by account handle")
    ap.add_argument("--approve", type=int, metavar="ID")
    ap.add_argument("--reject", type=int, metavar="ID")
    ap.add_argument("--outbox", action="store_true", help="approved, not yet posted")
    ap.add_argument("--posted", type=int, metavar="ID", help="mark as posted by you")
    ap.add_argument("--url", help="live URL of the posted tweet (with --posted)")
    ap.add_argument("--perf", type=int, metavar="ID", help="log engagement for a post")
    ap.add_argument("--likes", type=int, default=0)
    ap.add_argument("--retweets", type=int, default=0)
    ap.add_argument("--replies", type=int, default=0)
    ap.add_argument("--views", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="include actioned drafts")
    args = ap.parse_args()
    memory.init_db()

    if args.approve:
        _approve(args.approve)
        return
    if args.reject:
        memory.set_post_status(args.reject, "rejected")
        print(f"Draft #{args.reject} rejected — the learning loop will use this.")
        return
    if args.posted:
        memory.mark_posted(args.posted, url=args.url)
        print(f"Draft #{args.posted} marked posted.")
        # File it into long-term memory (stance, timeline, predictions).
        from pipeline.updater import MemoryUpdater
        report = MemoryUpdater().on_posted(args.posted)
        if report.get("ok"):
            extra = f" Prediction tracked: \"{report['prediction']}\"" if report.get("prediction") else ""
            print(f"Memory filed — topic '{report['topic']}', stance logged.{extra}")
        else:
            print(f"(memory filing skipped: {report.get('error')})")
        print(f"Log engagement later with:\n"
              f"  python review.py --perf {args.posted} --likes N --retweets N --replies N")
        return
    if args.perf:
        memory.record_engagement(args.perf, likes=args.likes, retweets=args.retweets,
                                 replies=args.replies, views=args.views)
        print(f"Engagement logged for #{args.perf}: {args.likes} likes, "
              f"{args.retweets} RTs, {args.replies} replies, {args.views} views.")
        return

    account_id = None
    if args.account:
        for a in memory.list_active_accounts():
            if a["handle"] == args.account:
                account_id = a["id"]
                break
        if account_id is None:
            print(f"No active account '{args.account}'.")
            return

    if args.outbox:
        posts = memory.get_outbox(account_id=account_id)
        if not posts:
            print("Outbox empty — nothing approved and unposted.")
            return
        print(f"{len(posts)} post(s) waiting for you to post:")
        for p in posts:
            _print_post(p)
        print("\nGet the compose link again:  python review.py --approve ID")
        return

    status = None if args.all else "draft"
    posts = memory.get_posts(account_id=account_id, status=status)
    if not posts:
        print("No drafts to show.")
        return
    print(f"{len(posts)} draft(s):")
    for p in posts:
        _print_post(p)
    print("\nAct on a draft:  python review.py --approve ID   |   --reject ID")


if __name__ == "__main__":
    main()
