// art.mjs — procedural backgrounds (VISUALS.md: the keyless fix for the
// empty-library hero card). Seeded compositions of layered gradients in the
// brand's palette: orbs, mesh corners, beams, horizon. Deterministic — the
// same (seed, accent) always renders the same art, so a regenerate doesn't
// reshuffle a card the user already approved.
//
// Everything is absolutely-positioned divs with single gradients (Satori
// supports one gradient per background; layering is ours). No blur filters
// (unsupported) — radial fade to transparent does the softening.

function mulberry32(seed) {
  let a = (seed >>> 0) || 1;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const abs = (style) => ({ type: "div", props: { style: {
  position: "absolute", display: "flex", ...style } } });

function orb(color, x, y, size, alpha) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, "0");
  return abs({
    left: x - size / 2, top: y - size / 2, width: size, height: size,
    background: `radial-gradient(circle at 50% 50%, ${color}${a} 0%, ${color}00 70%)`,
  });
}

const BASE = "#0e1118";

// variant builders: (rnd, accent, secondary, W, H) -> [layers]
const VARIANTS = [
  // 0 — orbs: 3-4 soft glows drifting around the edges
  (rnd, accent, secondary, W, H) => {
    const layers = [];
    const n = 3 + Math.floor(rnd() * 2);
    for (let i = 0; i < n; i++) {
      const color = i % 2 ? secondary : accent;
      layers.push(orb(color, rnd() * W, rnd() * H,
                      W * (0.45 + rnd() * 0.5), 0.16 + rnd() * 0.14));
    }
    return layers;
  },
  // 1 — mesh: a glow pinned in each of three corners
  (rnd, accent, secondary, W, H) => [
    orb(accent, 0, 0, W * 0.9, 0.20 + rnd() * 0.08),
    orb(secondary, W, H * (0.3 + rnd() * 0.4), W * 0.8, 0.14 + rnd() * 0.08),
    orb(accent, W * (0.2 + rnd() * 0.5), H, W * 0.85, 0.16 + rnd() * 0.10),
  ],
  // 2 — beams: two wide diagonal light bars
  (rnd, accent, secondary, W, H) => {
    const mk = (color, top, alpha, angle) => {
      const a = Math.round(alpha * 255).toString(16).padStart(2, "0");
      return abs({
        left: -W * 0.25, top, width: W * 1.5, height: H * 0.32,
        background: `linear-gradient(90deg, ${color}00 0%, ${color}${a} 50%, ${color}00 100%)`,
        transform: `rotate(${angle}deg)`,
      });
    };
    return [
      mk(accent, H * (0.05 + rnd() * 0.25), 0.22, -(8 + rnd() * 10)),
      mk(secondary, H * (0.5 + rnd() * 0.3), 0.16, -(8 + rnd() * 10)),
    ];
  },
  // 3 — horizon: gradient floor + one rising glow (sunrise energy)
  (rnd, accent, secondary, W, H) => [
    abs({ left: 0, top: H * 0.55, width: W, height: H * 0.45,
          background: `linear-gradient(180deg, ${accent}00 0%, ${accent}4d 100%)` }),
    orb(accent, W * (0.3 + rnd() * 0.4), H * 0.62, W * 0.7, 0.45),
    orb(secondary, W * 0.85, H * 0.15, W * 0.45, 0.20),
  ],
];

// The full background stack for a card: base coat + seeded composition.
export function artLayers(seed, accent, secondary, W, H) {
  const rnd = mulberry32(seed || 1);
  const variant = VARIANTS[Math.abs(seed || 0) % VARIANTS.length];
  return [
    abs({ left: 0, top: 0, width: W, height: H, background: BASE }),
    ...variant(rnd, accent || "#4da3ff", secondary || "#9aa4b2", W, H),
  ];
}
