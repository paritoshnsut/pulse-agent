# Pulse — Product Overview

> What it does, what problem it solves, why it's powerful, and how a user actually experiences it.

---

## The problem

Every brand, creator, and commentator needs to show up online — consistently, fast, and in their own voice. The reality:

- **Blank page problem.** You know you need to post. You open a new tab. Nothing comes. An hour later you close it.
- **Speed problem.** Breaking news happens. The first 15 minutes are worth 8x the engagement of hour 2. By the time you see the story, form a take, write it, and post — the moment is gone.
- **Volume problem.** Agencies manage 10-50 brand accounts. Each account needs fresh, on-brand content daily across 4-6 platforms. That's not a content problem, it's a manufacturing problem.
- **Voice problem.** When multiple people write for the same account, it never sounds like one person. The brand voice drifts post by post.
- **Consistency problem.** Posting works on momentum. You post 3x/week, you build. You miss a week, the algorithm punishes you for a month.

Scheduling tools (Buffer, Hootsuite) solve the *when*. AI writing tools (ChatGPT, Jasper) solve the *blank page*. Neither solves the *what to post*, the *watch the world for you*, or the *sounds exactly like you* problems. Pulse solves all five.

---

## What Pulse does

Pulse is an autonomous content agent. It watches your world — news feeds, YouTube, Reddit, Google Trends, industry sources — 24/7. The moment something relevant happens, it builds a fully drafted post in your voice and sends it to your phone. You tap approve. You copy it to X. That's it.

Three modes for different operators:

- **Copilot** — you approve every post before it goes anywhere. Full control, zero blank pages.
- **Hybrid** — high-urgency posts wait for your approval; low-urgency ones auto-post to Telegram (where bots are first-class). You get a morning digest of what went out.
- **Autopilot** — everything publishes. You get a daily summary. Hands-off.

---

## The 5 core capabilities

### 1. Real-time signal detection
Pulse watches 15 source types simultaneously:
- 117+ RSS feeds organized by vertical (politics, finance, sports, entertainment, tech, marketing)
- YouTube channels (keyless — no API key needed)
- Reddit subreddits (live upvote velocity)
- Google Trends per geography
- Wikipedia edit storms (early signal for breaking events)
- Google News (500+ outlets via a single keyless query)
- Moments calendar (89 recurring events — budget dates, IPL, elections, quarterly results)
- Autonomous discovery — searches YouTube and Reddit for your own topics without manual setup

Every signal is scored on 7 dimensions: velocity, relevance, corroboration (how many outlets are covering it), reaction potential, memory leverage (do you have past receipts on this topic), window urgency, and historical performance. The result: a ranked queue where FIRE signals demand immediate action and COOL signals are banked for later.

**The number that matters:** 0–15 minutes after a story breaks, posts get 8x more shares. Pulse detects and nudges under 8 minutes. Most accounts miss this window every time.

### 2. Content generation in your voice
Pulse generates 12 content formats, not just "write a tweet":

| Format | What it is |
|---|---|
| Hot take | Punchy reaction, <15min from trigger |
| Contradiction | "Then vs now" — most viral format in politics and markets |
| Data story | Leads with a surprising number |
| Video reaction | Transcribes YouTube, reacts to specific claims the speaker made |
| Thread | 3-8 connected posts building a narrative |
| Counter-narrative | The angle nobody else is covering |
| Explainer | "What is X and why it matters" |
| Prediction | Stakes a clear position on what happens next |
| Quote + context | Pulls a quotable moment, adds your commentary |
| Achievement amplifier | Amplifies wins (product launches, milestones, case studies) |
| Evergreen / opinion | Not tied to news, pure thought leadership |
| Callback | When a prediction you made resolves — "I called this" |

The decision agent picks the right format per story. FIRE signals get 3 alternative hook options so you can pick the strongest opening line.

Every draft is grounded in the source material (no hallucinated facts), checked against your past stances (no flip-flops), and scored for voice consistency before it ever reaches you. Below 70/100 consistency score: it regenerates automatically.

### 3. Style DNA — the voice that actually sounds like you
This is the hardest problem in content AI. Pulse solves it with a two-genome system:

**Genome A — your personal voice** is extracted from 50+ of your own posts. It captures: sentence length, sarcasm level, Hinglish/language mix, rhetorical question frequency, emoji habits, hashtag style, signature phrases, topics you prefer, things you never say. Every generation uses this as the voice instruction.

**Genome B — crowd wisdom** is a weekly scrape of the top 50 posts (1000+ likes) in your niche. Claude extracts what structural and linguistic patterns are performing. Merged with Genome A at a configurable blend (default: 60% your voice, 40% what works in your niche). This is why Pulse drafts feel native — they follow both your voice and the current platform vernacular.

**Auto-learning:** Every approve/reject you give is a training signal. After 10+ reviews, the system runs a contrast analysis — approved vs rejected — and updates your style DNA accordingly. The longer you use it, the more it sounds exactly like you.

### 4. Brand Kit — for accounts that have compliance rules
Agencies and brands need more than voice. They have rules:

- **Banned words** — "cheap" is not in your vocabulary. "disruptive" makes you sound like 2015. Pulse enforces these at generation AND deterministically post-generation (it doesn't just hope the model remembered).
- **Word swaps** — "cheap" → "affordable", "problems" → "challenges". Case-aware replacement applied to every draft.
- **Disclaimers** — "not financial advice", "past performance is not indicative of future results". Applied when contextually relevant.
- **Default CTA** — every post that fits gets your call to action appended.
- **Brand notes** — free-form rules like "always write in second person" or "never compare to competitors by name".
- **Brand safety scoring** — tragedy and divisive stories are automatically scored lower for brand accounts. A brand jumping on a disaster looks exploitative. A commentator should react to everything. The system knows the difference.

The brand kit is merged into the voice genome, so every generation path — news reactions, repurposed content, callbacks, evergreens — gets it automatically.

### 5. Content Squeezer — one input, an entire content calendar
The news-watching mode generates content reactively. The Squeezer is the proactive mode: you hand it one thing you already made, and it builds a full multi-platform content pack around it.

**Input:** paste text, drop a URL (any article), or paste a YouTube link (it auto-transcribes the captions).

**What it produces from one input (default plan):**
- 1 LinkedIn long-form post
- 2 Twitter/X threads
- 3 quote + context cards (ideal for carousels and shares)
- 1 newsletter section
- 1 video script

**How it's smarter than "just rewrite this for LinkedIn":**

Squeezer v2 doesn't generate everything from the raw blob. It first decomposes the source into typed insight nodes — **ideas** (each with 2-3 distinct angles: contrarian, educational, data-led, hot take), **claims**, **stories**, **statistics**, **quotes**, **opinions**. Then each draft is generated from ONE idea + ONE angle, with the most supporting facts attached. The result: 8 drafts that each make a different point, not 8 variations of the same summary.

A novelty check flags ideas you've already published — "you covered a very similar idea 3 weeks ago" — without blocking you.

Every asset is saved to your content library. Re-squeeze the same piece months later with an evolved voice and get a completely different set of drafts.

---

## Why agencies should use this

### The math of managing 20 accounts
An agency with 20 brand clients, each needing 2 posts/day across 3 platforms = 120 content pieces/day. At 30 min per piece, that's a 60-hour/day content operation. With Pulse: the agent drafts everything, the team approves and spots checks. The same team manages 3x the accounts.

### Voice consistency across clients
Every client account has its own style DNA and brand kit. No crossover, no drift. A junior writer can approve drafts without the "does this sound like them?" check — the system already ran that check and scored it.

### The content library compounds
Every source squeezed goes into the account's content library. A product launch article from Q1 can be re-squeezed in Q3 for a different angle. A founder podcast from 6 months ago is re-squeezed for a new audience segment. The library becomes a perpetually reusable asset — agencies traditionally lose this value when a client churns.

### Speed advantage for reactive content
When a major story breaks, agencies are slow by structure — it goes through a brief, a writer, a review, a revision, an approval. Pulse detects the story, generates the draft, and pushes it to the account manager's phone in under 8 minutes. The account manager approves with one tap. First-mover advantage, without the operational overhead.

### The safety layer is built in
Three automated checks on every draft before it reaches the human reviewer:
1. **Grounding** — every factual claim traced back to the source. No hallucinated statistics reach the client.
2. **Stance arc guard** — the draft won't contradict something the account said before. No embarrassing flip-flops.
3. **Backlash simulator** — on high-stakes posts, "how could this be screenshotted against us?" Pass fails → draft flagged.

Agencies charge for this layer. It's usually a senior editor's job. Here it's automated.

---

## The user flow

### Day 1 — setup (30 minutes total)

**Step 1: Create an account (2 min)**
Sign up at the web app. Pick account kind: commentator, creator, or brand.

**Step 2: Set your niche (3 min)**
"I'm a data-backed markets and economy commentator, skeptical of government spin."
Set verticals: finance, politics. Set regions: India, US.
Set topics: RBI, Fed, inflation, GDP, markets.

**Step 3: Add watch sources (5 min)**
Add 5-10 YouTube channels you follow. Add 3-5 subreddits. The agent already watches 117 RSS feeds for your verticals — you're adding depth, not breadth.

**Step 4: Build your voice (15 min)**
Paste 50+ of your existing posts (tweets, LinkedIn, anything). Pulse extracts your style DNA in 2 minutes. You can see the extracted genome: sentence length, sarcasm level, signature phrases. Edit anything wrong.

Or: use the Voice Importer — paste posts from a writer whose style you admire. Pulse imports their patterns as inspiration, kept separate from your personal voice, blended at your configured ratio.

**Step 5: Connect Telegram (5 min)**
Create a Telegram bot via @BotFather. Add your bot token and chat ID. This is the review interface — every draft arrives here.

That's it. The agent starts watching immediately.

---

### Every day — the normal operating loop

**Morning (2 min)**
You wake up to a Telegram message: your morning briefing. Yesterday's top performers. 3 COOL ideas from the ideas bank you could post today. Any open predictions that have new developments. The optimal posting windows for today based on your historical engagement patterns.

**During the day — reactive mode**
A FIRE signal fires: "RBI holds repo rate — surprise decision."
Pulse detects it within 8 minutes of the news breaking.
Your phone gets: the draft tweet, signal score (8.7/10 — FIRE), persona score (82/100), and two alternative hooks to choose from.
You tap the hook you like. You tap Approve. The post is formatted, labeled "AI-assisted," ready to copy.
Total time from news breaking to your post being live: under 5 minutes. Your competitors took 90 minutes.

**Proactive mode — content squeezer**
You record a 20-minute podcast. You upload it to YouTube. Pulse transcribes it automatically. You open the Squeezer, select the podcast from your content library, tap Squeeze. 15 minutes later: 8 drafts in your review queue — a LinkedIn long-form, two Twitter threads, three quote cards, a newsletter section, a video script. All in your voice. All making different points. All grounded in what you actually said.

**Weekly (5 min)**
Review your content performance. The system shows which formats, topics, and hooks got the most engagement. It's already updating your style DNA weights based on what you approved vs rejected. Your voice model is getting sharper.

---

### The agency flow

**IT cell / agency manager view**
One manager dashboard, N accounts. See every draft queue across all accounts in one view. Approve, reject, or edit drafts. See performance across accounts — which account, which vertical, which format is winning.

**Account setup**
New client onboarded in 30 minutes. Paste their existing posts → voice built. Set their brand kit (banned words, disclaimers, CTA). Set their verticals and topics. Connect their Telegram for approvals. Done.

**Variant generation (for campaigns)**
One approved message → 100 unique versions (same point, different wording, different angles). No two posts identical. Avoids platform spam detection. Each worker/satellite account posts their unique variant at the optimal time for their audience.

---

## The moat that builds over time

### Month 1
The agent watches your world and drafts in a voice approximation. You're still correcting maybe 1 in 5 posts. It saves 2-3 hours/day of writing time.

### Month 3
50+ approve/reject decisions. The learning loop has run 3-4 times. The voice model knows which topics you engage deeply on, which formats you prefer, which hooks you gravitate toward. Correction rate: 1 in 10.

### Month 6
The stance history table knows every position you've taken on 50+ topics. The events timeline has your 6-month history. The predictions tracker has your open bets. When you post about RBI, the system loads your last 4 takes, your prediction from March, and the contradictory statement the Governor made in January — all automatically. Posts feel like they come from someone who has been paying attention for years. Because the system has been.

### Month 12+
The content library has 300+ squeezed assets. The voice corpus has 500+ labeled examples. Fine-tuning a custom model becomes viable — a model that sounds specifically like this account, not just guided by style DNA in the prompt. At this point, the account has a moat that takes a year to replicate. Competitors can't copy it.

---

## What it costs to run

| Filter layer | Articles/day | Claude calls | Est. monthly cost |
|---|---|---|---|
| Raw ingestion | ~8,200 | — | $0 |
| After stale skip (>3h old) | ~4,900 | — | $0 |
| After keyword pre-filter | ~3,400 | — | $0 |
| After story dedup gate | ~230 | ~230/day | ~$24/month |

The watchers (RSS, YouTube, Reddit, Trends) are all free or keyless. The only paid API is Claude for scoring and generation. Set `DAILY_BUDGET_USD=2` to cap spend with automatic Telegram alerts.

---

## What's not here yet

- **Party / IT cell mode** — 100-variant generator for deploying to thousands of worker accounts. Designed, not built.
- **X/Twitter auto-posting** — intentionally deferred. The copilot flow (Telegram → copy to X) removes bot-flagging risk. Wire when ready.
- **LinkedIn + Threads posting APIs** — content is generated for these; posting is not wired.
- **Stripe billing** — not built. Currently single-instance, no multi-tenant SaaS layer.
- **Fine-tuned model per account** — the training data pipeline is live and collecting. Fine-tuning becomes viable at 500+ labeled examples per account (~3-6 months of active use).
