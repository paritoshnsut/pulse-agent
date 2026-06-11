# Pulse — single-user content agent

Watches the news + social signals on a schedule, decides what's worth reacting
to, drafts posts in *your* voice, and gates them for quality — on its own, every
few minutes. Built for one person (you), multiple personas.

## The loop (what runs on its own)

```
  scheduler.py  ── polls every N min ──┐
                                       ▼
   news 15m · youtube 15m · reddit 20m · trends 30m · wikipedia 60m
        │   each watcher → normalized article (tagged vertical/region,
        │                  + REAL velocity for reddit/trends/wiki)
        ▼
   articles ──(process cycle, 10m)──► per persona, its lanes only:
        │                              decision.py  score → FIRE/WARM/COOL/SKIP
        │                              generator.py draft in that persona's voice
        │                              scorer.py    persona gate (>70), regen if low
        ▼
   posts (draft) ──► pushed to your Telegram the moment they exist
        │
        ▼
   YOU approve (/approve on phone, or review.py) ──► final labeled text
        │                                            + tap-to-compose X link
        ▼                                            (X opens pre-filled,
   YOU press Post on X ──► /posted ──► /perf 12 ...   YOU press Post)
        │
        ▼
   learning loop (6h) ── approve/reject + engagement → voice + historical_perf
   crowd loop (weekly) ── niche's top posts → Genome B (structure, not voice)
```

**Why no auto-posting to X:** automated posting from a personal account is the
fastest way to get flagged as a bot (and the official write API is paid). The
copilot flow keeps a human pressing Post — as far as X can tell, you typed it —
while the agent does everything up to that tap. Telegram channel publishing IS
automated (optional), because Telegram supports bot posting natively.

## What's built

| Layer | File | Status |
|---|---|---|
| **Polling loop / scheduler** | `scheduler.py` | ✅ **new** — APScheduler, per-source intervals |
| **YouTube watch** (keyless upload RSS) | `watch/youtube.py` | ✅ **new** |
| **Reddit watch** (keyless JSON, real velocity) | `watch/reddit.py` | ✅ **new** |
| **Google Trends watch** (keyless RSS) | `watch/trends.py` | ✅ **new** |
| **Wikipedia edit-storm watch** | `watch/trends.py` | ✅ **new** |
| **Twitter watch** (pluggable stub) | `watch/twitter.py` | ✅ **new** — disabled; see below |
| **Multi-account / per-vertical personas** | schema + memory + decision | ✅ **new** |
| News monitor (RSS + NewsAPI) | `pipeline/monitor.py` | ✅ |
| Source catalog (65 feeds) | `sources.py` | ✅ |
| Decision / importance scorer | `pipeline/decision.py` | ✅ (now uses real velocity when present) |
| Style DNA / Genome A | `style/dna.py` | ✅ |
| Content generator | `pipeline/generator.py` | ✅ |
| Persona consistency scorer | `style/scorer.py` | ✅ |
| Review CLI + manual posting flow | `review.py` | ✅ — approve → compose link → --posted → --perf |
| Genome B / crowd wisdom | `style/crowd.py` | ✅ — needs `TWITTER_API_IO_KEY`; no-ops without |
| Approve/reject learning loop | `style/learning.py` | ✅ — updates Genome A + fills `historical_perf` |
| Copilot dispatch (X intent links, AI label, Telegram push) | `pipeline/poster.py` | ✅ |
| Telegram phone commands (/approve /posted /perf …) | `pipeline/telegram_bot.py` | ✅ |
| Engagement feedback (manual /perf → historical_perf) | `style/learning.py` + `engagement` table | ✅ |
| 6-layer context retriever (the memory moat, read side) | `pipeline/context.py` | ✅ — pure SQLite, zero Claude cost |
| Memory updater (stances, timeline, predictions on /posted) | `pipeline/updater.py` | ✅ — 1 Claude call per posted item |
| Callback generator ("I called this" when predictions resolve) | `pipeline/callbacks.py` | ✅ — hourly, free on quiet cycles |
| **All 12 formats** + per-signal format choice | `pipeline/generator.py` + `decision.py` | ✅ |
| **Video reaction** (keyless YouTube transcripts, no Whisper) | `watch/youtube.py` + `video_reaction` format | ✅ **new** |
| **Evergreen** (/evergreen — opinion posts from stance memory) | `pipeline/evergreen.py` | ✅ **new** — on demand, never scheduled |
| Image cards (branded PNG with every approval package) | `image/cards.py` | ✅ — Pillow, deterministic |
| **Audience fatigue detector** (Nth take on a topic isn't drafted) | `pipeline/fatigue.py` | ✅ **new** — pure SQL |
| **Timing engine** (best-window advice from your /perf data) | `pipeline/timing.py` | ✅ **new** — honest defaults until learned |
| **Morning briefing** (ideas bank, outbox, predictions, stats) | `pipeline/briefing.py` | ✅ **new** — daily, zero Claude cost |
| **Counter-narrative detector** (the angle nobody is taking) | `pipeline/counter.py` | ✅ **new** — FIRE + heavy coverage only |
| **Emotion calibration** (learns which emotions land for you) | generator + `style/learning.py` | ✅ **new** |
| **Hook variants on FIRE drafts** (you pick the opener) | `pipeline/generator.py` | ✅ **new** — copilot A/B |
| **Voice corpus** (persistent, daily-fed training set) | `style/corpus.py` + `voice_samples` | ✅ **new** — engagement-weighted selection |
| **Genome A v2** (cadence/punctuation/openers + sentiment depth) | `style/dna.py` | ✅ **new** |
| **Corpus suggestions** (from polled feeds, human-gated) | `style/corpus.py` + web Settings | ✅ **new** — never auto-added |
| Web app — React + Vite + Tailwind | `frontend/` + `api/main.py` | ✅ — FastAPI serves the built app |
| **Supabase auth** (per-user personas, email allowlist) | `api/main.py` | ✅ **new** — JWTs verified locally |
| Single-container deployment | `Dockerfile` (multi-stage) + `docker-compose.yml` | ✅ — one service runs everything |
| Tests | `tests/` | ✅ 206 passing, no keys needed |

## Polling intervals (chosen, env-overridable)

| Source | Interval | Why |
|---|---|---|
| News RSS | 15 min | TAU=60min decay → a fresh story still scores ~7.8/10 on velocity when first seen |
| YouTube | 15 min | keyless channel upload RSS; no quota |
| Reddit | 20 min | hot ranks move on tens-of-min; well inside the ~10 req/min keyless limit |
| Google Trends | 30 min | trending RSS refreshes ~half-hourly; faster gets blocked |
| Wikipedia | 60 min | edit storms build over an hour |
| Process (score+draft) | 10 min | drains the queue in capped batches; your Claude-spend throttle |
| Callbacks (predictions) | 60 min | free unless a new article keyword-matches an open prediction |
| Counter-narrative | 2 h | FIRE + ≥3 related articles only; each story analyzed at most once |
| Briefing | daily (8:00 local) | pure reads, zero Claude cost |
| Learn (approve/reject) | 6 h | free no-op unless new reviews crossed the thresholds; then 1 Claude call |
| Crowd (Genome B) | weekly | CLAUDE.md cadence; ~$0.01/call TwitterAPI.io + 1 Claude call per account |
| Telegram commands | 1 min | getUpdates poll, free; only runs when TELEGRAM_* configured |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add ANTHROPIC_API_KEY
python -m pytest -q         # 80 passing, no keys needed
```

## Run

```bash
python scheduler.py --seed   # create demo personas (markets_take, politics_take) + a starter watch list
# → then build a voice per persona: edit style/dna.py to target each handle's posts and run it
python scheduler.py --once   # run every job ONCE (great first test; watchers need network)
python scheduler.py          # start the always-on loop (Ctrl-C to stop)
python review.py             # see drafts; --approve ID / --reject ID
python review.py --outbox    # approved drafts waiting for you to post
python review.py --posted 12 --url https://x.com/...   # close the loop
python review.py --perf 12 --likes 120 --retweets 30 --replies 4
python -m style.learning     # run the learning pass by hand
python -m style.crowd        # refresh Genome B by hand (needs TWITTER_API_IO_KEY)
```

## The web app (the non-technical-user path)

React + Vite + Tailwind frontend (`frontend/`), served by FastAPI. One process
runs the dashboard, the JSON API, the image cards, AND the full scheduler
(watchers + scorer + drafter + learning loops).

```bash
cd frontend && npm install && npm run build && cd ..   # once (Docker does this for you)
SCHEDULER_IN_APP=1 python3 -m uvicorn api.main:app --port 8080
# open http://localhost:8080
```

Frontend dev loop: `cd frontend && npm run dev` (Vite on :5173, proxies /api
to :8080). A build-free fallback UI lives in `api/static/` and is served when
no `frontend/dist` exists.

Tabs: **Review** (approve/reject, Open-in-X prefilled compose, card download,
"I posted it", engagement entry), **Ideas** (COOL bank + briefing + evergreen
button), **Analytics** (approval/format/emotion rates, learned posting
windows), **Settings** (onboarding, accounts, paste-posts voice training,
watch list).

## Auth — Supabase (recommended) or family password

**Supabase mode** (real per-user accounts; each person sees their own
personas, drafts, analytics):
1. [supabase.com](https://supabase.com) → New project (free tier).
2. Settings → API: copy **Project URL** → `SUPABASE_URL`, **anon key** →
   `SUPABASE_ANON_KEY`, and JWT Settings → **JWT Secret** →
   `SUPABASE_JWT_SECRET`.
3. Set `ALLOWED_EMAILS=you@x.com,brother@x.com` — only these emails can use
   the deployment, even if someone else signs up.
4. (Optional) Authentication → Providers → Email → disable "Confirm email"
   for instant sign-in, or leave it on and confirm via the email link.

Each of you then hits the URL → **Create an account** → sign in. Personas you
create are yours alone; personas created before Supabase mode (owner-less)
are visible to both. The backend verifies Supabase JWTs locally — no extra
latency, no Supabase tables needed; SQLite stays the single datastore.

**Password mode**: leave the Supabase vars empty and set `APP_PASSWORD` — one
shared password, no per-user separation. Good for trying it out.

## Deploy it once, runs forever

**Any VPS / home server (Docker):**
```bash
cp .env.example .env    # fill ANTHROPIC_API_KEY, APP_PASSWORD, TELEGRAM_*
docker compose up -d --build
# http://<server>:8080 — DB + cards persist in the pulse-data volume
```

**Railway (no server to manage, ~$5/mo):**
1. Push this repo to GitHub → railway.app → New Project → Deploy from repo
   (it detects the Dockerfile).
2. Add a **Volume** mounted at `/data` (this is the SQLite DB — without it
   memory resets on every deploy).
3. Set env vars: `ANTHROPIC_API_KEY`, the Supabase four (`SUPABASE_URL`,
   `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`, `ALLOWED_EMAILS`),
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (+ optional keys).
4. Settings → Generate Domain → send your brother the URL. He creates his own
   login, adds his persona, pastes his posts — fully self-serve.

## The phone flow (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)

1. Draft generated → pushed to your private Telegram chat instantly.
2. Reply `/approve 12` → bot sends the branded image card (save it to attach)
   plus the final AI-labeled text + an `x.com/intent/post` link. Tap it:
   X opens with the post pre-filled.
3. **You** press Post. Reply `/posted 12` (URL optional).
4. A day later: `/perf 12 340 80 12` — engagement feeds `historical_perf`,
   so the scorer learns which stories are worth waking you up for.

Also: `/list`, `/show ID`, `/reject ID`, `/outbox`, `/help`. Only your chat id
is obeyed; commands from anyone else are ignored.

`--seed` creates two scoped personas and a starter watch list. **Edit `seed()` in
`scheduler.py`** to add your own YouTube channel IDs and subreddits, and set each
persona's niche. Build a Style DNA per persona (run `style.dna` once per handle)
so the process cycle can draft.

## Twitter — why it's a stub (your call: Trends instead)

Twitter/X read access is now paid ($100–5,000/mo official) and the cheap routes
are ToS-violating, fragile scrapers. Per your instruction, **Google Trends fills
the real-time slot** and Twitter ships as a clean pluggable interface
(`watch/twitter.py`, disabled). To enable later: implement `fetch()` with your
chosen API access, register accounts in `watch_list` (kind='twitter_account'),
set `TWITTER_ENABLED=True` in `scheduler.py`.

## Multi-account (the "all four verticals" answer)

Each persona has `verticals` + `regions`. The process cycle scores only the
articles in a persona's lanes, via a per-account scoring ledger (`scored_articles`)
so two personas can each score a shared story once and never re-score. A markets
handle never spends a Claude call on an entertainment story. This both fixes the
one-voice problem and cuts cost.

## Two principles throughout

**Measure-then-judge.** Countable things computed in Python; only judgment goes to
Claude. Reddit/Trends/Wiki expose **real engagement velocity** (upvotes/hr, traffic,
edit bursts) → the scorer's velocity subscore is now real for those sources
(logged `v*`), not the recency proxy (`v~`) it still uses for plain news.

## Signal scoring — 7 factors + 2 multipliers

Evolved from CLAUDE.md's 5-factor model. The two additions are deterministic
and free (zero extra Claude calls):

```
velocity        20%  real where measurable; recency proxy for plain news
relevance       20%  Claude: fit to the niche
corroboration   15%  distinct outlets carrying the story across our own feeds
                     (5 outlets → 10/10; fresh scoops score neutral until
                     they've had time to echo)
reaction_pot.   15%  Claude: does this account have a distinctive take
memory_leverage 10%  the moat factor: past stances (2.5 each, cap 5) + an open
                     prediction this story may resolve (4) + timeline history
                     (0.5/event, cap 1) — receipts make a story YOURS
window_urgency  10%  first-mover window left (recency decay)
historical_perf 10%  topic-level ("rbi-rate-policy") → vertical → overall,
                     Bayesian-shrunk toward 5.0
× freshness     0.6–1.0  fatigue folded into scoring: the 4th take on one topic
                         in 72h ranks down BEFORE Claude drafting money is spent
× source weight 0.8–1.0  wire/national full; aggregators/social-derived less
```

Deliberate consequence: a perfect solo-source story with no receipts tops out
in WARM (~7.75). FIRE is reserved for stories that are structurally big
(corroborated) or that this account is uniquely positioned to win (receipts).
Deliberately NOT added: predicted-virality vibes, controversy scores — only
factors with real signal.

**Honest placeholders.** `historical_perf` starts at a neutral 5.0 and only moves
as your approve/reject history accumulates (Bayesian shrinkage — one approval is
not a 10). Stale articles (older than `STALE_AFTER_MIN`, default 3h) are skipped
at scoring so the first run doesn't burn calls on old news.

## The voice corpus (training is no longer one-shot)

Every writing sample lives forever in `voice_samples`; feed it daily and hit
**Retrain voice from corpus** (web Settings, or `python -m style.corpus
--account me --retrain`). Two kinds, deliberately separated:

* **own** — posts you wrote, one per line. These define the voice: every
  measured statistic comes from these only. Optionally end a line with
  `| likes retweets replies` — when the corpus outgrows the training cap
  (`CORPUS_MAX_OWN`, 300), samples with measured engagement are kept first,
  best performers ranked top, so your proven winners never age out of the
  training set. The rest fills with the most recent.
* **inspiration** — editorials/threads/articles you admire, each stored as one
  whole piece. Claude distills them into `genome_a["influences"]`
  (admired patterns + themes) as directional pull — an admired 1200-word
  editorial never contaminates the arithmetic of your 180-char tweet voice.

**Genome A v2** now captures far more than the CLAUDE.md sketch. Measured
(deterministic, fingerprint-grade): words/sentence, short-fragment rate,
em-dash/ellipsis/exclamation/quote rates, opener habits (number / question /
conjunction / lowercase starts), share of posts with data. Judged (deep
sentiment analysis): emotional palette (ranked), sentiment baseline,
rhetorical devices actually used, argument structure (open → develop → land),
register + code-switching. All of it renders into the generation prompt and
the persona gate.

**Corpus suggestions, human-gated:** the watchers already pull editorials and
articles all day; pieces matching your topics + stance history are filed as
pending suggestions (free, deterministic, max `CORPUS_SUGGEST_MAX`/run),
surfaced in web Settings and counted in the morning briefing. Accept → enters
the corpus as inspiration; reject → never shown again. Nothing trains the
voice without your explicit yes — the human-in-the-loop rule applies to
training data exactly as it does to posting.

## The learning layer (how it self-improves before posting exists)

Two loops, both consuming signals already captured:

**Approve/reject → Genome A** (`style/learning.py`). Every `review.py` decision
is a training example. Once `LEARN_MIN_REVIEWED` (10) drafts are actioned, the
loop measures what separates the piles (per-format approval rates, length,
persona-score deltas — exact, in Python), and with ≥3 examples on each side asks
Claude WHY the rejected ones lost, phrased as style rules. Those land in
`things_to_avoid` + a `learned_preferences` block in a NEW style_dna version —
the generator picks them up on its next draft. Idempotent: no new reviews, no
version churn, no Claude spend. The same history fills the decision agent's
`historical_perf` subscore, per-vertical where evidence exists.

**Crowd wisdom → Genome B** (`style/crowd.py`). Weekly, scrapes the niche's top
posts (1000+ likes, via TwitterAPI.io) and distills the structural patterns
being rewarded — hooks, shapes, emotional registers. `effective_genome()` folds
them into the generation prompt at the `blend` weight (default 0.4) as
**structure only — voice identity stays 100% Genome A**. Without
`TWITTER_API_IO_KEY` the whole layer no-ops cleanly.

## The memory moat (context retriever + updater)

Every FIRE/WARM story is filed into `events_timeline` with a topic slug (free —
the decision agent's existing Claude call now also returns the slug). Every
post you actually publish gets one archivist call that files your **stance**
into `stance_history` and any **verifiable prediction** into
`predictions_tracker`. Before each draft, `pipeline/context.py` loads — with
zero Claude calls, pure SQLite keyword match — the six layers: past events on
the topic, positions you've already taken, contradiction material, related
coverage, the narrative arc, and competitor gap (placeholder; needs paid X
access). The generator is instructed to stay consistent with past stances,
reference the arc, and never invent memory beyond what's listed. Cold start is
honestly cold: with an empty memory, drafts are generated exactly as before;
after a month, they remember everything. Backfill old posts anytime with
`python -m pipeline.updater`.

**Callbacks** close the loop (`pipeline/callbacks.py`, hourly): every open
prediction is keyword-matched against newly ingested articles (free); when ≥2
keywords overlap, one strict Claude call verifies whether the story actually
resolves the claim — "unresolved" is the expected answer. On a hit, the
prediction is marked confirmed/refuted and a `callback` draft lands in your
normal review lane: "I called this" on a win, "I got this wrong" on a miss
(owning misses is part of the brand). A per-prediction cursor means each
article is judged at most once, and predictions expire after
`CALLBACK_EXPIRE_DAYS` (180) so the watcher never grinds on dead claims.
Run by hand: `python -m pipeline.callbacks`.

## The intelligence layer (CLAUDE.md's 12, scored honestly)

Built: timing engine (#1), emotion calibration (#4), counter-narrative (#5),
thread-vs-single via per-signal format choice (#6), fatigue detector (#7),
persona scorer (#10), hook variants (#3, copilot version: you pick, no posting
algorithm), plus trend velocity (#2) partially — real velocity from
Reddit/Trends/Wiki, recency proxy for plain news.

Blocked on paid API access: reply intelligence (#8), cross-platform
amplification (#9), competitor gap (#11), growth forecaster (#12 — needs
follower history that only an API can read).

## Not built yet (roadmap)

1. **Automated engagement reads** — `/perf` is manual entry; an X API reader
   (when worth paying for) would append to the same `engagement` table.
2. **X API posting** — deliberately skipped (bot-flagging risk + paid API).
   If ever wanted, `post_to_x()` lands in `pipeline/poster.py`; the
   draft→approved→posted lifecycle already supports it unchanged.
3. **Blocked intelligence features** (above) + **YouTube view-velocity** +
   **Twitter watch** — paid/keyed API access. (Transcription is NOT blocked
   anymore: YouTube's own captions are fetched keylessly; Whisper only ever
   mattered for videos without captions.)
4. **Productization** — SaaS layer (Sessions 17-26), Party mode (27-32),
   multi-platform (LinkedIn/Threads/WhatsApp). Deferred until selling.

All 12 CLAUDE.md formats now exist. The four "special" ones are produced by
their own triggers, not the per-signal chooser: callback (predictions watcher),
counter_narrative (the detector), video_reaction (auto for YouTube uploads
with a transcript), evergreen (/evergreen on Telegram or
`python -m pipeline.evergreen` — picks your most-recurring stance topic,
with a 14-day repeat guard).

Schema locked (rule #7); changes are additive via the auto-migration in `memory.init_db`.
