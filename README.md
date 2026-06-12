# Pulse Agent — Engineering Guide

The autonomous AI content agent for any brand, creator, or commentator. It watches the internet 24/7, scores what matters for your specific niche, drafts posts in your voice, and sends them to your phone for one-tap approval. It never posts to X automatically — you own the publish step.

Started as a political/news commentator tool; now domain-agnostic. The same engine runs a political commentator reacting to breaking news, a finance brand amplifying market data, a sports creator riding viral moments, or a startup building thought leadership. The wedge is the same: an autonomous agent that watches your world, learns your voice and brand, and never lets you face a blank page.

---

## Table of Contents

1. [What this system does](#what-this-system-does)
2. [Data flow end-to-end](#data-flow-end-to-end)
3. [Input sources](#input-sources)
4. [The cost filter (3 layers)](#the-cost-filter-3-layers)
5. [Scoring (decision agent)](#scoring-decision-agent)
6. [Drafting pipeline](#drafting-pipeline)
7. [Safety gates](#safety-gates)
8. [Review and posting](#review-and-posting)
9. [Style DNA system](#style-dna-system)
10. [Scheduled jobs](#scheduled-jobs)
11. [Database schema](#database-schema)
12. [Source file index](#source-file-index)
13. [API and Pulse Studio](#api-and-pulse-studio)
14. [Setup](#setup)
15. [Running locally](#running-locally)
16. [Deploying to Railway](#deploying-to-railway)
17. [Environment variables](#environment-variables)
18. [Test suite](#test-suite)
19. [What's not built yet](#whats-not-built-yet)

---

## What this system does

**One persona loop (the typical case):** The agent ingests ~8,000+ articles/day from 117+ RSS feeds, YouTube channels, Reddit, Google Trends, Wikipedia, and Google News. It filters this down to ~200 articles that are both relevant to your niche and genuinely new stories. It scores each one via Claude, identifies the top FIRE/WARM signals, and drafts platform-native posts in your voice. The drafts arrive on your Telegram within minutes of the event. You tap `/approve` — the post is formatted and you copy it to X.

**Multi-persona:** Every account has its own verticals, topics, style DNA, and brand kit. The scoring and drafting loop runs independently per persona. Ingestion is shared (one RSS fetch feeds all accounts). A politics commentator and a finance brand can run in the same instance — they never see each other's signals.

**Account kinds supported:**
- `commentator` — reacts to news made by others (political analyst, finance commentator, sports writer)
- `creator` — builds original takes and thought leadership (startup founder, industry expert)
- `brand` — amplifies wins, manages brand-safe positioning, auto-suppresses sensitive topics

---

## Data flow end-to-end

```
INGEST                         FILTER                         SCORE & DRAFT
──────                         ──────                         ─────────────

RSS (117 feeds)  ──┐           Layer 1: Stale skip            DecisionAgent.run()
YouTube (keyless)  │           (>3h old → skip free)          ├─ keyword pre-filter
Reddit (OAuth)     ├──► DB ──► Layer 2: Keyword pre-filter    ├─ story dedup gate
Google Trends      │    articles  (zero topic overlap → skip) └─ Claude score (7 dims)
Wikipedia          │
Google News (RSS) ─┘           Layer 3: Story dedup               │
Moments calendar               (already scored this story         ▼
Autonomous discovery           for this account → skip)       signals table

                                          ├─ FIRE / WARM → draft
                                          └─ COOL / SKIP → ideas bank

DRAFT PIPELINE                 SAFETY GATES               REVIEW
──────────────                 ────────────               ──────
ContextRetriever               Grounding check            Telegram bot (/approve)
  6-layer memory package       Stance arc guard           review.py CLI
ContentGenerator               Backlash simulator         Pulse Studio (web UI)
  12 content formats           Persona consistency ≥ 70       │
PersonaConsistencyScorer                                       ▼
  vocab/rhythm/tone/stance/    ─────────────────────►  POST
  emotion axes (0-100)         User copies to X / posts
                               Telegram auto-publish OK
                               Image card attached (Pillow)
                               "AI-assisted" label appended

POST-PUBLISH LOOP
─────────────────
Style learning (approve/reject signal)
Engagement feedback (historical_perf weight)
Prediction callbacks (I called this / I got this wrong)
Daily briefing digest (COOL ideas, outbox nag, timing advice)
```

---

## Input sources

### RSS / NewsAPI (117 feeds, 15 min interval)
Organized into verticals: `politics`, `finance`, `sports`, `entertainment`, `technology`, `marketing`. Each vertical has India + US feeds plus global outlets. The full catalog is in `sources.py`. Active accounts' verticals determine which verticals are actually fetched — a finance brand never pulls sports feeds, a politics commentator never pulls marketing feeds.

Custom per-account feeds are set via `watch_list` rows with `kind=rss_feed` or `kind=news_query` (NewsAPI keyword queries). These ride along with the global feed pull.

### YouTube (15 min interval)
Polls tracked channel IDs via the keyless YouTube RSS feed (`https://www.youtube.com/feeds/videos.xml?channel_id=...`). No API key required. New videos are ingested; transcripts are fetched via the unified transcription layer.

**Transcription layer** (`watch/transcribe.py`) — 4 backends in priority order:
| Backend | Cost | Notes |
|---|---|---|
| `youtube_captions` | Free | Default. Pulls existing CC/auto-captions |
| `assemblyai` | Free (100 hrs/month) | Best for Indian English. Needs `ASSEMBLYAI_API_KEY` |
| `openai` | $0.006/min | Whisper API. Needs `OPENAI_API_KEY` |
| `local` | Free | `faster-whisper` on-device. Needs ≥1GB RAM + `ffmpeg` |

Set `TRANSCRIPTION_BACKEND=assemblyai` in `.env` to upgrade. YouTube URLs try captions first; on failure (or for non-youtube_captions backend), fall back to audio. Non-YouTube URLs go directly to the audio backend.

### Reddit (20 min interval)
Polls tracked subreddits via the Reddit JSON API (keyless locally; OAuth required on Railway to avoid datacenter 403s). The `watch/reddit_auth.py` layer handles OAuth token caching (1hr TTL). Upvote velocity from the API is stored as `velocity_hint` on each article.

Set up a Reddit script-type app at `reddit.com/prefs/apps` and add `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME` to `.env`.

### Google Trends (30 min interval)
Polls trending topics per geo via `pytrends` (keyless). High-velocity trends get high `velocity_hint` scores. Configured per `trends_geo` entries in `watch_list`.

### Wikipedia edit storms (60 min interval)
Polls the Wikipedia recent-changes API. Unusual edit volume on a topic is a reliable early signal for breaking events.

### Google News RSS (30 min interval)
`watch/gnews.py` queries `https://news.google.com/rss/search?q=...` per account topic. Keyless. Covers 500+ outlets with a single query. Deduplicated across accounts (rule #8: same query → one fetch).

### Moments calendar (twice daily)
`watch/moments.py` holds 89 recurring moments (elections, budget dates, national days, IPL, quarterly results, etc.). When a moment enters its planning window, an article-equivalent is created so the drafting pipeline can prepare content proactively.

### Autonomous discovery (45 min interval, optional)
`watch/discover.py` searches YouTube and Reddit for each account's own topic keywords — no manual watch-list entry needed. Set `DISCOVER_ENABLED=true` (default) and configure `DISCOVER_MAX_QUERIES`.

### Instagram (optional)
`watch/instagram.py` pulls your own or benchmark business account's posts via the official Graph API as visual inspiration references. Auto-enabled only when `IG_GRAPH_TOKEN` is set.

---

## The cost filter (3 layers)

Raw daily throughput: ~8,200 articles. Cost per Claude decision call: ~$0.0035 (734 input tokens × $3/MTok + ~83 output tokens × $15/MTok). Without filtering: ~$103/month. With all three layers: ~$24/month.

### Layer 1: Stale skip
Articles older than `STALE_AFTER_MIN` (default 3h) are marked scored and skipped. These are never worth a Claude call — the first-mover window has closed. Cost reduction: ~40%.

### Layer 2: Keyword pre-filter
`_account_topic_words()` builds a `frozenset` of keywords from the account's `topics` JSON array and `niche` string (stopwords removed). Before calling Claude, checks if any article word intersects the topic bag. An article about "Virat Kohli's century" is instantly skipped for an economics account. Empty topic bag → always passes (fail-safe). Cost reduction: ~30%.

### Layer 3: Story dedup gate
`_story_already_scored()` extracts keywords from the article title/description, finds related articles in the DB via `find_articles_fetched_after`, and checks if any signal already exists for this account on those articles. If 4 outlets have covered the same RBI rate hold and the first was already scored as WARM, the other 3 are skipped. One Claude call per story. Cost reduction: ~75% of remaining.

Combined effect: 8,200 → ~230 Claude calls/day → ~$24/month at current throughput.

Set `DAILY_BUDGET_USD=2` to cap daily spend with a Telegram alert when the cap is hit.

---

## Scoring (decision agent)

`pipeline/decision.py` — `DecisionAgent.score_article()`

Scoring is a hybrid: Claude judges the subjective dimensions; Python calculates the deterministic ones.

**7 scoring dimensions (weights sum to 1.0):**

| Dimension | Weight | How computed |
|---|---|---|
| velocity | 0.20 | Exponential recency decay (τ=60min) — first-mover premium |
| relevance | 0.20 | Claude: how closely does this fit the account's niche |
| corroboration | 0.15 | Count of distinct outlets covering the same story in 6h window |
| reaction_potential | 0.15 | Claude: does this account have something strong to say |
| memory_leverage | 0.10 | Past stances/receipts on this topic → account can add context |
| window_urgency | 0.10 | Recency decay (same as velocity, different formulation) |
| historical_perf | 0.10 | Bayesian-smoothed past performance on this topic |

Two multipliers applied after weighted sum:
- **Freshness multiplier** — ≥3 recent posts on topic in 72h window suppresses score (audience fatigue)
- **Brand safety multiplier** — for brand accounts, tragedy/divisive stories are scored down; commentators are unaffected (strength=0)

**Tier thresholds:**
- FIRE (≥8.5): push notification immediately. Draft built. First-mover window.
- WARM (6.5–8.5): in-app card. Telegram push if phone idle 2h+.
- COOL (4.5–6.5): added to ideas bank. Surfaced in morning briefing.
- SKIP (<4.5): logged but not surfaced.

**New story heuristic:** a single-outlet scoop gets `corroboration=5` (neutral), not penalized. A story covered by 5+ outlets gets `corroboration=10`. This prevents suppressing genuine scoops.

---

## Drafting pipeline

`pipeline/generator.py` — `ContentGenerator.generate_checked()`

**12 content formats:**
1. `hot_take` — immediate, punchy, <15min of trigger
2. `contradiction` — "then vs now" (most viral format)
3. `data_story` — leads with a surprising statistic
4. `video_reaction` — transcribes YouTube, reacts to specific claims
5. `thread` — 3-8 tweets connecting event to larger arc
6. `counter_narrative` — the angle nobody is covering
7. `explainer` — "what is X and why it matters"
8. `prediction` — stakes a clear position on what happens next
9. `quote_context` — extracts quotable moment, adds commentary
10. `achievement_amplifier` — party mode, amplifies wins
11. `evergreen` — not news-tied, thought leadership
12. `callback` — "I called this" / "I got this wrong" when prediction resolves

The decision agent picks the best format per signal (stored in `signals.format`). The generator uses that as the format, falling back to `hot_take` if unset.

**6-layer context package** loaded before every draft (pure SQLite, zero API cost):
1. Historical context — related past events from `events_timeline`
2. Stance memory — what this account has said on this topic
3. Contradiction finder — past statements by the story's subject
4. Data enrichment — relevant statistics from the corpus
5. Narrative thread — which larger arc does this event fit
6. Competitor gap — have tracked competitors posted about this

**FIRE drafts get 3 alternative hooks** via `gen.alt_hooks()` — the opening line is where virality is won or lost. Hooks are stored in `posts.meta` as `alt_hooks` and shown in the review UI.

**Content Squeezer** (`pipeline/repurpose.py`) — takes any approved post and generates a full multi-format content pack: LinkedIn long-form, Twitter thread (×2), quote cards (×3), newsletter, video script. Squeezer v2 decomposes the source into typed insight nodes first (one extra Claude call), then generates each draft from a single idea + angle. Set `SQUEEZE_DECOMPOSE=false` for the faster v1 path.

---

## Safety gates

Applied in order, before a draft is saved:

### Grounding check (`pipeline/grounding.py`)
Verifies every factual claim in the draft against the source article the model was given. Flags hallucinated statistics or invented quotes. Enabled by default (`GROUNDING_ENABLED=1`).

### Stance arc guard (`pipeline/integrity.py` — `StanceArcGuard`)
Detects if the draft contradicts the account's established positions. A flip-flop is the cardinal political sin. Reads `stance_history` for the topic; only spends a Claude call if past stances exist. Enabled by default (`ARC_GUARD_ENABLED=1`).

### Backlash simulator (`pipeline/integrity.py` — `RiskSimulator`)
"How could this be screenshotted or misread against you?" Applied only to FIRE signals and inherently spicy formats. Expensive (Claude call), so intentionally narrow. Enabled by default (`RISK_CHECK_ENABLED=1`).

### Persona consistency scorer (`style/scorer.py`)
Scores the draft against the account's style DNA on 5 axes: vocabulary match, sentence rhythm, tone alignment, topic stance consistency, emotional register. Score 0–100. Threshold: 70. Below 70 → regenerate with tighter constraints. Below 60 → flag for human review. The score is stored and shown in the review UI.

---

## Review and posting

**The system never posts to X automatically.** Every X post is reviewed by a human first. This is the permanent design — it removes bot-detection risk and keeps the human in the loop.

Three review paths:

### Telegram copilot (primary)
New drafts are pushed to your phone as they're generated. Commands:
- `/approve <id>` — approve the draft
- `/reject <id>` — reject with implicit feedback
- `/posted <id>` — mark as manually posted (updates engagement tracking)
- `/perf` — recent performance stats
- `/ideas` — COOL ideas bank
- `/brief` — trigger morning briefing now

The Telegram bot also auto-publishes approved posts to a Telegram channel (if `TELEGRAM_CHANNEL_ID` is set) — bots are first-class on Telegram.

### review.py CLI
`python review.py` — shows pending drafts in the terminal with the full post text, signal score, persona score, and alternative hooks. Interactive approve/reject.

### Pulse Studio (web UI)
`api/studio.py` — the browser-based two-zone review interface. Left zone: draft queue with one-click approve/reject/edit. Right zone: signal context (score breakdown, source article, 6-layer context summary). See [API and Pulse Studio](#api-and-pulse-studio).

**Every post includes the `AI_LABEL`** (default: `🤖 AI-assisted`) appended to the final postable text. Set `AI_LABEL=` (empty) in `.env` to disable for manually polished posts.

---

## Style DNA system

Each account has a style DNA profile — the voice fingerprint that makes generated content sound like the account, not like generic AI.

### Genome A — Personal voice
Extracted from the account's own approved posts. Stored in `style_dna`. Fields: sentence length, avg post length, sarcasm level, Hinglish mix ratio, rhetorical question frequency, caps usage, emoji style, hashtag style, signature phrases, preferred topics, things to avoid.

Built via `style/dna.py` — `extract_and_store()`. Run it once on 50+ example posts from the account. Improves as more posts are approved/rejected.

### Genome B — Crowd wisdom
Weekly scrape of the niche's top posts (1000+ likes, past 7 days) via TwitterAPI.io. Claude extracts structural and linguistic patterns. Stored separately and merged with Genome A at blend ratio (default 40% crowd, 60% personal — configurable per account).

`style/crowd.py` — `CrowdWisdomScraper.refresh(account)`. Requires `TWITTER_API_IO_KEY`. Runs weekly.

### Learning loop (`style/learning.py`)
Every approve/reject action is a training signal. After 10+ reviewed drafts (with at least 3 on each side), `ReviewLearner.apply_learning()` runs a Claude contrast analysis: approved drafts vs rejected drafts → what changed? → update style DNA weights. Runs every 6 hours (cheap no-op when below threshold).

### Voice corpus (`style/corpus.py`)
A curated set of the account's own posts (up to 300) plus inspiration posts from other writers (up to 10 total, capped at 50% from any single source to prevent overfit). Used as in-context examples for generation and grounding for the voice importer.

### Voice importer (`style/importer.py`)
Pastes an external writer's posts → Claude extracts the structural/linguistic patterns → imports into the account's corpus as `kind=inspiration`. Capped and source-balanced.

### Brand kit (`style/brand.py`)
Per-account visual identity: colors, fonts, logo, tagline, tone modifiers. Used by the visuals engine and the image card generator. Stored in `brand_kit` table.

---

## Scheduled jobs

`scheduler.py` — run `python scheduler.py` to start the blocking loop.

| Job | Interval | What it does |
|---|---|---|
| `news` | 15 min | RSS ingest across active verticals (117+ feeds) + custom feeds |
| `youtube` | 15 min | New uploads from tracked channels + transcription |
| `reddit` | 20 min | Tracked subreddits (OAuth on Railway, keyless locally) |
| `trends` | 30 min | Google Trends per geo |
| `wikipedia` | 60 min | Edit-storm detection |
| `gnews` | 30 min | Google News RSS per account topic (keyless) |
| `process` | 10 min | Score new articles per account + draft top FIRE/WARM signals |
| `callbacks` | 60 min | Match open predictions against incoming articles → callback drafts |
| `counter` | 120 min | Counter-narrative detector on heavily-covered FIRE stories |
| `crowd` | weekly | Genome B refresh (requires TWITTER_API_IO_KEY) |
| `learn` | 6 h | Approve/reject learning pass (no-op below threshold) |
| `backup` | daily | VACUUM INTO SQLite snapshot, oldest pruned |
| `moments` | 12 h | Calendar events entering planning window |
| `discover` | 45 min | Autonomous topic discovery via YouTube + Reddit search |
| `telegram` | 1 min | Poll for phone commands (/approve, /reject, etc.) |
| `briefing` | daily cron | Morning digest: ideas bank, outbox nag, predictions, timing |

`process` also fires once at boot (no wait for the first interval).

**Concurrency:** 20-thread pool. `coalesce=True` + `max_instances=1` per job — a slow cycle never stacks overlapping runs.

---

## Database schema

`db/schema.sql` — SQLite. Schema is additive-only after initial creation (no breaking changes without a migration in `db/migrations/`).

| Table | Purpose |
|---|---|
| `accounts` | Per-persona settings: handle, niche, topics, verticals, regions, kind (commentator/brand/creator) |
| `articles` | Every ingested article/video/post from all sources |
| `scored_articles` | Per-account scoring ledger — tracks which account has seen which article |
| `signals` | Claude's verdict per (article, account): score, tier, all 7 subscores, angle, topic, format |
| `watch_list` | Sources to monitor: subreddits, YouTube channels, trends geos, RSS feeds, custom queries. Shared across users — one fetch per source per cycle |
| `style_dna` | JSON style profile per account (Genome A + B + blend ratio) |
| `voice_samples` | Account's own posts + inspiration posts for voice corpus |
| `corpus_suggestions` | Candidate posts awaiting review before corpus addition |
| `events_timeline` | Running log of major events by topic (historical context layer) |
| `stance_history` | Every position this account has taken on every topic |
| `predictions_tracker` | Predictions made, with status (open/confirmed/denied/expired) and outcome |
| `posts` | Every generated draft — content, format, persona score, signal_id, status (draft/approved/posted/rejected) |
| `draft_feedback` | Human approve/reject actions with optional notes (learning input) |
| `engagement` | Likes, replies, shares per post over time (engagement feedback loop) |
| `brand_kit` | Visual identity per account: colors, fonts, logo, tone |
| `content_packs` | Content Squeezer output — multi-format packs per input |
| `content_assets` | Individual assets within a content pack |
| `content_insights` | Decomposed insight nodes (Squeezer v2) |
| `visual_refs` | Approved background images + generated backgrounds for card reuse |
| `claude_logs` | Every Claude API call: module, model, tokens, estimated cost, timestamp |
| `kv_store` | Lightweight key-value store for dedup flags, alert sentinels, cached tokens |

**Shared watch list:** If 500 accounts track the same YouTube channel, the channel is fetched once and the article fans out to all account scoring queues. Never fetch the same source twice per cycle.

---

## Source file index

### Entry points
| File | What it does |
|---|---|
| `scheduler.py` | Always-on polling loop — start this in production |
| `api/main.py` | FastAPI web app — combines scheduler + Pulse Studio in one process |
| `review.py` | Terminal-based draft review |
| `run_pipeline.py` | One-shot manual pipeline run (useful for testing) |
| `check_feeds.py` | Diagnostic: test all RSS feeds for availability |

### `pipeline/` — the brain
| File | What it does |
|---|---|
| `monitor.py` | RSS + NewsAPI ingest |
| `decision.py` | Importance scorer (3-layer filter + Claude scoring) |
| `context.py` | 6-layer context retriever (pure SQLite) |
| `generator.py` | Content generation: 12 formats + alt hooks + Content Squeezer |
| `repurpose.py` | Content Squeezer — one input → full multi-format pack |
| `poster.py` | Telegram notifier + Telegram channel publisher |
| `telegram_bot.py` | Phone commander (/approve, /reject, /perf, etc.) |
| `memory.py` | All DB reads and writes |
| `llm.py` | Claude call wrapper: budget guard + cost ledger |
| `grounding.py` | Factual grounding check on drafts |
| `integrity.py` | Stance arc guard + backlash simulator |
| `fatigue.py` | Audience fatigue detector |
| `callbacks.py` | Prediction callback watcher |
| `counter.py` | Counter-narrative detector |
| `briefing.py` | Morning digest generator |
| `timing.py` | Optimal post timing engine |
| `feedback.py` | Engagement feedback utilities |
| `updater.py` | Style DNA updater |
| `visuals.py` | Visual card generation (Satori/Pillow): templates, carousels, charts, decor |
| `charts.py` | Chart-spec extraction (one cached Claude call) for chart_card |
| `blueprint.py` | Visual blueprint extraction: hook + comparison/framework/timeline/journey/process/list |
| `narrative.py` | Narrative carousel arcs: hook → beats → payoff slides |
| `visual_prefs.py` | Visual analytics: per-template approval stats, auto-pick bias |
| `design.py` | AI design agent |
| `evergreen.py` | Evergreen / opinion post generator |

### `watch/` — signal watchers
| File | What it does |
|---|---|
| `youtube.py` | YouTube channel monitor (keyless RSS) |
| `reddit.py` | Reddit subreddit monitor |
| `reddit_auth.py` | Reddit OAuth token manager |
| `transcribe.py` | Unified transcription: 4 backends, auto-routing |
| `trends.py` | Google Trends + Wikipedia edit storms |
| `gnews.py` | Google News RSS per topic |
| `discover.py` | Autonomous topic discovery |
| `moments.py` | Calendar moments watcher |
| `listening.py` | Custom per-account feed specs |
| `twitter.py` | X/Twitter stub (disabled until API access) |
| `instagram.py` | Instagram Graph API watcher |

### `style/` — voice and DNA
| File | What it does |
|---|---|
| `dna.py` | Style DNA extraction + storage + STOPWORDS |
| `scorer.py` | Persona consistency scorer (5 axes, 0-100) |
| `crowd.py` | Crowd wisdom scraper (Genome B) |
| `learning.py` | Approve/reject learning loop |
| `voice.py` | Genome A+B blending: `effective_for(account_id)` |
| `corpus.py` | Voice corpus management |
| `importer.py` | Voice importer (external writer → corpus) |
| `brand.py` | Brand kit management |

### Other
| File | What it does |
|---|---|
| `config.py` | All settings — single source of truth. Import `settings` everywhere |
| `sources.py` | Feed catalog: 117+ RSS feeds organized by vertical + region |
| `moments.py` | 89 calendar moments with dates and planning windows |
| `presets.py` | Content format presets |
| `image/cards.py` | Pillow image card generator (fail-safe fallback) |
| `render/` | Satori render service: `templates.mjs` + `blueprints.mjs` (13 layouts), `charts.mjs` (bar/line), `icons.mjs` (26 icons + decor), `art.mjs` (procedural backgrounds), `ui.mjs` (shared primitives), `server.mjs` (Node service + custom font loading) |
| `api/studio.py` | Pulse Studio web UI backend |

---

## API and Pulse Studio

`api/main.py` — FastAPI app. Combines the background scheduler with the REST API and the Pulse Studio UI in a single process. Start with `uvicorn api.main:app` (or let Railway handle it).

**Auth modes** (auto-selected from env):
- `supabase` — `SUPABASE_URL` + `SUPABASE_JWT_SECRET` set: real per-user accounts via Supabase, JWTs verified locally. Restrict access with `ALLOWED_EMAILS`.
- `password` — only `APP_PASSWORD` set: shared password for a small team.
- `dev` — nothing set: open. Local development only.

**Pulse Studio** (`api/studio.py`) — the browser review interface. Two-zone layout:
- Left: draft queue. Each card shows post content, signal tier, persona score, alternative hooks. One-click approve/reject/edit.
- Right: context panel. Signal score breakdown, source article summary, 6-layer memory context for the signal.

Also available in Studio: Brand Kit editor, Content Squeezer input, Voice Importer, corpus management.

---

## Setup

### Requirements
- Python 3.11+
- `ffmpeg` — only if using `local` transcription backend

### Install
```bash
cd pulse-agent
pip install -r requirements.txt
```

### Configure
```bash
cp .env.example .env
# Edit .env — at minimum, set ANTHROPIC_API_KEY
```

### Initialize the database
```bash
python -c "from pipeline import memory; memory.init_db()"
```

### Seed demo accounts and watch list
```bash
python scheduler.py --seed
```
Edit the `seed()` function in `scheduler.py` to set your own subreddits, YouTube channel IDs, and account niches before relying on it.

### Build Style DNA for an account
```bash
python -c "
from style.dna import extract_and_store
from pipeline import memory
acct = memory.get_account_by_handle('your_handle')
posts = ['post 1 text', 'post 2 text', ...]  # 50+ examples
extract_and_store(acct['id'], posts)
"
```

---

## Running locally

```bash
# Start the full polling loop (Ctrl-C to stop)
python scheduler.py

# Or run every job once (great for testing the wiring)
python scheduler.py --once

# Start the web app (scheduler + Studio + API in one process)
uvicorn api.main:app --reload --port 8000

# Review pending drafts in the terminal
python review.py
```

Check feed availability:
```bash
python check_feeds.py
```

---

## Deploying to Railway

The project runs as a single container on Railway. The API process (`api/main.py`) starts the background scheduler on boot.

### Start command
```
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

### Environment variables to set in Railway
At minimum: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DAILY_BUDGET_USD`.

For Reddit (required on Railway): `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`.

For auth: `APP_PASSWORD` (simple) or the full Supabase set.

### SQLite persistence
The DB file lives at `DB_PATH` (default: `agent.db` in the project root). Railway's ephemeral filesystem resets on deploy — persist the DB by attaching a Railway volume and setting `DB_PATH=/data/agent.db`. Daily backups (`job_backup`) write to `BACKUPS_DIR` (same volume). Keep `BACKUP_KEEP=7` (7 daily snapshots).

---

## Environment variables

All variables have safe defaults — the system runs without most of them. Only `ANTHROPIC_API_KEY` is required for drafting.

```bash
# Required for drafting and scoring
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6        # don't change this

# Cost guard (strongly recommended)
DAILY_BUDGET_USD=2.0                   # 0 = no cap

# Telegram copilot (strongly recommended — this is how you review drafts)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_CHANNEL_ID=...               # optional: auto-publish approved posts here

# News sources (optional — RSS is keyless; these add NewsAPI + GNews breadth)
NEWS_API_KEY=...
GNEWS_API_KEY=...

# Reddit OAuth (required on Railway to avoid datacenter 403s)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USERNAME=...

# Transcription (optional — youtube_captions is default and free)
TRANSCRIPTION_BACKEND=youtube_captions   # or assemblyai | openai | local
ASSEMBLYAI_API_KEY=...
OPENAI_API_KEY=...
WHISPER_MODEL=small                    # tiny | base | small | medium

# Crowd wisdom / Genome B (optional)
TWITTER_API_IO_KEY=...

# Auth (dev mode if nothing set; password mode with APP_PASSWORD; supabase for multi-user)
APP_PASSWORD=...
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_JWT_SECRET=...
ALLOWED_EMAILS=...

# Storage
DB_PATH=agent.db
BACKUPS_DIR=backups
BACKUP_KEEP=7

# Polling intervals (minutes) — defaults shown
POLL_NEWS_MIN=15
POLL_YOUTUBE_MIN=15
POLL_REDDIT_MIN=20
POLL_TRENDS_MIN=30
POLL_WIKIPEDIA_MIN=60
POLL_GNEWS_MIN=30
POLL_PROCESS_MIN=10
POLL_CALLBACKS_MIN=60
POLL_COUNTER_MIN=120
POLL_LEARN_MIN=360
POLL_TELEGRAM_MIN=1
DISCOVER_ENABLED=true
POLL_DISCOVER_MIN=45

# Scoring tuning
STALE_AFTER_MIN=180
PROCESS_BATCH=40
FATIGUE_WINDOW_HOURS=72
FATIGUE_MAX_POSTS=3
CORROBORATION_WINDOW_MIN=360
CORROBORATION_SATURATION=5

# Safety gates (all on by default)
GROUNDING_ENABLED=1
ARC_GUARD_ENABLED=1
RISK_CHECK_ENABLED=1

# Visuals
VISUALS_ENABLED=1
VISUALS_PORT=8787

# Briefing (local time)
BRIEFING_HOUR=8
TZ_OFFSET_MIN=330        # IST = +330
TZ_LABEL=IST
```

---

## Test suite

```bash
pytest                    # run all tests
pytest -x                 # stop at first failure
pytest tests/test_decision.py   # one module
```

**479 tests** across 33 test files. All tests are deterministic — Claude API calls are stubbed via `conftest.StubClient`. Tests hit a real in-memory SQLite DB (via the `temp_db` fixture) for integration-level confidence.

Key test files:
- `test_decision.py` — scoring math, keyword pre-filter, story dedup gate
- `test_generator.py` — all 12 content formats
- `test_scorer.py` — persona consistency scorer
- `test_transcribe.py` — transcription routing across all 4 backends
- `test_callbacks.py` — prediction resolution
- `test_robustness.py` — safety gates (grounding, arc guard, backlash)
- `test_studio.py` — Pulse Studio API endpoints
- `test_multiaccount.py` — per-account isolation

---

## What's not built yet

- **X/Twitter posting API** — `watch/twitter.py` is a stub. Intentional: the copilot flow (Telegram → copy to X) is lower-risk. Wire when you have API access.
- **LinkedIn + Threads posting** — content is generated for these formats; the posting API layer is not built.
- **WhatsApp Business API** — not started.
- **Party mode** — 100-variant generator, worker account manager, war room analytics, opponent monitoring. Designed in CLAUDE.md; not built.
- **Stripe billing** — not started.
- **Per-user data isolation for multi-tenant SaaS** — the auth layer exists; data partitioning for multiple paying customers isn't fully implemented.
- **Fine-tuned model per customer** — the training data moat is being built (style DNA, engagement feedback, voice corpus); the fine-tuning step is a V2 item.
