# VISUALS.md — the visual generation plan (living document)

> Why this exists: as a marketing tool, Pulse succeeds or fails on whether the
> final output *looks* good. This doc holds the full visual roadmap — what's
> built, what's next, and the architecture decisions with their reasoning —
> so nothing discussed is lost. Status legend matches CLAUDE.md:
> ✅ built · 🟡 partial · ⏳ next · ⏸ deferred (with trigger) · 🚫 refused.

---

## Architecture decision (settled)

**HTML/CSS-layout → image, rendered by Satori (self-hosted), NOT Pillow
coordinates and NOT AI image generators.**

- **Pillow** is pixel-pushing — fine for simple text cards (it remains our
  fail-safe fallback), a nightmare for real layouts (wrapping, flex spacing,
  multi-slide consistency).
- **AI image generators** (Midjourney/DALL·E/Flux) are *illustrators, not
  designers*: they hallucinate spelling, ignore exact hex codes, can't hold a
  layout across slides. 🚫 as the layout engine — see Phase 2 for where they
  DO fit.
- **Headless Chromium (Playwright)** renders everything but costs ~300MB+,
  RAM, and cold-starts inside our deliberately-cheap single container.
  ⏸ deferred — trigger: visuals proven core AND we're already splitting into
  multiple containers (pairs with the Postgres/queue migration).
- **Satori + resvg** (Vercel's OG-image stack): flexbox-subset CSS → SVG →
  PNG, pure JS, no browser, ~tens of MB. Runs as a **persistent localhost
  Node service** (decided over per-render subprocess: faster, no cold-start
  per image), spawned and health-checked by the Python side.
- The **durable asset is the template library + brand injection**, behind a
  `VisualRenderer` interface — the renderer backend stays swappable
  (Satori today, Chromium or a hosted API later, without touching templates'
  callers).

**Strategic guardrail:** we do not compete with Canva as a design playground.
The visual is the *auto-branded last mile* of content the agent already wrote
— "your draft, instantly a finished on-brand graphic." The moat stays the
brain; visuals are the multiplier.

---

## Phase V1 — the spine (this build)

| Item | Status |
|---|---|
| Brand kit visual fields: accent/secondary color, bg_style, font_family, watermark, logo_url | ✅ |
| `render/` Node service: satori → resvg, persistent localhost HTTP, health check | ✅ |
| Bundled open fonts (Inter / Lora / JetBrains Mono via @fontsource, woff) | ✅ |
| Templates: `quote_card` (line + handle + accent), `stat_highlight` (big number + context), `insight_card` (title + body) | ✅ |
| Auto-fit text sizing (font shrinks as text grows — nothing overflows) | ✅ |
| `pipeline/visuals.py`: `VisualRenderer` interface, Satori client, **Pillow fallback** (never hard-breaks), template auto-pick per post format, stat extraction | ✅ |
| Service lifecycle: Python spawns/health-checks the Node service | ✅ |
| Wired into approve flow (Telegram + web) replacing plain Pillow cards; served at `/visuals` | ✅ |
| Web: brand kit visual editor (colors, font, bg, watermark) | ✅ |
| Dockerfile: node binary + render bundle in the runtime image | ✅ |
| Tests: template mapping, payload shape, fallback, brand fields; real-render smoke (skipped when node deps absent) | ✅ |

## Phase V1.5 — breadth & polish

| Item | Status |
|---|---|
| **Carousel**: square (1080×1080) cover + N content slides + CTA closer; threads map tweet-per-slide, long-form packs paragraphs under a per-slide budget; cover hook auto-extracted (first sentence of huge openers); thin content falls back to a single card, as does any slide-render failure (no half-carousels). All slides pushed to Telegram individually + downloadable strip in web review. | ✅ |
| Logo image rendering: Python fetches + sizes via Pillow → data-URL → Satori footer (cached; failure-safe) | ✅ |
| Per-preset visual defaults — picking a preset seeds the brand kit (SaaS indigo/sans, D2C warm/light, finance emerald/mono, …) | ✅ |
| Live preview in web Settings: renders a sample card with the UNSAVED editor values | ✅ |
| Regenerate/swap-template control on the review card (quote/stat/insight) | ✅ |
| Visual approve/reject signal (start collecting preference data) | ⏳ |
| **Font architecture note:** fontsource browser subsets DON'T work with Satori (no same-family multi-file fallback → ₹ tofu). Fixed: `merge_fonts.py` builds single merged ttf per family/weight (committed in `render/fonts/`), and every stack ends in Noto Sans for cross-family glyph fallback. | ✅ |
| More templates: announcement card, list/tips card, before-after | ⏳ |

## Phase V1.75 — visual prowess (SHIPPED)

The four gaps called out in the honest assessment ("text-first cards, no
charts, three fonts, gradient fallback"), closed in one build:

| Item | Status |
|---|---|
| **chart_card — real data visualization.** Bar + line charts drawn deterministically (`render/charts.mjs`): bars are flexbox, lines are one SVG path with absolutely-positioned value labels (Satori can't render svg `<text>`). Latest point pops in accent. `pipeline/charts.py` extracts the spec — free numeric gate (≥3 distinct numbers) → ONE bounded Claude call ("extract, never invent") → validated + CACHED in post meta, so re-renders/template swaps never pay twice. Misses cache too; transient failures don't (retry next render). Negative values force `line` (bars can't show negatives honestly). data_story auto-tries the chart; explicit `template=chart_card` works on any post; no series → graceful fall-through to the normal card. | ✅ |
| **Illustration layer.** `render/icons.mjs`: ~24 bundled stroke icons (lucide-style path data, no deps, no fetches) + geometric motifs (dot grid / accent ring / light beam, seed-picked so a feed doesn't repeat one motif). `pick_icon()` maps content keywords → icon (markets→trending_up, parliament→landmark, court→scale, IPL→trophy…), format as fallback. Rendered at low opacity UNDER the text column — decoration never reflows text. `VISUALS_DECOR=none\|subtle\|bold` (default subtle). chart_card keeps decor off — nothing competes with the data. | ✅ |
| **Procedural hero backgrounds.** `render/art.mjs`: seeded compositions in the brand palette — orbs / mesh corners / diagonal beams / horizon glow. Deterministic (same seed+accent = same art, so regenerate doesn't reshuffle an approved card). Hero with no image now gets art, never a flat gradient — every account looks designed from day 1, keyless and free. Photos keep the strong scrim; art gets a soft one (it's already dark). | ✅ |
| **Custom brand fonts.** `POST /api/accounts/{id}/font` (TTF/OTF, weight 400/700, magic-bytes validated) → saved by convention as `render/fonts/custom/acct{id}-{weight}.ttf` (gitignored), kit `font_family='custom'` — no schema change. Server loads custom fonts lazily per render, cached by mtime (re-upload applies without restart). Missing file → stack falls back to bundled fonts + Noto Sans, never tofu. DELETE endpoint reverts to `sans`. | ✅ |

## Phase V1.9 — the visual blueprint engine (SHIPPED)

The reframe: users don't need "images", they need **visual communication of
ideas** — and the highest-performing organic visuals on LinkedIn/X/IG are
*structured* graphics (comparisons, frameworks, timelines, process flows,
lists), not artwork. LLMs are good at structure, bad at design → Claude
extracts a typed blueprint (`pipeline/blueprint.py`), the deterministic
templates (`render/blueprints.mjs`) own every pixel. Same cost posture as
chart_card: one bounded call, "extract never invent", cached on the post
(misses too; transient failures retry).

| Item | Status |
|---|---|
| `comparison_card` — X vs Y panels (yours gets the accent treatment), SVG ✓/✕ markers, centered "vs" chip | ✅ |
| `framework_card` — 3-5 numbered pillars of one idea, equal cards in a row | ✅ |
| `timeline_card` — 3-6 dated milestones on a horizontal rail, "now" dot filled accent | ✅ |
| `process_card` — 3-5 sequential steps joined by SVG arrows | ✅ |
| `list_card` — 3-6 numbered tips/mistakes/rules; the title is the hook | ✅ |
| Shared primitives extracted to `render/ui.mjs` (theme, frame, footer, number chip) — templates.mjs and blueprints.mjs stay consistent by construction | ✅ |
| Auto-pick: explainer / evergreen / counter_narrative try a blueprint before settling for a text card; carousel formats keep their multi-slide treatment; hot_take stays punchy (never attempts) | ✅ |
| Explicit swap: any post can request any blueprint template; the ask biases the extraction prompt but "prefer null over a weak structure" still holds; no structure → graceful fall-through | ✅ |
| **Glyph rule learned:** ✓ ✕ → are NOT in the merged font subsets — every marker/arrow in templates is now an SVG path (`icons.mjs`), never a text glyph | ✅ |
| Square (1080×1080) variants of the blueprint cards for IG feed | ⏳ |
| 9:16 story/reel template | ⏳ |

## Phase V1.95 — attention design (SHIPPED)

The honest critique that drove this: the system was optimized for
*information* design (useful, clear) when virality runs on *attention*
design (tension, emotion, narrative). "5 Founder Mistakes" informs;
"I wasted 2 years because of this" stops the scroll. Same content.

| Item | Status |
|---|---|
| **Hook hierarchy.** The blueprint extractor now also pulls the HOOK — the single most surprising/contrarian/emotional line (≤60 chars, "never manufacture drama": empty when nothing genuinely stops the scroll). Templates render the hook as the dominant headline with the descriptive title demoted to a small uppercase overline. No hook → title leads, exactly as before. | ✅ |
| **journey_card** — the narrative timeline. Milestones carry a MOOD (`win`/`fail`/`turn`/`neutral`): red ✕ circles for the failure beats, green ✓ for the win, filled accent dot at the turning point ("Month 1 build → Month 12 still building ✕ → Month 18 talked to users → Today PMF ✓"). A journey with zero emotional beats auto-downgrades to plain timeline — emotion is extracted, never decorated on. | ✅ |
| **Narrative carousel engine** (`pipeline/narrative.py`). Carousels are now built from a story ARC — hook slide → one beat per slide (each with its own scannable headline + body) → payoff slide ("a reader who only sees slide 1 and the last slide still gets the story") — instead of paragraph splitting. One bounded Claude call, cached (`narrative` in post meta), misses cached, transient failures retried. Paragraph splitting remains the free fallback and the `NARRATIVE_CAROUSEL=false` path. `carousel_slide` template gained headline+body layout. | ✅ |
| **Visual analytics v1** (`pipeline/visual_prefs.py`). Every render logs `visual_template` into post meta (chart/blueprint/single-card/`carousel_narrative` vs `carousel_split`). Deterministic stats join that log with approve/reject verdicts; a template with ≥6 reviews and <34% approval is SHUNNED on automatic paths (explicit requests always honored). This is the Visual-Genome seed: collect first, bias gently, compound. | ✅ |
| Sketch/founder whiteboard mode (handwriting font + rough borders + rotations) | ⏳ — needs a handwriting family added to the merge_fonts pipeline first |
| Meme layer | 🚫 — meme formats decay fast, carry copyright risk, and one mis-calibrated meme on a political/brand account is a reputation event. Wrong risk profile, permanently. |

## Phase V1.97 — choosing the right visual (SHIPPED)

The insight that framed this build: with 14 templates the bottleneck moved
from "can we render?" to "can we CHOOSE the right visual?" The winner isn't
the system with 50 templates; it's the one that correctly decides journey-
not-framework, narrative-carousel-not-hero, and learns that THIS account
performs best with minimalist visuals.

| Item | Status |
|---|---|
| **Size variants — square + story.** The render protocol accepts `data._size` (`square` 1080×1080 for IG feed, `story` 1080×1920 for reels/stories; default 16:9). Size-dependent templates (hero art, chart width, timeline rail) read the canvas dims. `generate_for_post(size=...)` renders a variant BESIDE the primary (`visual_square`/`visual_story` in meta, never replacing `visual`); API: `POST /api/drafts/{id}/visual?size=square`. Carousels stay square by definition. | ✅ |
| **Visual A/B engine** (`generate_alternates`). Up to k alternate approaches per draft at ZERO marginal cost by construction: only cached structures (chart spec, blueprint) + free templates (procedural hero, stat/insight/quote) are candidates — no new Claude calls, ever. Ordered by the account's Visual Genome, stored in meta (`visual_alternates`), exposed at `POST /api/drafts/{id}/visual/alternates`. The human's pick via the existing swap control updates `visual_template` — which IS the preference signal, no extra plumbing. | ✅ |
| **Visual Genome v1** (`visual_prefs.py` grown up). Beyond shunning losers: `preferred_templates()` ranks every template with ≥4 reviews by approval rate (orders A/B alternates); `better_generic_card()` upgrades the generic insight_card to a text-only template the account DEMONSTRABLY prefers (≥4 reviews, ≥60% approval, ≥15-point margin over the incumbent). Evidence-gated at every step: ordering is low-stakes (human still picks), overriding the default is gated harder. | ✅ |
| Consulting slide layer (McKinsey-style: headline / drivers / barriers / key insight) | ⏳ — next template build, high value for founder/consultant/agency accounts |
| Visual Review Studio (input → blueprint → template → output → approval rate, in Pulse Studio) | ⏳ — the data pipeline already exists: post meta carries blueprint, narrative, visual_template, visual_alternates |
| Feed awareness ("what stands out among the last 20 posts this user saw") + visual trend engine | ⏸ — needs feed/competitor visual data we don't collect yet; revisit when the Instagram inspiration watcher (V2b) lands |
| Screenshot recreation engine (fake Notion/Slack/WhatsApp/email screenshots) | 🚫 — fabricated screenshots on a political/news platform are manufactured evidence, not a growth hack. A notes-app *aesthetic* for the account's own words may come later as a style; an engine for fake screenshots, never. |
| Visual Genome v2 (density/typography/imagery preference profile per persona) | ⏳ V2b — grows out of the analytics log + A/B picks now accumulating |

## Phase V2 — the AI-imagery design agent (V2a SHIPPED)

The user-insight this encodes: human designers already work as
*find-inspiration → prompt an image model → iterate → finish typography in
Canva*. We automate that loop, with one reframe — **the "Canva finish" IS
Satori** (deterministic typography/brand layer), so the agent only owns the
imagery underneath. Lives in `pipeline/design.py` + the `hero_card` template.

| Item | Status |
|---|---|
| Image-gen backend behind an interface: keyless **library** backend (default — picks the best approved background from `visual_refs` by tag/notes match) + paid **openai** backend (gpt-image-1, `VISUALS_IMAGEGEN=openai`) | ✅ |
| Per-day cost guardrail: `VISUALS_IMAGE_DAILY_CAP` (default 12) counted from the data itself (`generated_images_today`); over cap → falls back to library | ✅ |
| Every paid generation persisted as a `kind='generated'` visual_ref — reusable for free forever | ✅ |
| Prompt construction from brand kit (colors/bg mood/notes) + post subject + account niche, with a hard NO-TEXT instruction (typography is Satori's) | ✅ |
| **Generate → Claude-vision critique → regenerate-with-feedback** loop, bounded by `DESIGN_MAX_ITERS` (2) / `DESIGN_ACCEPT_SCORE` (7.0); fail-open judge; library picks skip critique (a human approved them) | ✅ |
| **Composite**: `hero_card` Satori template — image layer (or gradient fallback) + darkening scrim + auto-fit headline + brand footer on top | ✅ |
| Keyless path: upload approved backgrounds via `POST /api/accounts/{id}/refs` (file or URL, tags/notes); list/delete endpoints | ✅ |
| Wired into the existing swap-template control: `template=hero_card` on `/api/drafts/{id}/visual`; no backend/refs → degrades to the flat card | ✅ |
| Fully fail-safe: no refs, dead API, broken critique, render failure → flat card, never an error | ✅ |
| Visual preference profile learned from approvals (Genome-A-for-visuals) | ⏳ V2b |
| Instagram inspiration feed → automatic ref suggestions | ⏳ V2b (upstream shape built: `watch/instagram.py` intent:"inspiration") |
| Alternate image models (Flux / Ideogram / SDXL) behind the same interface | ⏳ when needed |

## Phase V2.5 — content-aware color (SHIPPED)

The flat-dark / single-gradient background made every card look the same
regardless of what it said. Now the background carries the content's
emotional register: a `CONTENT_THEMES` map in `render/ui.mjs` keys format +
dominant emotion → a deep multi-stop gradient + a suggested accent.

| Item | Status |
|---|---|
| Per-format gradient palettes: hot_take (fiery red-orange), contradiction (crimson-purple tension), data_story (ocean blue), thread (indigo), prediction (amber-gold), counter_narrative (emerald), explainer (slate-blue), achievement (gold), quote_context (purple), evergreen (forest), callback (teal), video_reaction (magenta) | ✅ |
| Emotion overrides format (outrage → red even on a data story); 6 emotion palettes (outrage/curiosity/pride/humour/surprise/validation) | ✅ |
| **Brand accent always wins** — a kit with a custom `accent_color` keeps its accent; content theming only fills the background gradient + the accent when the kit is still on the default. `bg_style:light` always respected. | ✅ |
| `format` + `meta_json.dominant_emotion` threaded from the post into `brand_payload(account, kit, post)` at every render call site | ✅ |

## Phase V3 — the Visual Intelligence Engine (entity-aware imagery)

> **The reframe (do NOT build "fetch from Google Images").** The goal is not
> image *fetching*; it is *visual intelligence* — the system understands WHO
> and WHAT a post is about, decides what KIND of visual fits, and only then
> resolves an asset, from **licensed sources**, composited with brand
> treatment. The literal "scrape Google" mechanism is refused: copyright
> (press photos are Reuters/AP/Getty), wrong-image risk (a political account
> posting the wrong soldiers = a fake-news ratio), and implied-narrative /
> likeness exposure. We already chose generation over scraping in V2 for
> exactly these reasons; this phase honours that and adds the missing branch.
>
> **What's already done (so this is smaller than it looks):** the strategy
> router already picks between three of the four visual strategies —
> *data_driven* (`chart_card`), *diagram_driven* (`blueprints.mjs`), and
> *typography_driven* (quote/stat/insight). The ONLY missing branch is
> **photo_driven**. And the learning layer already exists (`visual_prefs.py`
> Visual Genome) — this phase adds `visual_strategy` as a new dimension it
> learns over, it does not rebuild it.
>
> **The honest limit:** for the *breaking scene itself* (today's call, the
> specific soldiers) no licensed asset exists — only press agencies have it.
> So *portraits of named people* work; *a photo of the event* never does via
> automation. The scroll-stopping version of the Modi–Trump example is a
> treated **dual-portrait card**, not a photo of the call.

### The 15-layer vision, mapped to what already exists

The full V3 vision (the brainstorm doc) is 15 layers. **The honest accounting:
most of it is already shipped** in V1–V2. Re-reading the vision against the
codebase, here is where each layer actually stands — so the build targets the
~6 layers that are genuinely new, not the 9 that already work.

| # | Layer (vision) | Status | Lives in / what's missing |
|---|---|---|---|
| 1 | Content Understanding (entities, type, emotion, triggers) | 🟡 | content-type = `format`, emotion = `dominant_emotion`, attention-trigger = the HOOK (all ✅, V1.95). **NEW: entity extraction** (people/orgs/products/locations) |
| 2 | Attention Engine (the anchor) | ✅ | hook hierarchy already extracts the scroll-stopping line (`blueprint.py`, V1.95) |
| 3 | Visual Strategy Engine (typography/blueprint/data/image/hybrid) | 🟡 | typography/blueprint/data branches all ✅. **NEW: image-first + hybrid branches** |
| 4 | Visual Entity Engine (symbols/icons) | ✅ | `render/icons.mjs` + `pick_icon()` keyword→symbol (V1.75) |
| 5 | Asset Retrieval (library→approved→wikimedia→official→licensed→search) | 🟡 | library + approved refs ✅ (`visual_refs`, V2a). **NEW: Wikipedia/Wikimedia/Openverse tiers.** Google "search provider" 🚫 refused |
| 6 | Visual Blueprint Engine (framework/comparison/timeline/journey/process/list/chart/hero/narrative) | ✅ | all built (V1.9, V1.95) |
| 7 | Composition Engine (layouts + sizes) | 🟡 | sizes square/story ✅ (V1.97); most layouts ✅. **NEW: dual_portrait, hero_portrait, product_showcase** |
| 8 | Brand Engine (logo/fonts/colors/watermark/presets) | ✅ | full brand kit + per-preset defaults (V1, V1.5) |
| 9 | Rendering Engine (Satori+resvg, 16:9/1:1/9:16) | ✅ | the spine (V1) |
| 10 | Visual Critic (quality score → regenerate) | 🟡 | vision-critique loop exists for hero imagery (`design.py`, V2a). **NEW: generalize to a per-card score across attention/readability/hierarchy/brand/platform-fit** |
| 11 | Visual A/B Engine (multiple approaches) | ✅ | `generate_alternates`, zero-marginal-cost (V1.97) |
| 12 | Visual Genome (learn preferences) | 🟡 | `visual_prefs.py` learns template preference (V1.97). **NEW: add `visual_strategy` as a learned dimension** |
| 13 | Platform Intelligence (per-platform strategy) | ❌ | **NEW: map platform → strategy/format/size bias** |
| 14 | Visual Review Studio (debug console) | ⏳ | data pipeline already exists in post meta; **NEW: the Studio page itself** |
| 15 | Self-Improving Loop (knowledge graph) | 🟡 | the Genome IS this loop; the "knowledge graph" framing is aspirational, grows from 12+13 |

**Conclusion:** the new work is layers **1 (entities), 3 (image strategy),
5 (licensed assets), 7 (portrait/product layouts), 10 (general critic),
13 (platform intelligence)**, plus the **14 (Studio)** view and the **12**
strategy-dimension. Everything else ships today. That's the build below.

### Step-by-step build sequence (the new work, ordered)

Each step is independently shippable and fail-safe (a failure falls back to
the card we render today). Steps 1–4 are the spiky v1 — the Modi–Trump case
end to end. 5+ broaden it.

**Step 1 — Entity + strategy extraction** *(Layer 1, 3 — the brain)*
- Extend the existing article-understanding / decision Claude call to also emit
  `entities` (people/orgs/products/locations, each typed + role) and
  `visual_strategy` ∈ {typography, blueprint, data, image_portrait, image_vs, product, hybrid}.
- Ride the call already made — no new Claude call. Cache on post meta
  (extract-never-invent, misses cached, transient failures retry — same
  posture as chart/blueprint).
- **Files:** `pipeline/decision.py` (or the understanding call) + `pipeline/memory.py` (meta).
- **Done when:** every scored post carries `entities[]` + `visual_strategy`.

**Step 2 — Licensed asset resolver, Tier 1** *(Layer 5 — the hands)*
- New module `pipeline/assets.py`. `resolve_portrait(name)` → Wikipedia REST
  `…/page/summary/{name}` → `thumbnail.source` → fetch, size via Pillow → data-URL.
  We ALREADY call this API in `watch/trends.py`; the lead image is
  Wikipedia-editor-disambiguated — the clean official portrait ~80% of the time.
- Per-entity cache (Modi's portrait doesn't change weekly).
- **Done when:** `resolve_portrait("Narendra Modi")` returns a sized data-URL or None.

**Step 3 — Treated portrait templates** *(Layer 7 — the taste)*
- `render/templates.mjs`: `dual_portrait` (two portraits, brand-color duotone
  or circular cut-out, accent "×"/"vs" between, headline below) and
  `hero_portrait` (single treated portrait + headline, reuses the `hero_card`
  scrim path).
- **Mandatory brand treatment** (duotone/scrim/cut-out) on every fetched photo —
  raw photos are never placed flat. Treatment is what makes the feed consistent
  AND reads as "news-desk graphic," not "scraped."
- **Done when:** given 2 portrait data-URLs + a headline, the renderer produces a treated card.

**Step 4 — Wire image-first into the auto-pick router** *(closes the v1 loop)*
- In `visuals.py generate_for_post`: when `visual_strategy ∈ {image_portrait, image_vs}`,
  resolve assets (Step 2) → render portrait template (Step 3). Any miss
  (no entity, no portrait, render fail) → fall through to today's card.
- **Done when:** a person-subject post auto-produces a treated portrait card end to end, the Modi–Trump example included.

**Step 5 — Asset resolver Tier 2 + attribution** *(broaden Layer 5)*
- Wikimedia Commons / Openverse CC search for concepts/places/products
  (filter to commercial-use licenses). Feeds the existing `hero_card` background.
- Small attribution footer line when a CC license requires it.
- **No Tier "search/Google."** No-asset → existing card. (🚫 in Deferred.)

**Step 6 — General Visual Critic** *(Layer 10)*
- Generalize the `design.py` vision critique into a per-candidate score across
  attention / readability / hierarchy / brand-fit / platform-fit (0–100).
  Low score → regenerate or pick the next A/B alternate (the engine exists).
- Fail-open (a dead judge passes the card), same as today.
- **Done when:** cards carry a visual quality score; sub-threshold cards auto-swap to an alternate.

**Step 7 — Platform Intelligence** *(Layer 13)*
- Map platform → strategy/format/size bias in the strategy engine: LinkedIn →
  blueprint/educational/portrait; X → punchy typography/high-contrast; IG →
  carousel/emotional/square; Threads → conversational.
- **Done when:** the same content yields a LinkedIn-framework, an X-punchy card, and an IG-carousel automatically.

**Step 8 — Genome strategy dimension** *(Layer 12)*
- Log `visual_strategy` alongside the already-logged `visual_template`;
  `visual_prefs.py` learns which strategies this account's audience rewards
  ("political → portraits +X%, finance → charts +Y%"). Extends the existing
  log + loop — no new learning system.

**Step 9 — Visual Review Studio** *(Layer 14)*
- A Pulse Studio page showing the full trace per post: content → entities →
  attention anchor → strategy → blueprint → assets chosen → A/B alternates →
  final render → approval rate. The data already lives in post meta; this is
  the read-only view (same shape as the other Studio pages).

**Sequencing note:** this is a multi-day build and belongs AFTER the core loop
is validated end-to-end (signals → draft → Telegram → approve → post) with
live credits. Ship **Steps 1–4 first** (the Modi–Trump slice); they prove the
whole thesis. 5–9 broaden and compound. Every step degrades to the card we
render today, so the platform is never worse for having started.

---

## Deferred / refused

- ⏸ **Headless Chromium renderer** — trigger above.
- ⏸ **Hosted render APIs** (htmlcsstoimage/Bannerbear/Urlbox) — viable swap-in
  if self-hosting Satori ever becomes a burden; costs per image, data leaves
  the box.
- ⏸ **Canva Connect / Figma API integration** — when brands demand editing in
  tools they know.
- 🚫 **AI image generators as the layout/typography engine** — wrong tool,
  permanently.
- 🚫 **Scraping Google Images for assets** — copyright (results are press-agency
  photos), wrong-image risk (a political account posting the wrong scene is a
  fake-news event), and implied-narrative/likeness exposure. Replaced by the
  licensed-source resolver in Phase V3 (Wikipedia/Wikimedia/Openverse). The
  *goal* (real faces on cards) is kept; the *mechanism* is refused.
