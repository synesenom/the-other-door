// node render.mjs <page.html> <out.pdf|out.png>: print a page with Chromium (Playwright from app/node_modules).
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = require(path.resolve(here, "../../app/node_modules/playwright"));
const [html, out] = process.argv.slice(2);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 794, height: 1123 } });
  await page.goto("file://" + path.resolve(html));
  if (out.endsWith(".png")) await page.screenshot({ path: out, fullPage: true });
  else await page.pdf({ path: out, format: "A4", printBackground: true, preferCSSPageSize: true });
} finally {
  await browser.close();
}
