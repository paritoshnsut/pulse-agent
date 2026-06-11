-- schema.sql — locked after Session 1 (CLAUDE.md rule #7).
-- No breaking changes without a migration. Single-user build: the multi-tenant
-- dedup machinery is dropped, but table shapes stay faithful to the master design
-- so Party/multi-user can be layered later without a rewrite.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Your social account(s). You can run more than one persona (e.g. a serious
-- analysis handle and a punchy reaction handle), each with its own style DNA.
-- verticals/regions (JSON arrays) scope which articles this persona scores, so
-- a markets handle never wastes a Claude call on an entertainment story.
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    handle      TEXT NOT NULL,
    platform    TEXT NOT NULL DEFAULT 'twitter',
    niche       TEXT,                       -- short free-text niche description
    topics      TEXT,                       -- JSON array of preferred topics
    verticals   TEXT,                       -- JSON array; null/[] = all verticals
    regions     TEXT,                       -- JSON array; null/[] = all regions
    owner_id    TEXT,                       -- supabase user id; NULL = shared
    kind        TEXT NOT NULL DEFAULT 'commentator',  -- commentator | brand | creator | ...
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    UNIQUE(handle, platform)
);

-- Per-account brand kit: the rules a brand's content must obey. Banned words,
-- preferred swaps ("cheap"->"affordable"), required disclaimers, default CTA,
-- compliance notes. Injected into generation AND enforced deterministically.
CREATE TABLE IF NOT EXISTS brand_kit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    banned_words TEXT,                       -- JSON array
    word_swaps   TEXT,                       -- JSON object {bad: good}
    disclaimers  TEXT,                       -- JSON array (appended where relevant)
    cta_text     TEXT,
    cta_url      TEXT,
    website_url  TEXT,
    notes        TEXT,                       -- freeform brand voice / compliance notes
    accent_color    TEXT,                    -- visual identity (VISUALS.md)
    secondary_color TEXT,
    bg_style        TEXT,                    -- dark | light | gradient
    font_family     TEXT,                    -- sans | serif | mono
    watermark_text  TEXT,
    logo_url        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- A repurpose run: one source input expanded into a pack of drafts. Posts
-- carry pack_id so a generated content pack can be shown together.
CREATE TABLE IF NOT EXISTS content_packs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    source_title   TEXT,
    source_url     TEXT,
    source_excerpt TEXT,
    created_at     TEXT NOT NULL
);

-- Raw ingested content from every source. UNIQUE(url) is the dedup key:
-- re-ingesting the same article is a no-op, so the same story is never
-- double-counted across polling cycles or across feeds.
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,            -- 'newsapi' | 'rss' | 'gnews'
    source_name   TEXT,                     -- publication / feed title
    vertical      TEXT,                     -- politics | finance | sports | entertainment
    region        TEXT,                     -- india | us | global
    url           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    description   TEXT,
    content       TEXT,
    author        TEXT,
    published_at  TEXT,                     -- ISO8601 UTC
    fetched_at    TEXT NOT NULL,            -- ISO8601 UTC
    velocity_hint REAL,                     -- 0-10 real velocity if source provides it (reddit/trends); else null
    raw_json      TEXT,                     -- full original payload, for replay
    processed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_articles_processed ON articles(processed);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_vertical ON articles(vertical);

-- Output of the decision/importance scorer. One signal per (article, account).
CREATE TABLE IF NOT EXISTS signals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id         INTEGER NOT NULL REFERENCES articles(id),
    account_id         INTEGER REFERENCES accounts(id),
    score              REAL NOT NULL,       -- 0-10 composite
    tier               TEXT NOT NULL,       -- FIRE | WARM | COOL | SKIP
    velocity           REAL,                -- subscores, each 0-10
    relevance          REAL,
    corroboration      REAL,                -- distinct outlets carrying the story
    reaction_potential REAL,
    memory_leverage    REAL,                -- this account's receipts on the topic
    window_urgency     REAL,
    historical_perf    REAL,
    angle              TEXT,                -- suggested take/angle for a post
    topic              TEXT,                -- kebab-case topic slug for memory filing
    format             TEXT,                -- post format the scorer judged best-fit
    reasoning          TEXT,                -- model's justification
    created_at         TEXT NOT NULL,
    UNIQUE(article_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_tier ON signals(tier);

-- Per-account scoring ledger. Replaces the single articles.processed flag so two
-- personas can each score the same article exactly once (the multi-account fix).
-- articles.processed is kept for back-compat but the loop uses this table.
CREATE TABLE IF NOT EXISTS scored_articles (
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    article_id  INTEGER NOT NULL REFERENCES articles(id),
    created_at  TEXT NOT NULL,
    PRIMARY KEY (account_id, article_id)
);

-- Sources to watch (channels, subreddits, etc). Deduplicated by (kind, ref) so
-- the same YouTube channel tracked for two personas is fetched once per cycle
-- (CLAUDE.md rule #8). vertical/region stamp whatever the source yields.
CREATE TABLE IF NOT EXISTS watch_list (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,              -- youtube_channel | subreddit | trends_geo | wiki
    ref         TEXT NOT NULL,              -- channel_id | subreddit name | geo code | (unused)
    label       TEXT,
    vertical    TEXT,
    region      TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    UNIQUE(kind, ref)
);

-- Per-account voice profile. genome_a = your personal voice (measured + judged),
-- genome_b = crowd wisdom (added later), blend = crowd weight.
CREATE TABLE IF NOT EXISTS style_dna (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    genome_a      TEXT NOT NULL,            -- JSON
    genome_b      TEXT,                     -- JSON, nullable until crowd layer
    blend         REAL NOT NULL DEFAULT 0.4,
    sample_count  INTEGER,                  -- how many posts it was trained on
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(account_id, version)
);

-- Running log of events by topic. Seeded by the monitor; consumed later by the
-- 6-layer context retriever for historical context.
CREATE TABLE IF NOT EXISTS events_timeline (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    source_url  TEXT,
    event_date  TEXT,                       -- ISO8601 UTC
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_topic ON events_timeline(topic);

-- What position each account has taken on each topic. Written after posting;
-- present here so the schema stays locked when the poster lands.
CREATE TABLE IF NOT EXISTS stance_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    topic       TEXT NOT NULL,
    stance      TEXT NOT NULL,
    source_url  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stance_topic ON stance_history(account_id, topic);

-- Generated drafts. content = rendered post (threads: tweets joined by a marker);
-- meta_json = structured form (tweets list, hashtags, all axis scores). status
-- tracks the human-in-the-loop lifecycle, which also feeds approve/reject learning.
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    signal_id     INTEGER REFERENCES signals(id),
    article_id    INTEGER REFERENCES articles(id),
    format        TEXT NOT NULL,            -- hot_take | contradiction | data_story | thread
    content       TEXT NOT NULL,            -- rendered, human-readable
    meta_json     TEXT,                     -- structured: {tweets, hashtags, axes, mechanical}
    persona_score REAL,                     -- composite consistency score 0-100
    needs_review  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'draft',  -- draft|approved|edited|rejected|posted
    pack_id       INTEGER REFERENCES content_packs(id),  -- repurpose pack grouping
    posted_at     TEXT,                     -- when YOU posted it (manual flow)
    posted_url    TEXT,                     -- live URL, if you logged it
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_account ON posts(account_id);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);

-- Engagement snapshots per post. Manual entry for now (/perf on Telegram or
-- review.py --perf); an API reader can append rows later without any change.
-- Multiple snapshots per post are fine — the learner reads the latest.
CREATE TABLE IF NOT EXISTS engagement (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER NOT NULL REFERENCES posts(id),
    likes       INTEGER NOT NULL DEFAULT 0,
    retweets    INTEGER NOT NULL DEFAULT 0,
    replies     INTEGER NOT NULL DEFAULT 0,
    views       INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_engagement_post ON engagement(post_id);

-- Freeform + graded feedback on drafts: the richer signal beyond approve/
-- reject. kind='redo' carries a steer ("more savage") that regenerated the
-- draft; kind='reject_note' a reason. Mined by the learning loop so recurring
-- steers become standing preferences.
CREATE TABLE IF NOT EXISTS draft_feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    post_id     INTEGER REFERENCES posts(id),
    kind        TEXT NOT NULL,              -- redo | reject_note
    note        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_draft_feedback_acct ON draft_feedback(account_id);

-- Every Claude call: which module spent what. The audit trail + the daily
-- budget guard's ledger (pipeline/llm.py).
CREATE TABLE IF NOT EXISTS claude_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    module        TEXT NOT NULL,             -- decision | generator | scorer | ...
    model         TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claude_logs_created ON claude_logs(created_at);

-- Tiny key-value store for process state that must survive restarts
-- (e.g. the Telegram getUpdates offset so commands aren't reprocessed).
CREATE TABLE IF NOT EXISTS kv_store (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- The voice corpus: every writing sample the voice is trained on, kept
-- forever (training is no longer one-shot paste-and-lose). kind='own' are
-- posts the user wrote — they define the voice and feed the measured stats.
-- kind='inspiration' are pieces the user admires (editorials, threads,
-- articles) — they inform qualitative influence, never the measured voice.
-- Engagement columns are optional analytics the user attaches so proven
-- high-performers weigh more when the corpus outgrows the training cap.
CREATE TABLE IF NOT EXISTS voice_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    kind         TEXT NOT NULL DEFAULT 'own',   -- own | inspiration
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,                 -- dedup key (per account)
    origin       TEXT,                          -- manual | article:<id> | url
    source       TEXT,                          -- outlet/author, for diversity cap
    likes        INTEGER,                       -- optional analytics
    retweets     INTEGER,
    replies      INTEGER,
    active       INTEGER NOT NULL DEFAULT 1,
    added_at     TEXT NOT NULL,
    UNIQUE(account_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_voice_samples_acct ON voice_samples(account_id, kind);

-- Corpus suggestions: pieces from the polled stream (articles/editorials/
-- reddit) that look like training material for an account. NEVER auto-added —
-- the user accepts or rejects each one (the human-in-the-loop rule applies to
-- training data exactly as it does to posting).
CREATE TABLE IF NOT EXISTS corpus_suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    article_id  INTEGER NOT NULL REFERENCES articles(id),
    reason      TEXT,                           -- why it was suggested
    status      TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | rejected
    created_at  TEXT NOT NULL,
    UNIQUE(account_id, article_id)
);

-- Predictions this account has staked publicly. Written by the memory updater
-- when a posted item contains a verifiable claim about the future; consumed
-- later by the callback generator ("I called this") when outcomes land.
CREATE TABLE IF NOT EXISTS predictions_tracker (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    post_id     INTEGER REFERENCES posts(id),
    topic       TEXT,
    prediction  TEXT NOT NULL,              -- the exact claim staked
    horizon     TEXT,                       -- rough timeframe ("weeks", "by Q3")
    status      TEXT NOT NULL DEFAULT 'open',   -- open | confirmed | refuted | expired
    outcome     TEXT,                       -- what actually happened
    made_at     TEXT NOT NULL,
    resolved_at TEXT,
    last_checked_at TEXT                    -- callback watcher's cursor: articles
                                            -- fetched before this were already considered
);
CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions_tracker(status);
