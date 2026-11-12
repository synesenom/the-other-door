// Renders the mockups into ../screens: desktop at 1280x800, phone at 390x844, both at 2x,
// plus phones.png, the phone screens side by side. Run: node docs/design/mockups/render.js
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');
const dir = __dirname, out = path.join(__dirname, '..', 'screens');
const DESKTOP = { width: 1280, height: 800 }, PHONE = { width: 390, height: 844 };
const SHOTS = [
  ['Main', 'matches', DESKTOP], ['Prepare', 'prepared', DESKTOP], ['Find', 'finding-jobs', DESKTOP],
  ['Applications', 'applications', DESKTOP], ['Review', 'review-dark', DESKTOP], ['Style', 'style-tile', DESKTOP],
  ['PhoneMatches', 'phone-matches', PHONE], ['PhoneMatches', 'phone-matches-dark', PHONE, '?dark=true'],
  ['PhonePosting', 'phone-posting', PHONE], ['PhonePrepared', 'phone-prepared', PHONE],
  ['PhoneFinding', 'phone-finding-jobs', PHONE], ['PhoneApplications', 'phone-applications', PHONE],
];
(async () => {
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined;
  const browser = await chromium.launch({ proxy });
  for (const [file, name, viewport, query = ''] of SHOTS) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, ignoreHTTPSErrors: true });
    const page = await ctx.newPage();
    // The unfilled template's {{holes}} make the browser complain before support.js fills them.
    page.on('console', m => m.type() === 'error' && !m.text().includes('{{') && console.log(file, m.text()));
    await page.goto(pathToFileURL(path.join(dir, file + '.dc.html')).href + query);
    await page.waitForSelector('html[data-ready]');
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(out, name + '.png') });
    console.log('wrote', name + '.png');
    await ctx.close();
  }
  // The phone strip: each phone screen as a rounded frame on the parchment ground.
  const phones = SHOTS.filter(s => s[2] === PHONE).map(s => 'data:image/png;base64,' + fs.readFileSync(path.join(out, s[1] + '.png')).toString('base64'));
  const ctx = await browser.newContext({ viewport: { width: 64 + phones.length * 414, height: 844 + 96 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.setContent('<body style="margin:0;background:#E7DABF;display:flex;gap:24px;padding:48px 32px;box-sizing:border-box">' +
    phones.map(src => `<img src="${src}" style="width:390px;height:844px;border-radius:32px;box-shadow:0 0 0 1px #D6C7A8,0 16px 40px rgba(30,26,22,.12)">`).join('') + '</body>');
  await page.evaluate(() => Promise.all([...document.images].map(i => i.decode())));
  await page.screenshot({ path: path.join(out, 'phones.png') });
  console.log('wrote phones.png');
  await browser.close();
})();
