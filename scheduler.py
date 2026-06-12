"""
scheduler.py — the always-on polling loop. The "regular polling" pillar.

Runs every watcher on its own interval, plus a process cycle that scores new
articles per-account and drafts the top signals. This is what turns the agent
from "run a command" into "it watches and feeds you content on its own."

    python scheduler.py            # start the loop (Ctrl-C to stop)
    python scheduler.py --once     # run every job once and exit (great for testing)
    python scheduler.py --seed     # add a starter watch list + demo accounts, then exit

Intervals come from config (env-overridable). Jobs use max_instances=1 and
coalesce=True so a slow cycle never stacks up overlapping runs.

WHAT RUNS, AND HOW OFTEN (defaults; see config.py):
    news      15 min   RSS across your chosen verticals/regions
    youtube   15 min   tracked channels (keyless upload RSS)
    reddit    20 min   tracked subreddits (keyless JSON, real upvote velocity)
    trends    30 min   Google Trends per geo (keyless RSS, real traffic velocity)
    wikipedia 60 min   edit-storm detector (keyless API)
    process   10 min   per-account score (filtered to each persona's lanes) + draft FIRE/WARM
    callbacks 60 min   open predictions vs incoming news -> "I called this" drafts
    crowd     weekly   Genome B refresh from the niche's top posts (needs TWITTER_API_IO_KEY)
    learn     6 h      approve/reject + engagement learning pass (no-op until new data)
    telegram  1 min    your phone commands: /approve /reject /posted /perf (needs TELEGRAM_*)
    twitter   —        disabled stub unless you wire API access

New drafts are also PUSHED to your Telegram chat as they're generated (when
TELEGRAM_* is configured) — approve and post from your phone; the system never
posts to X for you, so there's nothing for X to flag.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

# Roomy enough that a long process cycle (45s Claude blocks) never starves the
# watchers; each job is still max_instances=1 so nothing stacks on itself.
_EXECUTORS = {"default": ThreadPoolExecutor(max_workers=20)}
# A job whose tick is missed (slow predecessor, sleeping host) still runs if
# it's within this window, instead of being silently dropped.
_JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}

from config import settings
from pipeline import fatigue, memory, poster
from pipeline.callbacks import CallbackWatcher
from pipeline.context import ContextRetriever, transcript_excerpt
from pipeline.decision import DecisionAgent
from pipeline.generator import ContentGenerator
from pipeline.monitor import NewsMonitor
from pipeline.telegram_bot import TelegramCommander
from sources import feeds_for
from style.crowd import CrowdWisdomScraper
from style.voice import effective_for
from style.learning import ReviewLearner
from style.scorer import PersonaConsistencyScorer
from watch.reddit import RedditWatcher
from watch.trends import TrendsWatcher, WikipediaWatcher
from watch.twitter import TwitterWatcher
from watch.instagram import InstagramWatcher
from watch.moments import MomentsWatcher
from watch.listening import custom_feed_specs, merge_feed_specs
from watch.youtube import YouTubeWatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("scheduler")

# Fallback lanes when there are no accounts yet (first boot). Once accounts
# exist, job_news pulls the UNION of their verticals instead (see active_news_
# verticals) so a brand persona's lanes get fetched and a politics-only setup
# never wastes fetches on marketing feeds.
NEWS_VERTICALS = ["politics", "finance", "sports", "entertainment"]
NEWS_REGIONS = ["india", "us"]

# How many top signals to draft per account per process cycle.
DRAFT_TOP_N = 5
DRAFT_FORMAT = "hot_take"  # fallback only — the decision agent picks per signal
TWITTER_ENABLED = False  # flip to True only after you implement watch/twitter.py


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
def active_news_verticals() -> list[str]:
    """The lanes to actually fetch: the union of active accounts' verticals,
    intersected with verticals we have feeds for. An account with no verticals
    set means 'all', so any unscoped persona pulls the whole catalog. Falls back
    to NEWS_VERTICALS before any account exists."""
    from sources import VERTICALS as ALL
    accounts = memory.list_active_accounts()
    if not accounts:
        return NEWS_VERTICALS
    chosen: set[str] = set()
    for a in accounts:
        vs = a.get("verticals")
        if not vs:                      # null/[] -> sees everything
            return list(ALL)
        chosen.update(vs)
    return [v for v in ALL if v in chosen] or NEWS_VERTICALS


def job_news():
    # regions=None -> every region, so global-only brand feeds (HN, marketing,
    # etc.) get ingested; per-account region scoping still narrows what's scored.
    # Custom rss_feed/news_query watch rows ride along (per-brand listening).
    feeds = merge_feed_specs(feeds_for(active_news_verticals(), regions=None),
                             custom_feed_specs())
    NewsMonitor(rss_feeds=feeds).run()


def job_youtube():
    YouTubeWatcher().run()


def job_reddit():
    RedditWatcher().run()


def job_trends():
    TrendsWatcher().run()


def job_wikipedia():
    WikipediaWatcher().run()


def job_discover():
    """Autonomous discovery: search YouTube + Reddit for every account's own
    topics. No manual watch-list entry — set a niche, the agent goes looking."""
    from watch.discover import DiscoveryWatcher
    DiscoveryWatcher().run()


def job_twitter():
    TwitterWatcher(enabled=TWITTER_ENABLED).run()


def job_moments():
    # the proactive layer: calendar moments entering their planning window.
    # Idempotent (dedup per occurrence), so running twice a day is free.
    MomentsWatcher().run()


def job_instagram():
    # auto-enabled only when IG_GRAPH_TOKEN is set; pulls your own/benchmark
    # business account via the official Graph API as visual inspiration refs.
    InstagramWatcher().run()


def job_telegram():
    """Poll Telegram for your commands (/approve, /posted, /perf, ...). This is
    the phone-only copilot loop; no-op unless TELEGRAM_* is configured."""
    TelegramCommander().poll_once()


def job_counter():
    """Find heavily-covered FIRE stories where everyone says the same thing,
    and draft the angle nobody is taking. At most one analysis per story."""
    from pipeline.counter import CounterNarrativeDetector
    tally = CounterNarrativeDetector().run()
    if tally["targets"]:
        logger.info("counter: %s", tally)


def job_backup():
    """Daily snapshot of the SQLite brain (VACUUM INTO), oldest pruned.
    The whole moat is one file — this is the insurance."""
    path = memory.backup_db()
    logger.info("backup written: %s", path)


def job_briefing():
    """Daily morning digest per account: ideas bank (COOL signals), outbox
    nag, open predictions, yesterday's numbers, timing advice."""
    from pipeline import briefing
    briefing.send_briefings()


def job_callbacks():
    """Match open predictions against the incoming article stream; when one
    resolves, draft the 'I called this' (or 'I got this wrong') post. Free on
    quiet cycles — Claude is only called when the keyword prefilter passes."""
    tally = CallbackWatcher().run()
    if tally["checked"]:
        logger.info("callbacks: %s", tally)


def job_crowd():
    """Weekly Genome B refresh: scrape the niche's top posts per account and
    re-distill crowd patterns. No-ops without TWITTER_API_IO_KEY."""
    if not settings.twitter_api_io_key:
        logger.info("crowd: no TWITTER_API_IO_KEY — skipping Genome B refresh.")
        return
    scraper = CrowdWisdomScraper()
    for acct in memory.list_active_accounts():
        try:
            scraper.refresh(acct)
        except Exception as exc:  # noqa: BLE001
            logger.error("crowd refresh failed for %s: %s", acct["handle"], exc)


def job_learn():
    """Approve/reject learning pass per account. Cheap: it no-ops (no Claude
    call) unless new reviews have accumulated past the minimum thresholds."""
    learner = ReviewLearner()
    for acct in memory.list_active_accounts():
        try:
            report = learner.apply_learning(acct["id"])
            if report["updated"]:
                logger.info("[%s] voice updated from reviews: %s",
                            acct["handle"], report.get("summary") or "stats-only")
            else:
                logger.info("[%s] learn: %s", acct["handle"], report.get("reason"))
        except Exception as exc:  # noqa: BLE001
            logger.error("learning pass failed for %s: %s", acct["handle"], exc)


def job_process():
    """Score new articles for each active persona (its lanes only), then draft
    the top FIRE/WARM signals through the persona-consistency gate."""
    accounts = memory.list_active_accounts()
    if not accounts:
        logger.warning("No accounts configured — run `python scheduler.py --seed` or add one.")
        return

    agent = DecisionAgent()
    gen, scorer = ContentGenerator(), PersonaConsistencyScorer()
    notifier = poster.TelegramNotifier()
    retriever = ContextRetriever()
    from pipeline.grounding import GroundingChecker
    from pipeline.integrity import StanceArcGuard, RiskSimulator
    grounding = GroundingChecker() if settings.grounding_enabled else None
    arc_guard = StanceArcGuard() if settings.arc_guard_enabled else None
    risk = RiskSimulator() if settings.risk_check_enabled else None

    for acct in accounts:
        tally = agent.run(acct, limit=settings.process_batch, per_account=True)
        logger.info("[%s] scored %s", acct["handle"], tally)

        dna = memory.get_style_dna(acct["id"])
        if not dna:
            logger.info("[%s] no Style DNA yet — skipping drafting.", acct["handle"])
            continue

        # Blend in crowd patterns (Genome B) when they exist; pure Genome A otherwise.
        genome = effective_for(acct["id"])
        # only draft this account's own fresh, unposted FIRE/WARM signals
        shortlist = [s for s in (memory.get_signals_by_tier("FIRE")
                                 + memory.get_signals_by_tier("WARM"))
                     if s.get("account_id") == acct["id"]][:DRAFT_TOP_N]
        drafted = 0
        for s in shortlist:
            # skip signals already drafted (a post row exists for this signal+account)
            existing = [p for p in memory.get_posts(account_id=acct["id"])
                        if p.get("signal_id") == s["id"]]
            if existing:
                continue
            # audience fatigue gate: don't draft the Nth take on one topic
            fresh = fatigue.topic_freshness(acct["id"], s.get("topic"))
            if fresh["fatigued"]:
                logger.info("[%s] fatigue: skipping '%s' (%d recent posts on %s)",
                            acct["handle"], s["title"][:40],
                            fresh["recent_posts"], fresh["topic"])
                continue
            # Load the 6-layer memory package (free — pure SQLite reads).
            ctx = retriever.context_for(s, acct)
            # Draft in the format the decision agent judged best for this story.
            fmt = s.get("format") or DRAFT_FORMAT
            # YouTube uploads with a fetched transcript get the video_reaction
            # treatment: the draft quotes the video's actual claims.
            if s.get("source") in ("youtube", "yt_search") and s.get("article_id"):
                excerpt = transcript_excerpt(memory.get_article(s["article_id"]))
                if excerpt:
                    fmt = "video_reaction"
                    ctx = f"{ctx}\n{excerpt}" if ctx else excerpt
            # red-team backlash only on FIRE (high stakes); arc guard always
            draft = gen.generate_checked(
                s, genome, fmt=fmt, scorer=scorer, account_id=acct["id"],
                persist=True, context=ctx, grounding=grounding,
                arc_guard=arc_guard,
                risk=risk if s.get("tier") == "FIRE" else None)
            drafted += 1
            flag = " NEEDS REVIEW" if draft["needs_review"] else ""
            score = f"{draft['persona_score']:.0f}" if draft["persona_score"] is not None else "-"
            logger.info("[%s] drafted %s (persona=%s%s): %s",
                        acct["handle"], fmt, score, flag, s["title"][:50])
            # FIRE drafts get alternative hooks — you pick the strongest
            # opening (the copilot version of the A/B engine).
            if not draft["empty"] and draft.get("post_id") and s.get("tier") == "FIRE":
                hooks = gen.alt_hooks(draft["content"], s, genome)
                if hooks:
                    memory.update_post_meta(draft["post_id"], {"alt_hooks": hooks})
            # Push the draft to your phone the moment it exists — the
            # first-mover window is won or lost right here.
            if not draft["empty"] and draft.get("post_id"):
                notifier.notify_draft(memory.get_post(draft["post_id"]), s["title"])
        if drafted:
            logger.info("[%s] %d new draft(s) ready. Review with: python review.py "
                        "(or /approve on Telegram)", acct["handle"], drafted)


JOBS = [
    ("news", job_news, settings.poll_news_min),
    ("youtube", job_youtube, settings.poll_youtube_min),
    ("reddit", job_reddit, settings.poll_reddit_min),
    ("trends", job_trends, settings.poll_trends_min),
    ("wikipedia", job_wikipedia, settings.poll_wikipedia_min),
    ("process", job_process, settings.poll_process_min),
    ("callbacks", job_callbacks, settings.poll_callbacks_min),
    ("counter", job_counter, settings.poll_counter_min),
    ("crowd", job_crowd, settings.poll_crowd_min),
    ("learn", job_learn, settings.poll_learn_min),
    ("backup", job_backup, 24 * 60),
    ("moments", job_moments, 12 * 60),
]
if settings.discover_enabled:
    JOBS.append(("discover", job_discover, settings.poll_discover_min))
if settings.telegram_bot_token and settings.telegram_chat_id:
    JOBS.append(("telegram", job_telegram, settings.poll_telegram_min))
if TWITTER_ENABLED:
    JOBS.append(("twitter", job_twitter, settings.poll_news_min))
if os.getenv("IG_GRAPH_TOKEN", "").strip():
    JOBS.append(("instagram", job_instagram, settings.poll_news_min))


# --------------------------------------------------------------------------- #
# Seeding + entrypoints
# --------------------------------------------------------------------------- #
def seed():
    """Create a couple of demo personas and a starter watch list. Idempotent.
    EDIT the channel IDs / subreddits to your own before relying on it."""
    memory.init_db()

    # Two personas, each scoped to its lanes (the multi-account setup).
    memory.upsert_account(
        handle="markets_take", niche="data-backed markets & economy commentary, skeptical of spin",
        topics=["markets", "economy", "rbi", "fed"],
        verticals=["finance"], regions=["india", "us"],
    )
    memory.upsert_account(
        handle="politics_take", niche="sharp Indian + US political commentary, contrarian, data-led",
        topics=["indian politics", "us politics", "policy"],
        verticals=["politics"], regions=["india", "us"],
    )

    # Starter watch list (deduplicated). Replace refs with sources you actually follow.
    for kind, ref, label, vert, region in [
        ("subreddit", "IndiaSpeaks", "r/IndiaSpeaks", "politics", "india"),
        ("subreddit", "india", "r/india", "politics", "india"),
        ("subreddit", "IndianStreetBets", "r/IndianStreetBets", "finance", "india"),
        ("subreddit", "politics", "r/politics", "politics", "us"),
        ("subreddit", "economics", "r/economics", "finance", "us"),
        ("trends_geo", "IN", "India trends", None, "india"),
        ("trends_geo", "US", "US trends", None, "us"),
        # YouTube channel IDs (these are examples — swap for channels you track):
        # ("youtube_channel", "UCYwGL5iVNbu2_Ta9SvQTJ4w", "Example News", "politics", "india"),
    ]:
        memory.add_watch(kind=kind, ref=ref, label=label, vertical=vert, region=region)

    accts = memory.list_active_accounts()
    watches = memory.get_watch()
    logger.info("Seeded %d accounts, %d watch sources.", len(accts), len(watches))
    logger.info("Accounts: %s", [a["handle"] for a in accts])
    logger.info("Add YouTube channels and your own subreddits in scheduler.seed(), "
                "then build Style DNA per account with style.dna.")


def _briefing_utc() -> tuple[int, int]:
    """BRIEFING_HOUR is local; APScheduler runs UTC. Convert (hour, minute)."""
    total = (settings.briefing_hour_local * 60 - settings.tz_offset_min) % (24 * 60)
    return total // 60, total % 60


def run_once():
    """Run every job a single time, in order, then exit. For testing the wiring."""
    memory.init_db()
    for name, fn, _ in JOBS + [("briefing", job_briefing, 0)]:
        logger.info("── running job: %s ──", name)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            logger.error("Job %s failed: %s", name, exc)
    logger.info("All jobs ran once.")


def start_background() -> BackgroundScheduler:
    """Same job set as start(), but on a BackgroundScheduler — used by the web
    app (api/main.py) so one deployed process runs watchers + brain + UI."""
    memory.init_db()
    sched = BackgroundScheduler(timezone="UTC", executors=_EXECUTORS,
                                job_defaults=_JOB_DEFAULTS)
    for name, fn, minutes in JOBS:
        sched.add_job(fn, "interval", minutes=minutes, id=name)
    bh, bm = _briefing_utc()
    sched.add_job(job_briefing, "cron", hour=bh, minute=bm, id="briefing")
    sched.add_job(job_process, "date", id="process_boot")
    sched.start()
    logger.info("Background scheduler started with %d jobs + daily briefing.", len(JOBS))
    return sched


def start():
    """Start the blocking scheduler loop."""
    memory.init_db()
    if not memory.list_active_accounts():
        logger.warning("No accounts yet. Run `python scheduler.py --seed` first.")
    sched = BlockingScheduler(timezone="UTC", executors=_EXECUTORS,
                              job_defaults=_JOB_DEFAULTS)
    for name, fn, minutes in JOBS:
        sched.add_job(fn, "interval", minutes=minutes, id=name)
        logger.info("scheduled '%s' every %d min", name, minutes)
    # daily briefing at the configured local hour (converted to UTC)
    bh, bm = _briefing_utc()
    sched.add_job(job_briefing, "cron", hour=bh, minute=bm, id="briefing")
    logger.info("scheduled 'briefing' daily at %02d:%02d UTC "
                "(%02d:00 %s)", bh, bm, settings.briefing_hour_local, settings.tz_label)
    # kick a process cycle shortly after boot so you don't wait a full interval
    sched.add_job(job_process, "date", id="process_boot")
    logger.info("Polling loop starting. Ctrl-C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Pulse polling loop")
    p.add_argument("--once", action="store_true", help="run every job once and exit")
    p.add_argument("--seed", action="store_true", help="seed demo accounts + watch list and exit")
    args = p.parse_args()
    if args.seed:
        seed()
    elif args.once:
        run_once()
    else:
        start()
