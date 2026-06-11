// templates.mjs — the visual template library. THE durable asset (VISUALS.md):
// renderers come and go; these layouts + the brand injection are what we keep.
//
// Templates are Satori element trees (plain objects — satori's JSX-free form:
// { type, props: { style, children } }). Every template takes (data, brand)
// where brand carries accent/secondary colors, bg style, font family and
// watermark from the account's brand kit, with tasteful defaults when unset.

const SIZE = { width: 1200, height: 675 };      // 16:9 — single cards (X/LinkedIn)
const SQUARE = { width: 1080, height: 1080 };   // 1:1 — carousel slides (LinkedIn/IG)

const DEFAULTS = {
  accent: "#4da3ff",
  secondary: "#9aa4b2",
  bg_style: "dark",
  font_family: "sans",
};

const FONT_NAMES = { sans: "Inter", serif: "Lora", mono: "JetBrains Mono" };

function theme(brand) {
  const b = { ...DEFAULTS, ...Object.fromEntries(
    Object.entries(brand || {}).filter(([, v]) => v)) };
  const dark = b.bg_style !== "light";
  return {
    accent: b.accent,
    secondary: b.secondary,
    font: FONT_NAMES[b.font_family] || "Inter",
    fg: dark ? "#f0f2f5" : "#16181d",
    muted: dark ? "#8b94a1" : "#6b7280",
    background: b.bg_style === "gradient"
      ? `linear-gradient(135deg, #101319 0%, #1a2030 55%, ${b.accent}33 100%)`
      : dark ? "#101319" : "#fafafa",
    watermark: b.watermark_text || "",
    handle: b.handle || "",
  };
}

// Auto-fit: longer text -> smaller type, so nothing overflows the canvas.
export function fitFontSize(text, base = 58, min = 30) {
  const n = (text || "").length;
  if (n <= 90) return base;
  if (n <= 160) return 48;
  if (n <= 240) return 40;
  if (n <= 340) return 34;
  return min;
}

const el = (type, style, children) => ({ type, props: { style, ...(children !== undefined ? { children } : {}) } });

function frame(t, children) {
  return el("div", {
    width: "100%", height: "100%", display: "flex", flexDirection: "column",
    background: t.background, color: t.fg, fontFamily: t.font,
    padding: "64px 72px", justifyContent: "space-between",
  }, children);
}

function accentBar(t) {
  return el("div", { width: 88, height: 10, background: t.accent, borderRadius: 5 });
}

function footer(t) {
  const kids = [];
  if (t.handle) kids.push(el("div", { fontSize: 26, fontWeight: 700, color: t.accent, display: "flex" }, `@${t.handle.replace(/^@/, "")}`));
  kids.push(el("div", { fontSize: 22, color: t.muted, display: "flex" },
    t.watermark || " "));
  return el("div", {
    display: "flex", justifyContent: "space-between", alignItems: "center",
  }, kids);
}

// ---------------------------------------------------------------- templates
export function quoteCard(data, brand) {
  const t = theme(brand);
  const text = data.text || "";
  return frame(t, [
    accentBar(t),
    el("div", {
      fontSize: fitFontSize(text), fontWeight: 700, lineHeight: 1.25,
      display: "flex", flexGrow: 1, alignItems: "center",
    }, `“${text}”`),
    footer(t),
  ]);
}

export function statHighlight(data, brand) {
  const t = theme(brand);
  const stat = data.stat || "";
  const context = data.context || data.text || "";
  return frame(t, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1, justifyContent: "center" }, [
      el("div", {
        fontSize: stat.length > 9 ? 110 : 150, fontWeight: 700,
        color: t.accent, display: "flex", lineHeight: 1,
      }, stat),
      el("div", {
        fontSize: fitFontSize(context, 42, 26), color: t.fg, marginTop: 28,
        lineHeight: 1.3, display: "flex",
      }, context),
    ]),
    footer(t),
  ]);
}

export function insightCard(data, brand) {
  const t = theme(brand);
  const title = data.title || "";
  const body = data.text || "";
  return frame(t, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1, justifyContent: "center" }, [
      title ? el("div", {
        fontSize: 30, fontWeight: 700, color: t.accent, marginBottom: 22,
        textTransform: "uppercase", letterSpacing: 2, display: "flex",
      }, title) : el("div", { display: "flex" }),
      el("div", {
        fontSize: fitFontSize(body, 50), fontWeight: 600, lineHeight: 1.3,
        display: "flex",
      }, body),
    ]),
    footer(t),
  ]);
}

// ------------------------------------------------------- carousel slides
// Square multi-slide format: cover (the hook + swipe cue) -> content slides
// (numbered, one idea each) -> CTA closer. Python orchestrates the sequence;
// each render call produces one slide.

function slideCounter(t, index, total) {
  return el("div", {
    display: "flex", justifyContent: "space-between", alignItems: "center",
  }, [
    accentBar(t),
    el("div", { fontSize: 26, color: t.muted, display: "flex" },
      total ? `${index}/${total}` : " "),
  ]);
}

export function carouselCover(data, brand) {
  const t = theme(brand);
  const text = data.text || "";
  return el("div", {
    width: "100%", height: "100%", display: "flex", flexDirection: "column",
    background: t.background, color: t.fg, fontFamily: t.font,
    padding: "72px", justifyContent: "space-between",
  }, [
    slideCounter(t, 1, data.total),
    el("div", {
      fontSize: fitFontSize(text, 72, 38), fontWeight: 700, lineHeight: 1.2,
      display: "flex", flexGrow: 1, alignItems: "center",
    }, text),
    el("div", { display: "flex", justifyContent: "space-between", alignItems: "center" }, [
      t.handle
        ? el("div", { fontSize: 28, fontWeight: 700, color: t.accent, display: "flex" },
            `@${t.handle.replace(/^@/, "")}`)
        : el("div", { display: "flex" }),
      el("div", { fontSize: 28, color: t.muted, display: "flex" }, "swipe →"),
    ]),
  ]);
}

export function carouselSlide(data, brand) {
  const t = theme(brand);
  const text = data.text || "";
  return el("div", {
    width: "100%", height: "100%", display: "flex", flexDirection: "column",
    background: t.background, color: t.fg, fontFamily: t.font,
    padding: "72px", justifyContent: "space-between",
  }, [
    slideCounter(t, data.index, data.total),
    el("div", {
      fontSize: fitFontSize(text, 52, 32), fontWeight: 600, lineHeight: 1.32,
      display: "flex", flexGrow: 1, alignItems: "center",
    }, text),
    footer(t),
  ]);
}

export function carouselCta(data, brand) {
  const t = theme(brand);
  const cta = data.cta_text
    || (t.handle ? `Follow @${t.handle.replace(/^@/, "")} for more` : "Thanks for reading");
  return el("div", {
    width: "100%", height: "100%", display: "flex", flexDirection: "column",
    background: t.background, color: t.fg, fontFamily: t.font,
    padding: "72px", justifyContent: "space-between",
  }, [
    slideCounter(t, data.index, data.total),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1, justifyContent: "center" }, [
      el("div", {
        fontSize: fitFontSize(cta, 64, 36), fontWeight: 700, lineHeight: 1.25,
        color: t.fg, display: "flex",
      }, cta),
      data.cta_url ? el("div", {
        fontSize: 34, color: t.accent, marginTop: 30, fontWeight: 700, display: "flex",
      }, data.cta_url) : el("div", { display: "flex" }),
    ]),
    footer(t),
  ]);
}

export const TEMPLATES = {
  quote_card: quoteCard,
  stat_highlight: statHighlight,
  insight_card: insightCard,
  carousel_cover: carouselCover,
  carousel_slide: carouselSlide,
  carousel_cta: carouselCta,
};

export const TEMPLATE_SIZES = {
  carousel_cover: SQUARE,
  carousel_slide: SQUARE,
  carousel_cta: SQUARE,
};

export { SIZE };
