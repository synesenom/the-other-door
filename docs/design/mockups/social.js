// Renders the social card, docs/logo/door-social.png (1280 x 640), from social.html.
// Run: node docs/design/mockups/social.js   (needs Node and `playwright` where Node finds it, as render.js does)
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');
(async () => {
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined;
  const browser = await chromium.launch({ proxy });
  const page = await browser.newPage({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(path.join(__dirname, 'social.html')).href);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(__dirname, '..', '..', 'logo', 'door-social.png') });
  console.log('wrote docs/logo/door-social.png');
  await browser.close();
})();
