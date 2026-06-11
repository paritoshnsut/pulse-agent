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

## Phase V2 — the AI-imagery design agent (planned, not started)

The user-insight this encodes: human designers already work as
*find-inspiration → prompt an image model → iterate → finish typography in
Canva*. We automate that loop, with one reframe — **the "Canva finish" IS
Satori** (deterministic typography/brand layer), so the agent only owns the
imagery underneath:

1. Image-gen backend behind an interface (Flux / Ideogram / SDXL / DALL·E)
   + per-day cost guardrails (these are paid calls; the iterate loop
   multiplies them).
2. Prompt construction from brand kit + content + curated inspiration refs.
3. **Generate → Claude-vision critique → regenerate-with-feedback** loop —
   the same shape as our persona-gate loop, with vision as the judge
   ("composition unbalanced, palette off-brand; emphasize X").
4. **Composite: AI background/hero + Satori text/logo layer on top.** Gets
   "designed" richness without AI's spelling/layout failures — the genuine
   quality edge over flat-HTML tools.
5. Visual preference profile learned from approvals (Genome-A-for-visuals).
6. Cheaper no-paid-API path: brand uploads approved background images/
   textures; the agent selects + treats them per post.

Trigger to start V2: V1 visuals are being used on real posts and text-only
cards feel limiting; budget exists for paid image generation.

## Deferred / refused

- ⏸ **Headless Chromium renderer** — trigger above.
- ⏸ **Hosted render APIs** (htmlcsstoimage/Bannerbear/Urlbox) — viable swap-in
  if self-hosting Satori ever becomes a burden; costs per image, data leaves
  the box.
- ⏸ **Canva Connect / Figma API integration** — when brands demand editing in
  tools they know.
- 🚫 **AI image generators as the layout/typography engine** — wrong tool,
  permanently.
