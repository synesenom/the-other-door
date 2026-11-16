// node render_sealed.mjs <folder> <page.html> <out.pdf>: print a page with Chromium from a local server that
// serves only <folder>; every request to another origin is aborted (#145: this folder only).
import { createRequire } from "node:module";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = require(path.resolve(here, "../../app/node_modules/playwright"));
const [folder, html, out] = process.argv.slice(2);
const root = path.resolve(folder);
const types = { ".html": "text/html", ".svg": "image/svg+xml", ".ttf": "font/ttf", ".otf": "font/otf" };
const server = http.createServer((req, res) => {
  const file = path.resolve(root, "." + decodeURIComponent(req.url.split("?")[0]));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" });
  res.end(fs.readFileSync(file));
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 794, height: 1123 } });
  await page.route("**/*", (route) => (route.request().url().startsWith(origin + "/") ? route.continue() : route.abort()));
  await page.goto(`${origin}/${path.basename(html)}`);
  await page.waitForLoadState("networkidle");
  await page.pdf({ path: out, format: "A4", printBackground: true, preferCSSPageSize: true });
} finally {
  await browser.close();
  server.close();
}
