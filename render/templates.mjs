// templates.mjs — the visual template library. THE durable asset (VISUALS.md):
// renderers come and go; these layouts + the brand injection are what we keep.
//
// Templates are Satori element trees (plain objects — satori's JSX-free form:
// { type, props: { style, children } }). Every template takes (data, brand)
// where brand carries accent/secondary colors, bg style, font family and
// watermark from the account's brand kit, with tasteful defaults when unset.
//
// The library is split by concern:
//   ui.mjs         — theme/brand mapping + shared primitives (frame, footer…)
//   icons.mjs      — topic icons + decorative geometry
//   art.mjs        — seeded procedural backgrounds
//   charts.mjs     — bar/line data visualization
//   blueprints.mjs — structured idea visuals (comparison/framework/timeline/
//                    process/list) extracted by pipeline/blueprint.py
//   this file      — the core cards + carousel + the TEMPLATES registry

import { SIZE, SQUARE, theme, el, accentBar, footer, frame,
         fitFontSize } from "./ui.mjs";
import { decorLayer, iconNode } from "./icons.mjs";
import { artLayers } from "./art.mjs";
import { chartNode } from "./charts.mjs";
import { BLUEPRINT_TEMPLATES } from "./blueprints.mjs";

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
  ], data);
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
  ], data);
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
  ], data);
}

// --------------------------------------------------------------- chart card
// Real data visualization: headline + a bar/line chart drawn from the spec
// Python extracted (and cached on the post). The chart IS the message; the
// decor layer stays off so nothing competes with the data.
export function chartCard(data, brand, dims = SIZE) {
  const t = theme(brand);
  const title = data.title || data.text || "";
  const chartW = dims.width - 144;            // frame padding is 72 each side
  const chartH = Math.min(Math.round(dims.height * 0.49), 560);
  return frame({ ...t, decor_style: "none" }, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1,
                justifyContent: "center" }, [
      el("div", {
        fontSize: fitFontSize(title, 44, 28), fontWeight: 700, lineHeight: 1.2,
        marginBottom: 30, display: "flex",
      }, title),
      chartNode({ kind: data.kind || "bar", labels: data.labels || [],
                  values: data.values || [], unit: data.unit || "" },
                t, { width: chartW, height: chartH }),
      data.source ? el("div", {
        fontSize: 20, color: t.muted, marginTop: 14, display: "flex",
      }, `Source: ${data.source}`) : el("div", { display: "flex" }),
    ]),
    footer(t),
  ], data);
}

// --------------------------------------------------------------- hero card
// The V2 composite (VISUALS.md): an imagery layer underneath (AI-generated or
// an approved library background, prepared by Python as a sized data-URL) with
// the deterministic Satori text/brand layer on top — "designed" richness
// without trusting an image model to spell. Text sits on a darkening scrim,
// so the foreground is always light regardless of the kit's bg_style.
// No image -> seeded procedural art (art.mjs), never a flat gradient.
export function heroCard(data, brand, dims = SIZE) {
  const t = theme(brand);
  const text = data.text || "";
  const img = data.image || null;  // {src: dataURL, width, height} or null
  const layers = [];
  if (img) {
    layers.push({ type: "img", props: {
      src: img.src, width: dims.width, height: dims.height,
      style: { position: "absolute", top: 0, left: 0,
               width: dims.width, height: dims.height, objectFit: "cover" },
    } });
  } else {
    layers.push(...artLayers(data.seed || 0, t.accent, t.secondary,
                             dims.width, dims.height));
  }
  // photos need a strong scrim for text contrast; procedural art is already
  // dark, so a soft one keeps the composition from flattening to black.
  const scrim = img
    ? "linear-gradient(180deg, rgba(8,10,14,0.20) 0%, rgba(8,10,14,0.78) 100%)"
    : "linear-gradient(180deg, rgba(8,10,14,0.05) 0%, rgba(8,10,14,0.45) 100%)";
  layers.push(el("div", {
    position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
    background: scrim,
    display: "flex",
  }));
  const overlayT = { ...t, fg: "#f5f7fa", muted: "rgba(245,247,250,0.75)" };
  layers.push(el("div", {
    position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
    display: "flex", flexDirection: "column", color: overlayT.fg,
    padding: "64px 72px", justifyContent: "space-between",
  }, [
    accentBar(overlayT),
    el("div", {
      fontSize: fitFontSize(text, 64, 34), fontWeight: 700, lineHeight: 1.22,
      display: "flex", flexGrow: 1, alignItems: "flex-end",
      paddingBottom: 36, textShadow: "0 2px 12px rgba(0,0,0,0.55)",
    }, text),
    footer(overlayT),
  ]));
  return el("div", {
    width: "100%", height: "100%", display: "flex", position: "relative",
    fontFamily: t.font,
  }, layers);
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

// square frame with decor — same layering as frame() but carousel padding
function squareFrame(t, children, data = {}) {
  const decor = decorLayer(t, { style: t.decor_style,
                                icon: data.icon || null,
                                seed: (data.seed || 0) + (data.index || 0) });
  return el("div", {
    width: "100%", height: "100%", display: "flex", position: "relative",
    background: t.background, fontFamily: t.font,
  }, [
    ...decor,
    el("div", {
      position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
      display: "flex", flexDirection: "column", color: t.fg,
      padding: "72px", justifyContent: "space-between",
    }, children),
  ]);
}

export function carouselCover(data, brand) {
  const t = theme(brand);
  const text = data.text || "";
  return squareFrame(t, [
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
      // arrow is SVG, not a text glyph (the merged subsets lack U+2192)
      el("div", { display: "flex", alignItems: "center", gap: 10 }, [
        el("div", { fontSize: 28, color: t.muted, display: "flex" }, "swipe"),
        iconNode("arrow_right", 28, t.muted, 1, 2.2),
      ]),
    ]),
  ], data);
}

export function carouselSlide(data, brand) {
  const t = theme(brand);
  const text = data.text || "";
  const head = (data.headline || "").trim();
  // narrative slides lead with their own scannable headline; plain split
  // slides keep the single text block.
  const body = head
    ? el("div", { display: "flex", flexDirection: "column", flexGrow: 1,
                  justifyContent: "center" }, [
        el("div", { fontSize: fitFontSize(head, 58, 38), fontWeight: 700,
                    lineHeight: 1.15, display: "flex" }, head),
        text ? el("div", { fontSize: 32, lineHeight: 1.4, color: t.muted,
                           marginTop: 30, display: "flex" }, text)
             : el("div", { display: "flex" }),
      ])
    : el("div", {
        fontSize: fitFontSize(text, 52, 32), fontWeight: 600, lineHeight: 1.32,
        display: "flex", flexGrow: 1, alignItems: "center",
      }, text);
  return squareFrame(t, [
    slideCounter(t, data.index, data.total),
    body,
    footer(t),
  ], data);
}

export function carouselCta(data, brand) {
  const t = theme(brand);
  const cta = data.cta_text
    || (t.handle ? `Follow @${t.handle.replace(/^@/, "")} for more` : "Thanks for reading");
  return squareFrame(t, [
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
  ], data);
}

export const TEMPLATES = {
  quote_card: quoteCard,
  hero_card: heroCard,
  stat_highlight: statHighlight,
  insight_card: insightCard,
  chart_card: chartCard,
  carousel_cover: carouselCover,
  carousel_slide: carouselSlide,
  carousel_cta: carouselCta,
  ...BLUEPRINT_TEMPLATES,
};

export const TEMPLATE_SIZES = {
  carousel_cover: SQUARE,
  carousel_slide: SQUARE,
  carousel_cta: SQUARE,
};

export { SIZE, fitFontSize };
