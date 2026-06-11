// server.mjs — the persistent localhost render service (VISUALS.md).
//
// POST /render  {template, data, brand}  ->  image/png
// GET  /health                           ->  {"ok": true, templates: [...]}
//
// satori (flexbox layout -> SVG) + resvg (SVG -> PNG). No browser, no
// network calls out — bound to 127.0.0.1 only; the Python side spawns it
// and health-checks it (pipeline/visuals.py).

import http from "node:http";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import satori from "satori";
import { Resvg } from "@resvg/resvg-js";
import { TEMPLATES, TEMPLATE_SIZES, SIZE } from "./templates.mjs";

const require = createRequire(import.meta.url);
const PORT = parseInt(process.env.VISUALS_PORT || "8787", 10);

function font(pkg, file, family, weight) {
  return {
    name: family,
    data: readFileSync(require.resolve(`${pkg}/files/${file}`)),
    weight,
    style: "normal",
  };
}

const FONTS = [
  font("@fontsource/inter", "inter-latin-400-normal.woff", "Inter", 400),
  font("@fontsource/inter", "inter-latin-700-normal.woff", "Inter", 700),
  font("@fontsource/lora", "lora-latin-400-normal.woff", "Lora", 400),
  font("@fontsource/lora", "lora-latin-700-normal.woff", "Lora", 700),
  font("@fontsource/jetbrains-mono", "jetbrains-mono-latin-400-normal.woff", "JetBrains Mono", 400),
  font("@fontsource/jetbrains-mono", "jetbrains-mono-latin-700-normal.woff", "JetBrains Mono", 700),
];

async function renderPNG(template, data, brand) {
  const build = TEMPLATES[template];
  if (!build) throw new Error(`unknown template '${template}'`);
  const size = TEMPLATE_SIZES[template] || SIZE;  // carousels are square
  const svg = await satori(build(data || {}, brand || {}), {
    ...size,
    fonts: FONTS,
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
