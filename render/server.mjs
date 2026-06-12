// server.mjs — the persistent localhost render service (VISUALS.md).
//
// POST /render  {template, data, brand}  ->  image/png
// GET  /health                           ->  {"ok": true, templates: [...]}
//
// satori (flexbox layout -> SVG) + resvg (SVG -> PNG). No browser, no
// network calls out — bound to 127.0.0.1 only; the Python side spawns it
// and health-checks it (pipeline/visuals.py).

import http from "node:http";
import { readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import satori from "satori";
import { Resvg } from "@resvg/resvg-js";
import { TEMPLATES, TEMPLATE_SIZES, SIZE } from "./templates.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.VISUALS_PORT || "8787", 10);

// Fonts: pre-merged single files (latin + latin-ext) built by merge_fonts.py
// and committed in fonts/. One file per (family, weight) — satori does NOT
// fall back across multiple files of the same family, so browser-style
// subset files render tofu for anything in the -ext range (₹!). Noto Sans
// closes every font stack in templates.mjs: cross-FAMILY fallback does work,
// and Noto carries ₹ where Lora/JetBrains Mono lack the glyph entirely.
function font(file, family, weight) {
  return { name: family, data: readFileSync(join(HERE, "fonts", file)),
           weight, style: "normal" };
}

const FONTS = [
  font("Inter-400.ttf", "Inter", 400),
  font("Inter-700.ttf", "Inter", 700),
  font("Lora-400.ttf", "Lora", 400),
  font("Lora-700.ttf", "Lora", 700),
  font("JetBrainsMono-400.ttf", "JetBrains Mono", 400),
  font("JetBrainsMono-700.ttf", "JetBrains Mono", 700),
  font("NotoSans-400.ttf", "Noto Sans", 400),
  font("NotoSans-700.ttf", "Noto Sans", 700),
];

// Custom brand fonts: uploaded via the API as fonts/custom/<key>-{400,700}.ttf
// and referenced by brand.custom_font_key. Loaded lazily per render, cached by
// mtime so a re-upload takes effect without a restart. Missing files are
// simply skipped — templates' stacks end in Noto Sans, so text still renders.
const _customCache = new Map();   // path -> {mtime, font}

function customFonts(key) {
  if (!key || !/^[\w.-]+$/.test(key)) return [];
  const out = [];
  for (const weight of [400, 700]) {
    const path = join(HERE, "fonts", "custom", `${key}-${weight}.ttf`);
    try {
      const mtime = statSync(path).mtimeMs;
      const hit = _customCache.get(path);
      if (hit && hit.mtime === mtime) { out.push(hit.font); continue; }
      const f = { name: `Custom-${key}`, data: readFileSync(path),
                  weight, style: "normal" };
      _customCache.set(path, { mtime, font: f });
      out.push(f);
    } catch { /* no file for this weight — fine */ }
  }
  return out;
}

async function renderPNG(template, data, brand) {
  const build = TEMPLATES[template];
  if (!build) throw new Error(`unknown template '${template}'`);
  const size = TEMPLATE_SIZES[template] || SIZE;  // carousels are square
  const svg = await satori(build(data || {}, brand || {}), {
    ...size,
    fonts: [...customFonts((brand || {}).custom_font_key), ...FONTS],
  });
  const png = new Resvg(svg, {
    fitTo: { mode: "width", value: size.width },
  }).render().asPng();
  return png;
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, templates: Object.keys(TEMPLATES) }));
    return;
  }
  if (req.method === "POST" && req.url === "/render") {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", async () => {
      try {
        const { template, data, brand } = JSON.parse(body || "{}");
        const png = await renderPNG(template, data, brand);
        res.writeHead(200, { "Content-Type": "image/png" });
        res.end(png);
      } catch (err) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: String(err.message || err) }));
      }
    });
    return;
  }
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ ok: false, error: "not found" }));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`pulse-render listening on 127.0.0.1:${PORT}`);
});
