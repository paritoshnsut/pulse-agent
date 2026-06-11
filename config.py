"""
config.py — single source of truth for environment + tunable constants.

Per CLAUDE.md rule #5: every Claude call uses claude-sonnet-4-6 (centralized
here so it is a one-line swap). Per rule #6: all secrets come from .env, never
hardcoded. Import `settings` everywhere; never read os.environ directly elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present. Real keys live there, never in git.
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # --- Anthropic ---
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # --- News sources ---
    news_api_key: str = os.getenv("NEWS_API_KEY", "")
    gnews_api_key: str = os.getenv("GNEWS_API_KEY", "")

    # --- Storage ---
    db_path: str = os.getenv("DB_PATH", str(PROJECT_ROOT / "agent.db"))
    schema_path: str = str(PROJECT_ROOT / "db" / "schema.sql")
    # How long a write waits for a competing write before giving up. The single
    # container shares one SQLite file across web/API/watchers/telegram; this is
    # the queue that prevents 'database is locked' under concurrency.
    db_busy_timeout_s: float = float(os.getenv("DB_BUSY_TIMEOUT_S", "30"))
    # Concurrency for the RSS fetch fan-out (65 feeds sequentially is slow;
    # these are I/O-bound so threads are the right tool).
    feed_fetch_workers: int = int(os.getenv("FEED_FETCH_WORKERS", "12"))

    # --- Signal scoring weights (must sum to 1.0). Evolved from CLAUDE.md's
    # 5-factor model: corroboration (coverage breadth across our own feeds)
    # and memory_leverage (does THIS account hold receipts on the topic) are
    # new, both deterministic and free; the two recency-driven factors shrank
    # to make room since corroboration now carries "is this actually big". ---
    weights: dict = field(default_factory=lambda: {
        "velocity": 0.20,
        "relevance": 0.20,
        "corroboration": 0.15,
        "reaction_potential": 0.15,
        "memory_leverage": 0.10,
        "window_urgency": 0.10,
        "historical_perf": 0.10,
    })

    # --- Corroboration: distinct outlets carrying the story within the window.
    # saturation outlets -> 10/10. Stories younger than the grace period with
    # no corroboration yet score a neutral 5 (a 20-minute-old scoop hasn't HAD
    # time to corroborate — unknown is not punished, same rule as recency). ---
    corroboration_window_min: int = int(os.getenv("CORROBORATION_WINDOW_MIN", "360"))
    corroboration_saturation: int = int(os.getenv("CORROBORATION_SATURATION", "5"))
    corroboration_grace_min: int = int(os.getenv("CORROBORATION_GRACE_MIN", "45"))

    # --- Freshness multiplier on the composite (fatigue folded into scoring,
    # so saturated topics rank down BEFORE Claude drafting money is spent):
    # 0-1 recent posts on topic -> x1.0, 2 -> x0.85, >= fatigue_max_posts -> floor. ---
    freshness_floor: float = float(os.getenv("FRESHNESS_FLOOR", "0.6"))

    # --- Urgency tier cutoffs (composite score is 0-10). From CLAUDE.md. ---
    tier_fire: float = 8.5   # >= -> FIRE
    tier_warm: float = 6.5   # >= -> WARM
    tier_cool: float = 4.5   # >= -> COOL; below -> SKIP

    # --- Recency decay (minutes). Drives window_urgency and the news velocity
    # proxy. TAU=60 maps the first-mover window from CLAUDE.md onto 0-10:
    #   0 min -> 10.0 | 15 min -> 7.8 | 60 min -> 3.7 | 120 min -> 1.4
    recency_tau_minutes: float = 60.0

    # --- Default RSS feeds (Indian politics/economy, matching the niche).
    # Override per-run by passing your own list to NewsMonitor. ---
    default_rss_feeds: tuple = (
        "https://www.thehindu.com/news/national/feeder/default.rss",
        "https://indianexpress.com/section/india/feed/",
        "https://www.livemint.com/rss/news",
        "https://www.business-standard.com/rss/home_page_top_stories.rss",
    )

    # --- Polling intervals (minutes). Chosen against each source's real dynamics
    # and rate limits; see README. Override via env (e.g. POLL_NEWS_MIN=10). ---
    poll_news_min: int = int(os.getenv("POLL_NEWS_MIN", "15"))
    poll_youtube_min: int = int(os.getenv("POLL_YOUTUBE_MIN", "15"))
    poll_reddit_min: int = int(os.getenv("POLL_REDDIT_MIN", "20"))
    poll_trends_min: int = int(os.getenv("POLL_TRENDS_MIN", "30"))
    poll_wikipedia_min: int = int(os.getenv("POLL_WIKIPEDIA_MIN", "60"))
    poll_process_min: int = int(os.getenv("POLL_PROCESS_MIN", "10"))

    # Skip scoring anything older than this at ingest time (don't pay Claude to
    # judge stale news, esp. on first run). 0 disables the cutoff.
    stale_after_min: int = int(os.getenv("STALE_AFTER_MIN", "180"))

    # Per-process cap on how many articles the scorer drains per cycle (cost guard).
    process_batch: int = int(os.getenv("PROCESS_BATCH", "40"))

    # --- Crowd wisdom / Genome B (TwitterAPI.io; no key -> module no-ops) ---
    twitter_api_io_key: str = os.getenv("TWITTER_API_IO_KEY", "")
    crowd_min_likes: int = int(os.getenv("CROWD_MIN_LIKES", "1000"))   # CLAUDE.md: 1000+ likes
    crowd_top_k: int = int(os.getenv("CROWD_TOP_K", "50"))             # CLAUDE.md: top 50
    poll_crowd_min: int = int(os.getenv("POLL_CROWD_MIN", str(7 * 24 * 60)))  # weekly

    # --- Approve/reject learning loop ---
    # Don't learn from noise: need this many human-actioned drafts overall, and
    # this many on EACH side (approved-ish vs rejected) before the Claude
    # contrast step runs. Below the side floor, only deterministic stats update.
    learn_min_reviewed: int = int(os.getenv("LEARN_MIN_REVIEWED", "10"))
    learn_min_side: int = int(os.getenv("LEARN_MIN_SIDE", "3"))
    # Bayesian shrinkage toward neutral 5.0 for historical_perf: with few reviews
    # the score stays near 5; it only moves as evidence accumulates.
    learn_prior_weight: float = float(os.getenv("LEARN_PRIOR_WEIGHT", "10"))
    poll_learn_min: int = int(os.getenv("POLL_LEARN_MIN", "360"))      # every 6h, cheap no-op if no new reviews

    # --- Copilot dispatch (manual posting; no X API, no bot-flagging risk) ---
    # Bot token from @BotFather; chat_id is YOUR private chat with the bot
    # (message the bot once, then https://api.telegram.org/bot<token>/getUpdates
    # shows it). channel_id optional: a Telegram channel the bot may auto-publish
    # approved posts to — allowed by Telegram, bots are first-class there.
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_channel_id: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    poll_telegram_min: int = int(os.getenv("POLL_TELEGRAM_MIN", "1"))
    # Rule #10: label appended to the final postable text. Set AI_LABEL= (empty)
    # in .env to disable for manually-posted content — your call as the poster.
    ai_label: str = os.getenv("AI_LABEL", "🤖 AI-assisted")

    # --- Image cards (Pillow; attached to the Telegram approval package) ---
    cards_enabled: bool = os.getenv("CARDS_ENABLED", "1").lower() not in ("0", "false", "")
    cards_dir: str = os.getenv("CARDS_DIR", str(PROJECT_ROOT / "cards"))

    # --- Web app auth. Three modes, auto-selected:
    #   supabase  — SUPABASE_URL + SUPABASE_JWT_SECRET set: real per-user
    #               accounts (email+password via Supabase), JWTs verified
    #               locally. ALLOWED_EMAILS (comma-sep) restricts who may in.
    #   password  — only APP_PASSWORD set: one shared family password.
    #   dev       — nothing set: open. Local development only. ---
    app_password: str = os.getenv("APP_PASSWORD", "")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    allowed_emails: str = os.getenv("ALLOWED_EMAILS", "")

    @property
    def auth_mode(self) -> str:
        if self.supabase_url and self.supabase_jwt_secret:
            return "supabase"
        return "password" if self.app_password else "dev"

    def allowed_email_set(self) -> set:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    # --- Cost guard: every Claude call is logged (claude_logs) with an
    # estimated cost; when today's spend crosses the budget, calls stop and a
    # Telegram alert fires once. 0 disables the cap (logging always on). ---
    daily_budget_usd: float = float(os.getenv("DAILY_BUDGET_USD", "5.0"))
    cost_in_per_mtok: float = float(os.getenv("COST_IN_PER_MTOK", "3.0"))
    cost_out_per_mtok: float = float(os.getenv("COST_OUT_PER_MTOK", "15.0"))

    # --- Grounding shield: pre-review check that every factual claim in a
    # draft is supported by the source material the model was given ---
    grounding_enabled: bool = os.getenv("GROUNDING_ENABLED", "1").lower() not in ("0", "false", "")

    # --- Stance arc guard: flag drafts that contradict your established
    # positions (a flip-flop is the cardinal political sin). Free at cold start
    # — only spends a call when you HAVE past stances on the topic. ---
    arc_guard_enabled: bool = os.getenv("ARC_GUARD_ENABLED", "1").lower() not in ("0", "false", "")

    # --- Backlash simulator: on high-stakes drafts, a "how could this be
    # screenshotted / misread / turned against you" pass. FIRE + inherently
    # spicy formats only, to keep the spend targeted. ---
    risk_check_enabled: bool = os.getenv("RISK_CHECK_ENABLED", "1").lower() not in ("0", "false", "")

    # --- Draft staleness: warn when a draft has been waiting this long ---
    draft_stale_hours: int = int(os.getenv("DRAFT_STALE_HOURS", "24"))

    # --- Backups: daily VACUUM INTO copies, oldest pruned past the cap ---
    backups_dir: str = os.getenv("BACKUPS_DIR", str(PROJECT_ROOT / "backups"))
    backup_keep: int = int(os.getenv("BACKUP_KEEP", "7"))

    # --- Voice corpus: training-set caps + suggestion throttle ---
    corpus_max_own: int = int(os.getenv("CORPUS_MAX_OWN", "300"))
    corpus_max_inspiration: int = int(os.getenv("CORPUS_MAX_INSPIRATION", "10"))
    corpus_suggest_max: int = int(os.getenv("CORPUS_SUGGEST_MAX", "5"))
    # Anti-overfit: no single outlet/author may exceed this fraction of the
    # inspiration training set, so one columnist can't warp `influences`.
    corpus_source_cap_fraction: float = float(os.getenv("CORPUS_SOURCE_CAP_FRACTION", "0.5"))

    # --- Visuals: Satori-rendered branded graphics (see VISUALS.md).
    # The Node render service runs persistently on localhost; Python spawns
    # and health-checks it. Pillow stays the fail-safe fallback. ---
    visuals_enabled: bool = os.getenv("VISUALS_ENABLED", "1").lower() not in ("0", "false", "")
    visuals_port: int = int(os.getenv("VISUALS_PORT", "8787"))
    visuals_dir: str = os.getenv("VISUALS_DIR", str(PROJECT_ROOT / "visuals"))
    render_dir: str = os.getenv("RENDER_DIR", str(PROJECT_ROOT / "render"))

    # --- Content Squeezer (repurpose one input into a multi-format pack).
    # Each tuple is (format, count). Text-only formats — multi-platform APIs
    # and visual generation are a later phase. ---
    repurpose_plan: tuple = (
        ("linkedin_post", 1),
        ("thread", 2),
        ("quote_context", 3),
        ("newsletter", 1),
        ("video_script", 1),
    )
    repurpose_max_chars: int = int(os.getenv("REPURPOSE_MAX_CHARS", "12000"))

    # --- Audience fatigue detector: don't draft the Nth take on one topic ---
    fatigue_window_hours: int = int(os.getenv("FATIGUE_WINDOW_HOURS", "72"))
    fatigue_max_posts: int = int(os.getenv("FATIGUE_MAX_POSTS", "3"))

    # --- Timing engine. All storage is UTC; advice is shown in your local
    # timezone (IST default). Below min samples the windows are honest
    # niche defaults, labeled as such. ---
    tz_offset_min: int = int(os.getenv("TZ_OFFSET_MIN", "330"))
    tz_label: str = os.getenv("TZ_LABEL", "IST")
    timing_min_samples: int = int(os.getenv("TIMING_MIN_SAMPLES", "8"))

    # --- Morning briefing (daily Telegram digest), in local time ---
    briefing_hour_local: int = int(os.getenv("BRIEFING_HOUR", "8"))

    # --- Counter-narrative detector ---
    poll_counter_min: int = int(os.getenv("POLL_COUNTER_MIN", "120"))
    counter_min_coverage: int = int(os.getenv("COUNTER_MIN_COVERAGE", "3"))

    # --- Callback generator (open predictions vs incoming news) ---
    poll_callbacks_min: int = int(os.getenv("POLL_CALLBACKS_MIN", "60"))
    # A candidate article must share at least this many distinct keywords with
    # the prediction before a Claude verification call is spent on it.
    callback_min_keyword_hits: int = int(os.getenv("CALLBACK_MIN_KEYWORD_HITS", "2"))
    callback_max_candidates: int = int(os.getenv("CALLBACK_MAX_CANDIDATES", "3"))
    # Open predictions older than this are marked expired (horizon text like
    # "by Q3" isn't reliably parseable, so one honest global cutoff).
    callback_expire_days: int = int(os.getenv("CALLBACK_EXPIRE_DAYS", "180"))

    def require_anthropic(self) -> None:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )

    def validate_weights(self) -> None:
        total = round(sum(self.weights.values()), 6)
        if total != 1.0:
            raise ValueError(f"Signal weights must sum to 1.0, got {total}")


settings = Settings()
settings.validate_weights()
