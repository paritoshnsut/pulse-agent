# Deferred ideas — parked on purpose, not forgotten

Ideas we evaluated and chose NOT to build yet, with the reason and the trigger
that would make them worth building. Reviewed against external suggestions
(Grok) and our own roadmap. The guiding rule: build factors/features with
**real signal**, refuse vibes-prediction, and don't add infrastructure for
users we don't have yet.

---

## Knowledge Graph memory (the moat upgrade)

**Idea:** elevate `events_timeline` / `stance_history` / `predictions_tracker`
into a lightweight knowledge graph — entity nodes (politicians, policies,
orgs), typed edges ("contradicts", "supports", "caused", "part_of_arc"),
queried for god-tier context ("every time X said Y vs now") and automatic
cross-month narrative threading.

**Why parked:** entity resolution is a genuine swamp — "Modi" / "PM Modi" /
"Narendra Modi" / "the PM" must collapse to one node, and getting it wrong
silently corrupts the graph. Our keyword matching over stance memory, **plus
the stance arc guard** (shipped — flags contradictions with your past
positions), already delivers most of the headline benefit without the swamp.

**Build trigger:** when you have months of data and can point at specific
queries where keyword matching visibly fails (e.g. "Modi" missing posts that
said "the PM"). Then build the entity layer incrementally — start with a
hand-curated alias table for the ~50 entities you actually talk about, not a
general NER + resolution pipeline. Module would be `pipeline/knowledge_graph.py`,
entities extracted on `/posted` (we already make a Claude call there in the
updater — fold extraction into it, no new call).

---

## Proactive narrative intelligence

**Idea:** weekly "narrative opportunity briefing" ("BJP is weak on inflation
this month — here's a 4-post arc to own"); a prediction marketplace surfacing
upcoming events (budget, elections) with pre-emptive stances drafted.

**Why parked:** needs an events/calendar source we don't ingest. "Surface
upcoming events" is hollow without one, and the rest is speculative.

**Build trigger:** add a calendar/events feed (election commission, budget
schedule, an editorial calendar). Then the arc-suggestion layer becomes real.

---

## Multi-modal (vision / audio)

**Idea:** Claude Vision on infographics/memes/debate stills; audio sentiment
layered on transcripts; meme-macro generator.

**Why parked:** no image input path exists (we deliberately don't scrape
images — copyright), YouTube already gives us transcripts, and a meme
generator is a font/template/copyright rabbit hole that Pillow cards already
cover honestly. Low ROI for a text-tweet account.

**Build trigger:** a real need to react to visual content (e.g. you start
covering infographic-heavy sources, or want to react to debate clips frame by
frame). Vision is cheap to add once there's an image to feed it.

---

## Live-stream audio interceptor

**Idea:** `yt-dlp` + chunked Whisper/faster-whisper on live political
speeches, trigger on keyword/sentiment spikes, generate counter-drafts during
the speech (high wow-factor).

**Why parked:** needs paid transcription or a beefy always-on server, and the
value is concentrated in reacting to *speeches* — which matters most in party
mode, not personal copilot.

**Build trigger:** party-mode build, or a server with the headroom. This is the
headline feature of the political-war-room phase.

---

## Opponent mirror / counter-intelligence

**Idea:** shadow personas for rivals (generate what they'd say, pre-build
counters); amplification predictor ("likely to be picked up by bigger
accounts").

**Why parked:** opponent mirror needs opponent-account tracking = paid X read
access (the context retriever's competitor-gap layer is already stubbed for
it). Amplification predictor is the **vibes-prediction we refuse on principle**
— a model can't feel virality from text, and pretending it can erodes trust.

**Build trigger:** opponent mirror when you pay for X read access. Amplification
predictor: never as a "score"; only if real engagement data reveals concrete,
measurable patterns it can key on.

---

## Smaller parked items

- **Dynamic Genome A/B blend per topic/time** — data-starved; revisit after
  months of `/perf` history reveals topic×time performance.
- **Blind-test mode** (old vs new genome A/B) — nice QA ritual, low urgency.
- **Graduated autopilot** (auto-post COOL only) — you explicitly chose manual
  posting; revisit only if approval rate gets boringly high.
- **"Generate 6 variants, auto-post the best"** — we don't auto-post by design
  and have no engagement API to pick a winner; the copilot hook-variants
  feature already covers the human-picks-best case.
- **Regional vernacular engine** (Hindi/district profiles) — Hinglish ratio +
  code-switching register already live in Genome A v2; a full layer is a
  party-mode multiplier.
- **Postgres + Celery + multi-container + Prometheus** — enterprise plumbing
  for two users. CLAUDE.md says SQLite → Postgres *at scale*; move then.
