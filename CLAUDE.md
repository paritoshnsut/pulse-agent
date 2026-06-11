# CLAUDE.md — Pulse build spec & status (living document)

> This is the **updated, annotated** version of the original product brief.
> The original vision doc lives separately at `~/Downloads/CLAUDE.md` and is
> left untouched. This file maps every planned item — from the original spec
> AND the suggestions we evaluated from Grok — to its real status, so nothing
> is lost and nothing is overclaimed.
>
> Legend: ✅ built · 🟡 partial · ⏸ deferred on purpose (see `DEFERRED.md`) ·
> ❌ blocked (needs paid API / not started) · 🚫 deliberately skipped
>
> Snapshot: **290 tests passing**, single-container deploy (FastAPI + React +
> always-on agent), live on GitHub (`paritoshnsut/pulse-agent`). Model:
> `claude-sonnet-4-6`, every call routed through one cost-tracked wrapper.

---

## What Pulse is

An autonomous content **copilot for any account that needs to post** — a
person, a brand, a creator, a business. It watches *your* world 24/7 (news,
social, or your own business inputs), scores what's worth saying, drafts in
*your* trained voice and brand, guards the draft (facts, stance consistency,
backlash, brand compliance), and hands you a one-tap manual post. It learns
from every approve/reject/edit/steer + engagement number you feed it.

> **Positioning (v1 → marketing tool):** politics is just one vertical of
> marketing. The engine is domain-agnostic — the wedge is the *autonomous,
> always-watching, learns-your-voice agent* ("you never face a blank page"),
> which is identical for a crypto founder, a D2C brand, a SaaS, or a
> politician. "Marketing-ready v1" (de-politicize + Content Squeezer + Brand
> Kit) ships that pivot. Multi-platform APIs, visual generation, agency mode,
> and triggers are the planned next phases — see the roadmap below + `DEFERRED.md`.

One deliberate departure from the original brief: **no auto-posting to X.**
Automated posting from a personal account is the fastest way to get flagged,
and the write API is paid. The copilot flow keeps a human pressing Post; the
agent does everything up to that tap. (Telegram channel publishing IS
automated — Telegram supports bot posting natively.)

---

## The 4 content systems (original spec)

| System | Status | Notes |
|---|---|---|
| **1. Input Processor** | 🟡 | News/RSS/NewsAPI, YouTube (auto-transcribed, keyless), Reddit, Trends, Wikipedia → normalized articles. Paste-text via corpus. PDF/image/audio input ⏸. |
| **2. Context Retriever (6 layers)** | ✅ (5/6) | historical events, your stances, contradiction material, related coverage, narrative arc — all live, pure-SQLite, zero Claude cost. Competitor gap = layer 6, stubbed (needs paid X). |
| **3. Content Generator** | ✅ | All 12 formats (see below). Per-signal format choice by the decision agent. |
| **4. Memory Updater** | ✅ | On `/posted`: files stance → `stance_history`, event → `events_timeline`, predictions → `predictions_tracker`. One Claude call per posted item. |

---

## The 12 content formats — ALL built ✅

`hot_take`, `contradiction`, `data_story`, `thread`, `callback`, `explainer`,
`prediction`, `quote_context`, `counter_narrative`, `video_reaction`,
`achievement`, `evergreen`.

The decision agent picks among the 8 reactive formats per signal; the 4
special ones have their own triggers: **callback** (predictions watcher),
**counter_narrative** (the detector), **video_reaction** (auto for YouTube
uploads with a fetched transcript), **evergreen** (on-demand, from stance
memory). Video transcription is keyless (YouTube captions) — Whisper was never
needed.

---

## The Auto-Watch agent (always-on)

| Source | Status | Interval | Notes |
|---|---|---|---|
| News RSS (65 feeds, 4 verticals, IN/US) | ✅ | 15 min | per-source weighting (wire/national vs aggregator) |
| YouTube (channel upload RSS + transcripts) | ✅ | 15 min | keyless; transcript unlocks `video_reaction` |
| Reddit (real upvote velocity) | ✅ | 20 min | keyless JSON |
| Google Trends | ✅ | 30 min | keyless RSS, real traffic velocity |
| Wikipedia edit-storms | ✅ | 60 min | keyless |
| Twitter/X read | ❌ | — | pluggable stub; paid API ($100–5,000/mo). Trends fills the slot. |
| YouTube view-velocity | ❌ | — | needs YouTube Data API quota |

### Signal scoring — UPGRADED from 5 factors to **7 + 2 multipliers** ✅

The original 5-factor model, evolved (both additions deterministic, zero extra
Claude calls):

```
velocity        20%   real where measurable; recency proxy for plain news
relevance       20%   Claude: fit to the niche
corroboration   15%   NEW — distinct outlets carrying the story across our feeds
reaction_pot.   15%   Claude: does this account have a distinctive take
memory_leverage 10%   NEW — your receipts on the topic (stances/predictions/timeline)
window_urgency  10%   first-mover window left
historical_perf 10%   topic-level → vertical → overall, Bayesian-shrunk
× freshness     0.6–1.0   fatigue folded into scoring (saturated topics rank down)
× source weight 0.8–1.0   junk-source insurance
```

Consequence by design: a solo-source story with no receipts tops out at WARM
(~7.75). FIRE is reserved for stories that are structurally big (corroborated)
or that *you* are positioned to win (receipts). Tiers: FIRE 8.5+ · WARM 6.5+ ·
COOL 4.5+ · SKIP below.

### Operating modes

- **Copilot** (human posts every item) — ✅ the shipped default.
- **Hybrid / Autopilot** (auto-post COOL/WARM) — ⏸ deliberately not built; you
  chose manual posting. Revisit only if approval rate gets boringly high.

---

## Style DNA system

| Piece | Status | Notes |
|---|---|---|
| Genome A — personal voice | ✅ **v2** | far deeper than the original sketch (below) |
| Genome B — crowd wisdom | ✅ | weekly TwitterAPI.io scrape; structure-only, voice stays A; no-ops without key |
| Auto-learning feedback loop | ✅ | approve/reject + engagement + freeform steers → genome + historical_perf |
| Persona consistency scorer (rule #9 gate) | ✅ | >70 gate, regenerate-with-feedback |
| Emotion calibration | ✅ | tags emotion per draft, learns which registers land |

### Genome A v2 — what we measure & judge now

**Measured (deterministic, fingerprint-grade):** avg length, emoji/caps/
hashtag profile, Hinglish ratio, **words-per-sentence, short-fragment rate,
em-dash/ellipsis/exclamation/quote rates, opener habits (number/question/
conjunction/lowercase starts), data-rate.**

**Judged (deep, by Claude):** sentence style, sarcasm, tone, signature phrases,
topics, things-to-avoid, **emotional palette (ranked), sentiment baseline,
rhetorical devices, argument structure (open→develop→land), register +
code-switching,** and `influences` distilled from admired writing.

### Voice corpus — training is a living flywheel ✅ (Grok-aligned, our build)

- **Persistent corpus** (`voice_samples`): every sample kept forever; retrain
  over the full set. Feed 200–300/day — the intended usage.
- **own vs inspiration** strictly separated: measured stats come from *your*
  posts only; admired editorials inform `influences`, never the arithmetic.
- **Engagement-weighted selection:** `| likes rts replies` per line; proven
  winners stay in the training set as the corpus outgrows the cap.
- **Corpus suggestions (human-gated):** pieces from the polled feeds matching
  your topics/stances are surfaced in Settings + briefing; nothing trains the
  voice without your explicit accept.
- **Flywheel:** a posted draft + its `/perf` numbers auto-file into the corpus
  (`approved_draft`) — the system trains on its own audience-validated output.

---

## Intelligence features (the 12)

| # | Feature | Status |
|---|---|---|
| 1 | Optimal post-timing engine | ✅ advice in the approval package; honest defaults until 8+ posts |
| 2 | Trend velocity detector | 🟡 real for Reddit/Trends/Wiki; recency proxy for plain news |
| 3 | Hook A/B testing | ✅ copilot version — variants surfaced, *you* pick (no posting algorithm) |
| 4 | Emotion calibration | ✅ |
| 5 | Counter-narrative detector | ✅ |
| 6 | Thread vs single predictor | ✅ via per-signal format choice |
| 7 | Audience fatigue detector | ✅ also folded into the score as a multiplier |
| 8 | Reply intelligence | ❌ needs paid X read |
| 9 | Cross-platform viral amplification | ❌ needs multi-platform + analytics |
| 10 | Persona consistency scorer | ✅ |
| 11 | Competitor gap analysis | ❌ needs paid X read (context layer 6 stubbed) |
| 12 | Growth trajectory forecaster | ❌ needs follower history (paid API) |

---

## Platform distribution

| Platform | Status | Notes |
|---|---|---|
| X / Twitter | ✅ | manual via `x.com/intent/post` pre-filled compose (no API write) |
| Telegram | ✅ | draft push + full command cockpit + optional channel auto-publish |
| **Branded visuals (Satori)** | ✅ | template-based PNGs (quote/stat/insight) with brand kit colors/fonts; Pillow card is the fail-safe; see `VISUALS.md` |
| LinkedIn / Threads / WhatsApp | ⏸ | deferred until selling / party mode |

---

## Robustness & integrity layer (added beyond original spec — Grok-prompted, honest builds)

| Feature | Status | Notes |
|---|---|---|
| **Grounding shield** | ✅ | flags draft claims unsupported by the source material; honest scope = groundedness, not truth (no vector DB pretending to be an oracle) |
| **Stance arc guard** | ✅ | flags drafts that *reverse* your past positions — flip-flop protection; free at cold start |
| **Backlash simulator** | ✅ | red-teams FIRE/spicy drafts for how they could be turned against you |
| **Redo-with-steer** | ✅ | "make it more savage" rewrites in place; works for every format |
| **Reject reasons + steer learning** | ✅ | freeform feedback recorded + fed into the learning loop's next pass |
| **Cost ledger + daily budget guard** | ✅ | every Claude call logged (`claude_logs`); hard stop at `DAILY_BUDGET_USD`, one alert/day |
| **Daily backups** | ✅ | `VACUUM INTO` snapshots, rotated; the whole moat is one SQLite file |
| **Draft staleness warnings** | ✅ | "the moment may have passed" past 24h |

All guards **flag, never block** (you review everything) and are **fail-safe**
(a broken check lets the draft through, logged).

### Operational resilience (Gemini-prompted hardening)

| Hardening | Status | Notes |
|---|---|---|
| SQLite `busy_timeout` + `synchronous=NORMAL` | ✅ | WAL already persistent; the timeout queues colliding writes instead of `database is locked` under the single-container concurrency |
| Parallel RSS fetch (bounded thread pool) | ✅ | 65 feeds fetched concurrently — seconds, not minutes; failures isolated per feed |
| Scheduler executor sizing + misfire grace | ✅ | 20-worker pool so a 45s Claude block never starves the watchers; missed ticks within 5 min still run |
| Corpus source-diversity cap | ✅ | no single outlet/author exceeds `CORPUS_SOURCE_CAP_FRACTION` (0.5) of the inspiration set — anti-overfit on `influences` |
| Full async (`aiohttp`) rewrite of all watchers | ⏸ | premature for two users; APScheduler already thread-isolates and the SDK releases the GIL on I/O. See `DEFERRED.md`. |

---

## SaaS / productization layer

| Piece | Status | Notes |
|---|---|---|
| React + Vite + Tailwind dashboard | ✅ | Review / Ideas / Analytics / Settings |
| FastAPI backend | ✅ | one process serves UI + API + cards + the scheduler |
| Posts feed + manual-post flow UI | ✅ | approve → Open-in-X → "I posted it" → engagement entry |
| Analytics dashboard | ✅ | approval/format/emotion rates, learned windows, spend |
| Style DNA / corpus viewer + editor | ✅ | paste, retrain, suggestion review |
| Supabase auth (per-user personas, email allowlist) | ✅ | JWTs verified locally; SQLite stays the only datastore |
| Onboarding | ✅ | guided 2-step in Settings |
| Single-container deploy (Docker + Railway) | ✅ | `/data` volume = DB + cards + backups |
| Stripe billing | 🚫 | skipped on purpose — personal/family use |
| OAuth platform connections | ⏸ | not needed for the manual flow |

---

## Marketing pivot — "content tool for everyone"

The vision widened from political commentator to **a content/marketing engine
for any brand, creator, or business.** Shipped in v1; the rest is the roadmap.

| Feature | Status | Notes |
|---|---|---|
| **De-politicized engine** | ✅ | decision agent reframed for person/brand/creator; account `kind`; vertical **presets** (SaaS, D2C, creator, finance, fitness, local, agency, political) prefill onboarding |
| **Content Squeezer (repurpose)** | ✅ | one input (blog/podcast/launch/newsletter; paste or URL) → a pack of platform-shaped drafts (LinkedIn post, threads, standalone insights, newsletter, video script). Zero polling setup; the blank-page killer. |
| **Text Brand Kit** | ✅ | banned words, preferred swaps ("cheap"→"affordable"), disclaimers, default CTA, brand notes — injected into generation AND enforced deterministically; off-brand drafts flagged. Applies on every generation path via `style/voice.py`. |
| Multi-platform native output + scheduling | ⏸ | LinkedIn/Instagram/Threads APIs (brand pages permit scheduled posting — unlike personal X). Phase 2. |
| Trigger-to-Content (webhooks: GitHub/Shopify/Stripe/calendar) | ⏸ | generalizes the watch layer to business events. Phase 2. |
| Agency mode + magic-link client approvals | ⏸ | the lucrative multi-seat segment. Phase 3. |
| Content calendar / campaign planner | ⏸ | cadence + themes + "fill my week". Phase 3. |
| **Visual generation V1 (Satori)** | ✅ | branded PNGs on every approval: quote/stat/insight templates, brand colors/fonts/watermark, persistent localhost Node renderer (no browser), Pillow fail-safe. Full plan + phases in `VISUALS.md`. |
| Visuals V1.5 (carousel, logo embed, preview) + V2 (AI-imagery design agent) | ⏸ | tracked step-by-step in `VISUALS.md` |
| Social listening (tamed lead-gen — copilot reply, never auto-spam) | ⏸ | needs paid social read; auto-reply-to-strangers deliberately refused. |

## Party mode (enterprise) — all ⏸ deferred

100-variant generator, worker account manager, war-room analytics, opponent
monitoring/counter-content, narrative consistency at scale. Park until the
personal product is proven and there's a pitch on the calendar. Schema shapes
already leave room.

---

## Deferred / not-doing (full reasoning in `DEFERRED.md`)

⏸ **Knowledge graph** (entity nodes + typed edges) — the moat upgrade, but
entity resolution ("Modi"/"PM Modi"/"the PM") is a swamp; the stance arc guard
+ keyword memory already deliver most of the benefit. Build trigger:
months of data + a hand-curated alias table for the ~50 entities you actually
discuss.
⏸ Proactive narrative briefing / prediction marketplace — needs an events
calendar feed we don't ingest.
⏸ Multi-modal (vision/audio/meme generator) — no image input path; low ROI for
text tweets.
⏸ Live-stream audio interceptor — paid transcription + always-on server; a
party-mode headline feature.
⏸ Opponent mirror / regional vernacular / Postgres+Celery+Prometheus — paid
API or enterprise-scale, premature for two users.
🚫 Amplification predictor ("likely to go viral") — the vibes-prediction we
refuse on principle; a model can't feel virality from text.

---

## Rules still in force (from the original brief)

1. Every Claude call uses `claude-sonnet-4-6` (centralized in `config.py`, now
   also routed through the cost-tracked wrapper).
2. All secrets in `.env`, never hardcoded.
3. Schema is additive-only — migrations via the auto-migration in
   `memory.init_db` (rule #7 honoured across every new table).
4. Every post passes the persona gate (>70) before it reaches you.
5. Every post carries an "AI-assisted" label (configurable).
6. Measure-then-judge everywhere: countable things in Python, only judgment to
   Claude.
7. Human-in-the-loop is sacred — applies to posting AND to training data
   (corpus suggestions are accept/reject, never auto-added).

---

## Repo map (where things live)

```
pipeline/   monitor decision context generator scorer poster telegram_bot
            updater callbacks counter evergreen fatigue timing briefing
            grounding integrity feedback llm repurpose memory
style/      dna corpus crowd learning scorer brand voice
watch/      youtube reddit trends twitter(stub)
image/      cards
presets.py  onboarding starter packs            sources.py  65-feed catalog
api/        main.py (+ static fallback)         frontend/  React app
db/         schema.sql                          tests/     290 tests
DEFERRED.md  parked ideas + triggers           README.md  user/run/deploy guide
```

*Last updated: integrity layer (arc guard, backlash sim, redo-with-steer) +
this status doc. Keep this file current as the source of truth for "what's
actually built."*
