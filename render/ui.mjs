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
  return {
    accent: b.accent_color,
    secondary: b.secondary_color,
    // Noto Sans ends every stack: cross-family glyph fallback (₹ etc.)
    font: `${family}, Noto Sans`,
    fg: dark ? "#f0f2f5" : "#16181d",
    muted: dark ? "#8b94a1" : "#6b7280",
    dark,
    // panel surfaces for structured cards (comparison/framework/process)
    panel: dark ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.035)",
    panelBorder: dark ? "rgba(255,255,255,0.09)" : "rgba(0,0,0,0.10)",
    background: b.bg_style === "gradient"
      ? `linear-gradient(135deg, #101319 0%, #1a2030 55%, ${b.accent_color}33 100%)`
      : dark ? "#101319" : "#fafafa",
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
