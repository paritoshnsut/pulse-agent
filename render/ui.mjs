// ui.mjs — shared design primitives for every template (templates.mjs +
// blueprints.mjs). One place owns the theme/brand mapping, the framed canvas,
// and the auto-fit type scale, so all cards stay visually consistent.

import { decorLayer } from "./icons.mjs";

export const SIZE = { width: 1200, height: 675 };    // 16:9 single cards
export const SQUARE = { width: 1080, height: 1080 }; // 1:1 carousel slides + IG feed
export const STORY = { width: 1080, height: 1920 };  // 9:16 stories/reels

// canvas sizes a caller may request via data._size (server resolves)
export const SIZES = { wide: SIZE, square: SQUARE, story: STORY };

const DEFAULTS = {
  accent_color: "#4da3ff",
  secondary_color: "#9aa4b2",
  bg_style: "dark",
  font_family: "sans",
};

// ─── Content-aware visual identity ───────────────────────────────────────────
// Each content type carries its own emotional register. A data story should
// feel analytical; a hot take should feel urgent; a contradiction should feel
// tense. This map translates format + emotion → gradient + accent so every
// card's visual mood matches what it says.
//
// Emotion overrides format when present — outrage on a data story is still
// red. Brand accent_color always wins over the content accent (if set).
// Light bg_style is always respected as-is.

const CONTENT_THEMES = {
  // ── Formats ──────────────────────────────────────────────────────────────
  hot_take: {
    bg: "linear-gradient(145deg, #120400 0%, #1e0800 40%, #2d1000 70%, #3d1500 100%)",
    accent: "#ff4d00",
    // fiery orange-red — urgency, breaking, no time to think
  },
  contradiction: {
    bg: "linear-gradient(135deg, #0d0514 0%, #14042a 35%, #1a0535 65%, #0a1525 100%)",
    accent: "#e84545",
    // crimson-purple tension — split reality, "then vs now"
  },
  data_story: {
    bg: "linear-gradient(150deg, #010a16 0%, #021830 45%, #033050 80%, #042545 100%)",
    accent: "#38b2ff",
    // deep ocean blue — analytical, trust the numbers
  },
  thread: {
    bg: "linear-gradient(135deg, #080618 0%, #100e30 45%, #160c40 75%, #0e0a28 100%)",
    accent: "#a78bfa",
    // deep indigo-purple — narrative, layered, builds to something
  },
  prediction: {
    bg: "linear-gradient(140deg, #0f0900 0%, #1e1400 40%, #2e1e00 70%, #3d2a00 100%)",
    accent: "#fbbf24",
    // amber-gold — confidence, stakes, bold call
  },
  counter_narrative: {
    bg: "linear-gradient(135deg, #021008 0%, #041e0e 40%, #063018 70%, #083a20 100%)",
    accent: "#34d399",
    // deep emerald — subversive, fresh angle, not what you expected
  },
  explainer: {
    bg: "linear-gradient(150deg, #060c18 0%, #0c1628 45%, #101f36 75%, #0e1a2e 100%)",
    accent: "#60a5fa",
    // calm slate-blue — educational, clear, trustworthy
  },
  achievement: {
    bg: "linear-gradient(140deg, #100800 0%, #1f1200 40%, #301c00 70%, #402600 100%)",
    accent: "#f59e0b",
    // warm gold — celebration, milestone, earned
  },
  quote_context: {
    bg: "linear-gradient(135deg, #080310 0%, #12062a 40%, #180840 70%, #100530 100%)",
    accent: "#c084fc",
    // rich purple — eloquent, quotable, the thing worth saying
  },
  evergreen: {
    bg: "linear-gradient(145deg, #030c06 0%, #061810 40%, #0a2418 70%, #0d2e20 100%)",
    accent: "#4ade80",
    // deep forest green — timeless, considered, not tied to the news cycle
  },
  callback: {
    bg: "linear-gradient(135deg, #020c10 0%, #041820 40%, #062c30 70%, #083840 100%)",
    accent: "#2dd4bf",
    // teal — completion, I called this, circle closes
  },
  video_reaction: {
    bg: "linear-gradient(135deg, #0c0318 0%, #160630 50%, #200840 80%, #180535 100%)",
    accent: "#e879f9",
    // electric magenta-purple — reaction, live energy, watching together
  },

  // ── Emotions (override format when present) ──────────────────────────────
  outrage: {
    bg: "linear-gradient(145deg, #140202 0%, #220404 40%, #300608 70%, #3a0808 100%)",
    accent: "#f87171",
  },
  curiosity: {
    bg: "linear-gradient(150deg, #030610 0%, #060e1e 45%, #0c1640 75%, #101e50 100%)",
    accent: "#818cf8",
  },
  pride: {
    bg: "linear-gradient(140deg, #0e0a00 0%, #1c1400 45%, #2a1e00 75%, #382800 100%)",
    accent: "#fcd34d",
  },
  humour: {
    bg: "linear-gradient(135deg, #080c02 0%, #121604 40%, #1c2008 70%, #242a0a 100%)",
    accent: "#bef264",
  },
  surprise: {
    bg: "linear-gradient(140deg, #020c10 0%, #041e22 45%, #063040 75%, #084050 100%)",
    accent: "#22d3ee",
  },
  validation: {
    bg: "linear-gradient(145deg, #020e06 0%, #051a0a 40%, #082810 70%, #0a3418 100%)",
    accent: "#6ee7b7",
  },
};

// Color psychology by STORY TYPE (the GPT-rules spec, Rule 9). Highest
// priority — a story's category sets the emotional palette of the background.
// Like CONTENT_THEMES, the accent here is only a SUGGESTION: a brand with a
// custom accent keeps it (theme() below), so this colours the gradient, not
// the brand. person_news/prediction/comparison/timeline/explainer intentionally
// have no entry — they keep the format/emotion palette (the photo or structure
// carries the meaning).
const STORY_THEMES = {
  // financial success → green + gold on black
  money_news:    { bg: "linear-gradient(140deg,#04100a 0%,#0a2016 40%,#13301c 70%,#1f2a08 100%)", accent: "#fbbf24" },
  achievement:   { bg: "linear-gradient(140deg,#100800 0%,#1f1200 40%,#301c00 70%,#402600 100%)", accent: "#f59e0b" },
  // breaking → red / white / black urgency
  breaking_news: { bg: "linear-gradient(145deg,#160202 0%,#2a0606 45%,#3a0808 75%,#240404 100%)", accent: "#ef4444" },
  // politics/policy → navy / white
  policy:        { bg: "linear-gradient(150deg,#03060f 0%,#070f22 45%,#0b1836 75%,#0a1530 100%)", accent: "#93c5fd" },
  // war/conflict → desaturated, dark, serious
  war_conflict:  { bg: "linear-gradient(160deg,#0a0c0e 0%,#13171c 45%,#1c2228 75%,#15191e 100%)", accent: "#94a3b8" },
  // controversy → crimson tension
  controversy:   { bg: "linear-gradient(145deg,#16040a 0%,#260818 40%,#360a22 70%,#240616 100%)", accent: "#fb7185" },
  // data → blue, ranking/numbers
  data_news:     { bg: "linear-gradient(150deg,#04060f 0%,#081226 45%,#0c1e3e 75%,#0a1830 100%)", accent: "#38bdf8" },
  // sports → energetic orange
  sports:        { bg: "linear-gradient(140deg,#120600 0%,#221000 45%,#331800 75%,#3a1c00 100%)", accent: "#fb923c" },
  // quote → purple eloquence
  quote:         { bg: "linear-gradient(135deg,#080310 0%,#12062a 40%,#180840 70%,#100530 100%)", accent: "#c084fc" },
};

// Theme for a card: STORY type (highest), then emotion, then format.
function contentTheme(format, emotion, story) {
  if (story && STORY_THEMES[story]) return STORY_THEMES[story];
  if (emotion && CONTENT_THEMES[emotion]) return CONTENT_THEMES[emotion];
  if (format && CONTENT_THEMES[format]) return CONTENT_THEMES[format];
  return null;
}

const FONT_NAMES = { sans: "Inter", serif: "Lora", mono: "JetBrains Mono" };

export function theme(brand) {
  const b = { ...DEFAULTS, ...Object.fromEntries(
    Object.entries(brand || {}).filter(([, v]) => v)) };
  const dark = b.bg_style !== "light";
  // custom = an uploaded brand font, registered by the server per render as
  // family `Custom-<key>`; stack still ends in Noto Sans for glyph fallback.
  const family = b.font_family === "custom" && b.custom_font_key
    ? `Custom-${b.custom_font_key}`
    : FONT_NAMES[b.font_family] || "Inter";

  // Content-aware identity: format + emotion → gradient + accent suggestion.
  // Brand accent_color always wins — this only fills in when the brand kit
  // has no explicit accent (i.e. still on the default #4da3ff).
  const ct = contentTheme(b.content_format, b.content_emotion, b.content_story);
  const brandHasCustomAccent = (brand || {}).accent_color &&
                                (brand || {}).accent_color !== DEFAULTS.accent_color;
  const resolvedAccent = brandHasCustomAccent ? b.accent_color
                         : (ct ? ct.accent : b.accent_color);

  // Background priority:
  //   1. light bg_style → always light (brand decision)
  //   2. content theme gradient → dark cards get emotional colour
  //   3. fallback: flat dark
  let background;
  if (!dark) {
    background = "#fafafa";
  } else if (ct) {
    background = ct.bg;
  } else {
    background = "#101319";
  }

  return {
    accent: resolvedAccent,
    secondary: b.secondary_color,
    // Noto Sans ends every stack: cross-family glyph fallback (₹ etc.)
    font: `${family}, Noto Sans`,
    fg: dark ? "#f0f2f5" : "#16181d",
    muted: dark ? "#8b94a1" : "#6b7280",
    dark,
    // panel surfaces for structured cards (comparison/framework/process)
    panel: dark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.035)",
    panelBorder: dark ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.10)",
    background,
    watermark: b.watermark_text || "",
    handle: b.handle || "",
    logo: b.logo || null,   // {src: dataURL, width, height} prepared by Python
    decor_style: b.decor_style || "subtle",  // none | subtle | bold
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

export const el = (type, style, children) => ({ type, props: {
  style, ...(children !== undefined ? { children } : {}) } });

export function accentBar(t) {
  return el("div", { width: 88, height: 10, background: t.accent, borderRadius: 5 });
}

export function footer(t) {
  const left = [];
  if (t.logo) {
    left.push({ type: "img", props: {
      src: t.logo.src, width: t.logo.width, height: t.logo.height,
      style: { width: t.logo.width, height: t.logo.height },
    } });
  }
  if (t.handle) {
    left.push(el("div", { fontSize: 26, fontWeight: 700, color: t.accent, display: "flex" },
      `@${t.handle.replace(/^@/, "")}`));
  }
  return el("div", {
    display: "flex", justifyContent: "space-between", alignItems: "center",
  }, [
    el("div", { display: "flex", alignItems: "center", gap: 14 }, left),
    el("div", { fontSize: 22, color: t.muted, display: "flex" }, t.watermark || " "),
  ]);
}

// frame: relative canvas with the decoration layer UNDER a full-bleed content
// column — decor never collides with or reflows the text.
export function frame(t, children, data = {}) {
  const decor = decorLayer(t, { style: t.decor_style,
                                icon: data.icon || null,
                                seed: data.seed || 0 });
  return el("div", {
    width: "100%", height: "100%", display: "flex", position: "relative",
    background: t.background, fontFamily: t.font,
  }, [
    ...decor,
    el("div", {
      position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
      display: "flex", flexDirection: "column", color: t.fg,
      padding: "64px 72px", justifyContent: "space-between",
    }, children),
  ]);
}

// number chip: the shared "1 2 3" marker for structured cards
export function chip(t, label, size = 42) {
  return el("div", {
    width: size, height: size, borderRadius: size, background: t.accent,
    color: "#0e1118", fontSize: size * 0.5, fontWeight: 700,
    display: "flex", alignItems: "center", justifyContent: "center",
    flexShrink: 0,
  }, String(label));
}
