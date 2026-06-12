// blueprints.mjs — the structured visual templates (VISUALS.md "visual
// intelligence"). These are what top creators actually post: comparisons,
// frameworks, timelines, process flows, lists — ideas given SHAPE, not text
// on a gradient. Claude extracts the typed blueprint (pipeline/blueprint.py);
// these layouts own every pixel deterministically.
//
// All 16:9. Decor stays off — structured cards are already visually dense;
// nothing may compete with the structure.

import { theme, el, accentBar, footer, frame, fitFontSize, chip } from "./ui.mjs";
import { iconNode } from "./icons.mjs";

const noDecor = (t) => ({ ...t, decor_style: "none" });

function title(t, text, marginBottom = 36) {
  return el("div", {
    fontSize: fitFontSize(text, 42, 30), fontWeight: 700, lineHeight: 1.15,
    marginBottom, display: "flex",
  }, text);
}

// ------------------------------------------------------------- comparison
// Left vs right. The right side is "yours" — it gets the accent treatment;
// the left stays neutral. A centered "vs" chip joins the panels.
export function comparisonCard(data, brand) {
  const t = noDecor(theme(brand));
  // markers are SVG, never text glyphs — the merged font subsets don't carry
  // ✓/✕ and Satori renders missing glyphs as tofu.
  const point = (text, marker, color, last) => el("div", {
    display: "flex", alignItems: "flex-start", marginBottom: last ? 0 : 16,
  }, [
    el("div", { marginRight: 14, marginTop: 4, display: "flex",
                flexShrink: 0 },
       [iconNode(marker, 22, color, 1, 2.6)]),
    el("div", { fontSize: 23, lineHeight: 1.35, display: "flex", flexGrow: 1 },
       text),
  ]);
  const panel = (head, points, accent) => el("div", {
    display: "flex", flexDirection: "column", flexGrow: 1, flexBasis: 0,
    background: accent ? `${t.accent}14` : t.panel,
    border: `1px solid ${accent ? `${t.accent}66` : t.panelBorder}`,
    borderRadius: 22, padding: "30px 34px",
  }, [
    el("div", { fontSize: 28, fontWeight: 700, marginBottom: 22,
                color: accent ? t.accent : t.muted, display: "flex" }, head),
    ...points.map((p, i) => point(p, accent ? "check" : "x",
                                  accent ? t.accent : t.muted,
                                  i === points.length - 1)),
  ]);
  return frame(t, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1,
                justifyContent: "center" }, [
      title(t, data.title),
      el("div", { display: "flex", alignItems: "stretch" }, [
        panel(data.left_title, data.left_points || [], false),
        el("div", { width: 76, display: "flex", alignItems: "center",
                    justifyContent: "center", flexShrink: 0 }, [
          el("div", {
            width: 56, height: 56, borderRadius: 56, background: "#101319",
            border: `2px solid ${t.accent}`, color: t.accent,
            fontSize: 21, fontWeight: 700, display: "flex",
            alignItems: "center", justifyContent: "center",
          }, "vs"),
        ]),
        panel(data.right_title, data.right_points || [], true),
      ]),
    ]),
    footer(t),
  ], data);
}

// -------------------------------------------------------------- framework
// 3-5 named pillars of one idea, numbered, in a row of equal cards.
export function frameworkCard(data, brand) {
  const t = noDecor(theme(brand));
  const items = data.items || [];
  const n = items.length || 1;
  const labelSize = n >= 5 ? 22 : 25;
  const descSize = n >= 5 ? 18 : 20;
  const cards = items.map((it, i) => el("div", {
    display: "flex", flexDirection: "column", flexGrow: 1, flexBasis: 0,
    background: t.panel, border: `1px solid ${t.panelBorder}`,
    borderRadius: 20, padding: n >= 5 ? "24px 22px" : "28px 28px",
    marginRight: i < n - 1 ? 20 : 0,
  }, [
    chip(t, i + 1, 42),
    el("div", { fontSize: labelSize, fontWeight: 700, marginTop: 20,
                lineHeight: 1.2, display: "flex" }, it.label),
    it.desc ? el("div", { fontSize: descSize, color: t.muted, marginTop: 12,
                          lineHeight: 1.35, display: "flex" }, it.desc)
            : el("div", { display: "flex" }),
  ]));
  return frame(t, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1,
                justifyContent: "center" }, [
      title(t, data.title),
      el("div", { display: "flex", alignItems: "stretch" }, cards),
    ]),
    footer(t),
  ], data);
}

// --------------------------------------------------------------- timeline
// 3-6 dated milestones on a horizontal rail; the latest one is "now" and
// gets the filled accent dot.
export function timelineCard(data, brand) {
  const t = noDecor(theme(brand));
  const ms = data.milestones || [];
  const n = ms.length || 1;
  const W = 1056;                       // content width inside frame padding
  const colW = W / n;
  const dotY = 64;                      // center line of the dot row
  const cols = ms.map((m, i) => {
    const last = i === n - 1;
    return el("div", {
      display: "flex", flexDirection: "column", alignItems: "center",
      width: colW, textAlign: "center",
    }, [
      el("div", { fontSize: n >= 5 ? 24 : 27, fontWeight: 700,
                  color: last ? t.accent : t.fg, height: 44,
                  display: "flex" }, m.period),
      el("div", { height: 40, display: "flex", alignItems: "center",
                  justifyContent: "center" }, [
        el("div", {
          width: last ? 22 : 18, height: last ? 22 : 18,
          borderRadius: 22, display: "flex",
          background: last ? t.accent : "#101319",
          border: `3px solid ${t.accent}`,
        }),
      ]),
      el("div", { fontSize: n >= 5 ? 18 : 20, color: t.muted, marginTop: 14,
                  lineHeight: 1.35, display: "flex",
                  padding: "0 10px", justifyContent: "center" }, m.text),
    ]);
  });
  return frame(t, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1,
                justifyContent: "center" }, [
      title(t, data.title, 44),
      el("div", { position: "relative", display: "flex", width: W }, [
        // the rail: from the first dot's center to the last dot's center
        el("div", {
          position: "absolute", top: dotY - 2, left: colW / 2,
          width: W - colW, height: 4, background: `${t.accent}59`,
          display: "flex",
        }),
        ...cols,
      ]),
    ]),
    footer(t),
  ], data);
}

// ---------------------------------------------------------------- process
// 3-5 sequential steps joined by arrows. Same pillar cards as framework,
// but the arrow makes the ORDER the message.
export function processCard(data, brand) {
  const t = noDecor(theme(brand));
  const steps = data.steps || [];
  const n = steps.length || 1;
  const labelSize = n >= 5 ? 21 : 24;
  const row = [];
  steps.forEach((s, i) => {
    row.push(el("div", {
      display: "flex", flexDirection: "column", alignItems: "center",
      flexGrow: 1, flexBasis: 0,
      background: t.panel, border: `1px solid ${t.panelBorder}`,
      borderRadius: 20, padding: n >= 5 ? "26px 18px" : "30px 24px",
      textAlign: "center",
    }, [
      chip(t, i + 1, 44),
      el("div", { fontSize: labelSize, fontWeight: 700, marginTop: 18,
                  lineHeight: 1.2, display: "flex",
                  justifyContent: "center" }, s.label),
      s.desc ? el("div", { fontSize: n >= 5 ? 17 : 19, color: t.muted,
                           marginTop: 10, lineHeight: 1.3, display: "flex",
                           justifyContent: "center" }, s.desc)
             : el("div", { display: "flex" }),
    ]));
    if (i < n - 1) {
      row.push(el("div", {
        width: n >= 5 ? 36 : 46, display: "flex", alignItems: "center",
        justifyContent: "center", flexShrink: 0,
      }, [iconNode("arrow_right", n >= 5 ? 26 : 32, t.accent, 1, 2.4)]));
    }
  });
  return frame(t, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1,
                justifyContent: "center" }, [
      title(t, data.title),
      el("div", { display: "flex", alignItems: "stretch" }, row),
    ]),
    footer(t),
  ], data);
}

// ------------------------------------------------------------------- list
// 3-6 numbered tips/mistakes/rules. The title is the hook; the rows scan.
export function listCard(data, brand) {
  const t = noDecor(theme(brand));
  const items = data.items || [];
  const n = items.length || 1;
  const size = n >= 5 ? 23 : 26;
  const pad = n >= 5 ? 16 : 22;
  const rows = items.map((it, i) => el("div", {
    display: "flex", alignItems: "center",
    padding: `${pad}px 0`,
    borderBottom: i < n - 1 ? `1px solid ${t.panelBorder}` : "none",
  }, [
    chip(t, i + 1, n >= 5 ? 36 : 40),
    el("div", { fontSize: size, lineHeight: 1.3, marginLeft: 24,
                display: "flex", flexGrow: 1 }, it),
  ]));
  return frame(t, [
    accentBar(t),
    el("div", { display: "flex", flexDirection: "column", flexGrow: 1,
                justifyContent: "center" }, [
      title(t, data.title, 28),
      el("div", { display: "flex", flexDirection: "column" }, rows),
    ]),
    footer(t),
  ], data);
}

export const BLUEPRINT_TEMPLATES = {
  comparison_card: comparisonCard,
  framework_card: frameworkCard,
  timeline_card: timelineCard,
  process_card: processCard,
  list_card: listCard,
};
