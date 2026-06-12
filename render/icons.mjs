// icons.mjs — the bundled topic-icon set + decorative geometry (VISUALS.md
// "illustration layer"). Stroke icons as plain path data (24x24 viewBox,
// lucide-style), rendered inline as Satori SVG nodes — no image fetches, no
// dependencies, deterministic forever.
//
// Python picks the icon name per post (topic/format keywords); templates place
// it as a large low-opacity glyph so cards stop being typography-only without
// ever competing with the text.

const P = (d) => ({ kind: "path", d });
const C = (cx, cy, r) => ({ kind: "circle", cx, cy, r });

// Every icon: array of primitives. Kept deliberately simple — these render at
// low opacity as decoration, not at 24px in a toolbar.
export const ICONS = {
  trending_up: [P("M2 17l6.5-6.5 5 5L22 7"), P("M15 7h7v7")],
  trending_down: [P("M2 7l6.5 6.5 5-5L22 17"), P("M15 17h7v-7")],
  bar_chart: [P("M3 21h18"), P("M7 21V9"), P("M13 21V3"), P("M19 21v-7")],
  landmark: [P("M3 21h18"), P("M5 21v-9"), P("M9 21v-9"), P("M15 21v-9"),
             P("M19 21v-9"), P("M2 12L12 4l10 8")],
  scale: [P("M12 3v18"), P("M8 21h8"), P("M4 7h16"),
          P("M6 7l-3 6a3 3 0 0 0 6 0L6 7z"), P("M18 7l-3 6a3 3 0 0 0 6 0l-3-6z")],
  megaphone: [P("M3 10l15-6v16L3 14v-4z"), P("M7 14v4a2 2 0 0 0 4 1"),
              P("M21 10v4")],
  globe: [C(12, 12, 10), P("M2 12h20"),
          P("M12 2a15 15 0 0 1 0 20a15 15 0 0 1 0-20")],
  zap: [P("M13 2L3 14h9l-1 8 10-12h-9l1-8z")],
  calendar: [P("M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7z"),
             P("M16 3v4"), P("M8 3v4"), P("M4 11h16")],
  target: [C(12, 12, 10), C(12, 12, 6), C(12, 12, 2)],
  briefcase: [P("M4 8h16v12H4z"), P("M9 8V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v3"),
              P("M4 13h16")],
  coins: [C(9, 9, 6), C(15, 15, 6)],
  trophy: [P("M8 21h8"), P("M12 17v4"), P("M7 4h10v6a5 5 0 0 1-10 0V4z"),
           P("M7 6H4a3 3 0 0 0 3 5"), P("M17 6h3a3 3 0 0 1-3 5")],
  film: [P("M4 4h16v16H4z"), P("M4 9h16"), P("M4 15h16"), P("M9 4v16"),
         P("M15 4v16")],
  mic: [P("M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z"),
        P("M5 11a7 7 0 0 0 14 0"), P("M12 18v4")],
  message_square: [P("M4 4h16v12H8l-4 4V4z")],
  book: [P("M4 19a2.5 2.5 0 0 1 2.5-2.5H20V3H6.5A2.5 2.5 0 0 0 4 5.5V19z"),
         P("M4 19a2.5 2.5 0 0 0 2.5 2.5H20")],
  shield: [P("M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z")],
  heart: [P("M12 21C7 16.5 3 13 3 8.5A4.5 4.5 0 0 1 12 6a4.5 4.5 0 0 1 9 2.5c0 4.5-4 8-9 12.5z")],
  cpu: [P("M5 5h14v14H5z"), P("M9 9h6v6H9z"), P("M12 2v3"), P("M12 19v3"),
        P("M2 12h3"), P("M19 12h3")],
  leaf: [P("M6 21c0-9 4-15 14-17-1 10-6 15-14 15"), P("M6 21c2-5 6-9 11-11")],
  flame: [P("M12 2c1 4 5 6 5 11a5 5 0 0 1-10 0c0-2 1-4 2-5 0 2 1 3 2 3-1-3 0-7 1-9z")],
  check: [P("M5 12l4 4L19 6")],
  users: [C(9, 8, 3.5), P("M2 21a7 7 0 0 1 14 0"), P("M16 4a4 4 0 0 1 0 8"),
          P("M17 14a7 7 0 0 1 5 7")],
};

// One icon as a Satori SVG node. size in px; color any CSS color string.
export function iconNode(name, size, color, opacity = 1, strokeWidth = 1.6) {
  const prims = ICONS[name];
  if (!prims) return null;
  return {
    type: "svg",
    props: {
      viewBox: "0 0 24 24", width: size, height: size,
      style: { opacity },
      children: prims.map((p) => p.kind === "circle"
        ? { type: "circle", props: { cx: p.cx, cy: p.cy, r: p.r, stroke: color,
                                     strokeWidth, fill: "none" } }
        : { type: "path", props: { d: p.d, stroke: color, strokeWidth,
                                   fill: "none", strokeLinecap: "round",
                                   strokeLinejoin: "round" } }),
    },
  };
}

// ----------------------------------------------------- decorative geometry
// Variants picked by seed so a feed of cards doesn't repeat one motif.
// All absolutely positioned and non-interactive with the text column.

function abs(style, children) {
  return { type: "div", props: { style: { position: "absolute", display: "flex",
                                          ...style }, ...(children ? { children } : {}) } };
}

export function dotGrid(color, opacity, { right = 56, top = 56 } = {}) {
  const rows = [];
  for (let r = 0; r < 4; r++) {
    const dots = [];
    for (let c = 0; c < 6; c++) {
      dots.push({ type: "div", props: { style: {
        width: 5, height: 5, borderRadius: 3, background: color,
        marginRight: c < 5 ? 16 : 0, display: "flex" } } });
    }
    rows.push({ type: "div", props: { style: {
      display: "flex", marginBottom: r < 3 ? 16 : 0 }, children: dots } });
  }
  return abs({ right, top, flexDirection: "column", opacity }, rows);
}

export function accentRing(color, opacity, { size = 340, right = -110, bottom = -110 } = {}) {
  return abs({
    right, bottom, width: size, height: size, borderRadius: size,
    border: `3px solid ${color}`, opacity,
  });
}

export function beam(color, opacity, { width = 480, top = -80, right = -120, angle = 35 } = {}) {
  return abs({
    top, right, width, height: 150,
    background: `linear-gradient(90deg, ${color}00 0%, ${color} 50%, ${color}00 100%)`,
    opacity, transform: `rotate(${angle}deg)`,
  });
}

// The composed decoration layer for a card. style: "none" | "subtle" | "bold".
// seed varies the motif; icon (when known) anchors bottom-right.
export function decorLayer(t, { style = "subtle", icon = null, seed = 0 } = {}) {
  if (style === "none") return [];
  const o = style === "bold" ? { icon: 0.22, geo: 0.5 } : { icon: 0.10, geo: 0.25 };
  const layers = [];
  const motif = Math.abs(seed) % 3;
  if (motif === 0) layers.push(dotGrid(t.secondary, o.geo));
  else if (motif === 1) layers.push(accentRing(t.accent, o.geo * 0.6));
  else layers.push(beam(t.accent, o.geo * 0.45));
  if (icon && ICONS[icon]) {
    layers.push(abs({ right: 64, bottom: 96 },
      [iconNode(icon, 132, t.accent, o.icon)]));
  }
  return layers;
}
