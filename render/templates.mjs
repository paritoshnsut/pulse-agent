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

// Editorial type system (review-driven): Playfair Display for the big display
// headline (magazine authority), Inter for tags/subheads/meta (clean, modern).
// Noto Sans closes each stack so ₹ and friends never tofu.
const DISPLAY = "Playfair Display, Noto Sans";
const SANS = "Inter, Noto Sans";
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

// --------------------------------------------------- portrait cards (V3 Step 3)
// News-desk look: a licensed portrait (resolved upstream from Wikipedia) gets a
// mandatory brand treatment — never a raw flat photo — so the feed reads as a
// designed graphic, not a scrape. hero_portrait = one subject (text left, face
// right); dual_portrait = two subjects with a "VS" badge.

// An editorial pill (the "NEW ENVOY" / "US → INDIA" tag): accent fill, dark
// text, uppercase. Falls back to a plain accent overline when used as a kicker.
function pill(t, label) {
  const base = {
    display: "flex", alignItems: "center", gap: 10, alignSelf: "flex-start",
    background: t.accent, color: "#0b0d12", fontFamily: SANS, fontSize: 24,
    fontWeight: 700, letterSpacing: 1, textTransform: "uppercase",
    padding: "8px 16px", borderRadius: 8,
  };
  // an arrow tag ("US → DELHI") renders the arrow as SVG — the merged font
  // subsets lack U+2192, so a literal arrow would tofu.
  const parts = label.split(/\s*[→➜⟶➝➔]\s*/);
  if (parts.length === 2) {
    return el("div", base, [
      el("div", { display: "flex" }, parts[0]),
      iconNode("arrow_right", 22, "#0b0d12", 1, 2.6),
      el("div", { display: "flex" }, parts[1]),
    ]);
  }
  return el("div", base, label);
}

// Headline with one phrase colour-popped (Rule 3). Rendered as wrapping word
// spans so the highlight sits inline and the line still wraps cleanly — Satori
// can't colour a substring inside a single text node.
function highlightedHeadline(text, highlight, t, fontSize) {
  const words = (text || "").split(/\s+/).filter(Boolean);
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9₹$%]/gi, "");
  const hw = (highlight || "").split(/\s+/).filter(Boolean).map(norm);
  const marked = new Set();
  if (hw.length) {
    for (let i = 0; i + hw.length <= words.length; i++) {
      if (hw.every((w, j) => norm(words[i + j]) === w)) {
        for (let j = 0; j < hw.length; j++) marked.add(i + j);
        break;
      }
    }
  }
  return el("div", {
    display: "flex", flexWrap: "wrap",
    columnGap: Math.round(fontSize * 0.27), rowGap: Math.round(fontSize * 0.1),
  }, words.map((w, i) => el("div", {
    display: "flex", fontFamily: DISPLAY, fontSize, fontWeight: 700,
    lineHeight: 1.04, color: marked.has(i) ? t.accent : t.fg,
    textShadow: "0 2px 14px rgba(0,0,0,0.5)",
  }, w)));
}

// A subtle radial vignette — darkens the edges so the card reads with depth
// instead of flat PowerPoint. Satori supports radial-gradient (verified).
function vignette(dims) {
  return el("div", {
    position: "absolute", top: 0, left: 0, width: dims.width, height: dims.height,
    background: "radial-gradient(125% 130% at 50% 30%, rgba(0,0,0,0) 50%, rgba(0,0,0,0.45) 100%)",
  });
}

export function heroPortrait(data, brand, dims = SIZE) {
  const t = theme(brand);
  const img = data.image || null;
  const headline = data.text || data.headline || "";
  const highlight = (data.highlight || "").trim();
  const sub = (data.subheadline || "").trim();
  const tag = (data.tag || "").trim();
  const overline = (data.overline || "").trim();
  const imgW = img ? Math.round(dims.width * 0.44) : 0;
  const textW = dims.width - imgW;

  // image column: a flow <img> filling a fixed box (dual_portrait's proven
  // pattern), then absolute brand-wash + bottom fade so it reads as a graphic.
  const imgCol = img
    ? el("div", { display: "flex", width: imgW, height: dims.height, position: "relative" }, [
        { type: "img", props: { src: img.src, width: imgW, height: dims.height,
          style: { width: imgW, height: dims.height, objectFit: "cover" } } },
        el("div", { position: "absolute", top: 0, left: 0, width: imgW, height: dims.height,
          background: `linear-gradient(90deg, ${t.background} 0%, rgba(0,0,0,0) 28%)` }),
        el("div", { position: "absolute", top: 0, left: 0, width: imgW, height: dims.height,
          background: `linear-gradient(180deg, rgba(8,10,14,0) 62%, rgba(8,10,14,0.5) 100%)` }),
      ])
    : null;

  const textCol = el("div", {
    display: "flex", flexDirection: "column", width: textW, height: dims.height,
    padding: "64px 56px", justifyContent: "space-between", color: t.fg,
  }, [
    el("div", { display: "flex", flexDirection: "column" }, [
      // tag pill (preferred) → plain accent overline → nothing
      tag ? pill(t, tag)
        : overline
          ? el("div", { fontSize: 28, fontWeight: 700, letterSpacing: 2,
              textTransform: "uppercase", color: t.accent, display: "flex" }, overline)
          : el("div", { display: "flex", height: 8 }),
      el("div", { display: "flex", marginTop: 22 },
        [highlightedHeadline(headline, highlight, t, fitFontSize(headline, 70, 36))]),
      sub
        ? el("div", { fontFamily: SANS, fontSize: 30, color: t.muted,
            lineHeight: 1.3, marginTop: 18, display: "flex" }, sub)
        : el("div", { display: "flex" }),
    ]),
    footer(t),
  ]);

  return el("div", { width: dims.width, height: dims.height, display: "flex",
    position: "relative", background: t.background, fontFamily: t.font }, [
    el("div", { display: "flex", width: dims.width, height: dims.height },
      imgCol ? [textCol, imgCol] : [textCol]),
    vignette(dims),
  ]);
}

export function dualPortrait(data, brand, dims = SIZE) {
  const t = theme(brand);
  const imgs = data.images || [];
  const labels = data.labels || [];
  const headline = data.text || data.headline || "";
  const highlight = (data.highlight || "").trim();
  const sub = (data.subheadline || "").trim();
  const tag = (data.tag || "").trim();
  const stripH = Math.round(dims.height * 0.64);
  const halfW = Math.round(dims.width / 2);

  const half = (asset, label) => el("div", {
    display: "flex", width: halfW, height: stripH, position: "relative",
  }, [
    asset
      ? { type: "img", props: { src: asset.src, width: halfW, height: stripH,
          style: { width: halfW, height: stripH, objectFit: "cover" } } }
      : el("div", { width: "100%", height: "100%", display: "flex", background: t.panel }),
    el("div", { position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
      background: "linear-gradient(180deg, rgba(8,10,14,0.05) 50%, rgba(8,10,14,0.88) 100%)" }),
    label
      ? el("div", { position: "absolute", bottom: 22, left: 0, width: "100%",
          display: "flex", justifyContent: "center", fontSize: 32, fontWeight: 700,
          color: "#f5f7fa" }, label)
      : el("div", { display: "flex" }),
  ]);

  const vs = el("div", {
    position: "absolute", left: halfW - 46, top: Math.round(stripH / 2) - 46,
    width: 92, height: 92, borderRadius: 46, background: t.accent,
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 34, fontWeight: 800, color: "#0b0d12",
    border: "5px solid " + t.background,
  }, "VS");

  return el("div", { width: dims.width, height: dims.height, display: "flex",
    position: "relative", background: t.background, fontFamily: t.font }, [
    el("div", { width: dims.width, height: dims.height, display: "flex",
      flexDirection: "column" }, [
      el("div", { display: "flex", position: "relative" }, [
        half(imgs[0], labels[0]), half(imgs[1], labels[1]), vs,
      ]),
      el("div", { display: "flex", flexGrow: 1, flexDirection: "column",
        padding: "32px 56px", justifyContent: "space-between", color: t.fg }, [
        el("div", { display: "flex", flexDirection: "column" }, [
          tag ? pill(t, tag) : el("div", { display: "flex" }),
          el("div", { display: "flex", marginTop: tag ? 14 : 0 },
            [highlightedHeadline(headline, highlight, t, fitFontSize(headline, 52, 30))]),
          sub
            ? el("div", { fontFamily: SANS, fontSize: 28, color: t.muted,
                lineHeight: 1.3, marginTop: 14, display: "flex" }, sub)
            : el("div", { display: "flex" }),
        ]),
        footer(t),
      ]),
    ]),
    vignette(dims),
  ]);
}

export const TEMPLATES = {
  quote_card: quoteCard,
  hero_card: heroCard,
  hero_portrait: heroPortrait,
  dual_portrait: dualPortrait,
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
