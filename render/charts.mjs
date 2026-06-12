// charts.mjs — deterministic data visualization (VISUALS.md: "the post says
// GDP trended up since 2019 — show the chart, not just the sentence").
//
// Geometry only: Python supplies a validated spec {kind, labels, values,
// unit?}; this module turns it into Satori nodes. Bars are pure flexbox
// (the most reliable layout primitive Satori has); lines are one inline SVG
// path with the value labels as absolutely-positioned divs, because Satori
// doesn't render <text> inside SVG.

const el = (type, style, children) => ({ type, props: {
  style, ...(children !== undefined ? { children } : {}) } });

function fmt(v, unit) {
  const n = Math.abs(v) >= 1000
    ? v.toLocaleString("en-IN")
    : (Math.round(v * 100) / 100).toString();
  return unit ? (unit === "%" ? `${n}%` : `${unit}${n}`) : n;
}

// ------------------------------------------------------------- bar chart
export function barChart(spec, t, { width = 1056, height = 360 } = {}) {
  const values = spec.values, labels = spec.labels;
  const max = Math.max(...values, 0) || 1;
  const usable = height - 76;                    // value label + x label rows
  const cols = values.map((v, i) => {
    const h = Math.max(6, Math.round((v / max) * usable));
    const last = i === values.length - 1;        // the "now" bar pops in accent
    return el("div", {
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "flex-end", flexGrow: 1, height,
      marginRight: i < values.length - 1 ? 18 : 0,
    }, [
      el("div", { fontSize: 24, fontWeight: 700, marginBottom: 8,
                  color: last ? t.accent : t.fg, display: "flex" },
         fmt(v, spec.unit)),
      el("div", { width: "100%", height: h, borderRadius: 8, display: "flex",
                  background: last ? t.accent : `${t.accent}55` }),
      el("div", { fontSize: 21, color: t.muted, marginTop: 10, display: "flex" },
         String(labels[i] ?? "")),
    ]);
  });
  return el("div", { display: "flex", width, height, alignItems: "flex-end" }, cols);
}

// ------------------------------------------------------------ line chart
export function lineChart(spec, t, { width = 1056, height = 360 } = {}) {
  const values = spec.values, labels = spec.labels, n = values.length;
  const padX = 24, padTop = 56, padBottom = 44;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = (hi - lo) || 1;
  const px = (i) => padX + (i * (width - 2 * padX)) / (n - 1);
  const py = (v) => padTop + (1 - (v - lo) / span) * (height - padTop - padBottom);
  const pts = values.map((v, i) => [px(i), py(v)]);

  const line = "M" + pts.map(([x, y]) => `${x} ${y}`).join(" L");
  const area = line + ` L${px(n - 1)} ${height - padBottom}` +
               ` L${px(0)} ${height - padBottom} Z`;
  const svg = {
    type: "svg",
    props: {
      viewBox: `0 0 ${width} ${height}`, width, height,
      style: { position: "absolute", top: 0, left: 0 },
      children: [
        { type: "path", props: { d: area, fill: `${t.accent}26` } },
        { type: "path", props: { d: line, stroke: t.accent, strokeWidth: 5,
                                 fill: "none", strokeLinecap: "round",
                                 strokeLinejoin: "round" } },
        ...pts.map(([x, y], i) => ({ type: "circle", props: {
          cx: x, cy: y, r: i === n - 1 ? 9 : 6,
          fill: i === n - 1 ? t.accent : "#0e1118",
          stroke: t.accent, strokeWidth: 3 } })),
      ],
    },
  };
  // value labels above each point (every point when few; ends + peak when many)
  const want = n <= 7 ? pts.map((_, i) => i)
    : [0, values.indexOf(hi), n - 1].filter((v, i, a) => a.indexOf(v) === i);
  const valueLabels = want.map((i) => el("div", {
    position: "absolute", left: px(i) - 60, top: py(values[i]) - 42, width: 120,
    fontSize: 23, fontWeight: 700, justifyContent: "center", display: "flex",
    color: i === n - 1 ? t.accent : t.fg,
  }, fmt(values[i], spec.unit)));
  const xLabels = el("div", {
    position: "absolute", left: 0, top: height - 32, width, display: "flex",
    justifyContent: "space-between", padding: `0 ${padX - 14}px`,
  }, labels.map((l) => el("div", { fontSize: 21, color: t.muted,
                                   display: "flex" }, String(l ?? ""))));
  return el("div", { position: "relative", width, height, display: "flex" },
            [svg, ...valueLabels, xLabels]);
}

export function chartNode(spec, t, opts) {
  return spec.kind === "line" ? lineChart(spec, t, opts) : barChart(spec, t, opts);
}
