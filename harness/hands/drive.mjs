// plan-7862 S1: one driver ACTION per invocation, run by the executor via `docker exec`.
// The browser profile persists across actions in /profile (tmpfs: it dies with the cell).
// It goes out ONLY through HANDS_PROXY (the per-lease proxy). It reads the action as JSON on
// argv[2] and writes one JSON result line to stdout.
import { chromium } from 'playwright-core';

const act = JSON.parse(process.argv[2] || '{}');
const proxy = process.env.HANDS_PROXY;
if (!proxy) { console.log(JSON.stringify({ ok: false, error: 'no HANDS_PROXY: refusing to run unproxied' })); process.exit(2); }

const ctx = await chromium.launchPersistentContext(process.env.HANDS_PROFILE || '/profile', {
  executablePath: '/usr/bin/chromium',
  headless: false,                    // Xvfb :99; the owner's stream attaches here in S3
  proxy: { server: proxy },
  args: ['--no-first-run', '--no-default-browser-check', '--disable-dev-shm-usage'],
});
let out;
try {
  const page = ctx.pages()[0] || await ctx.newPage();
  if (act.verb === 'goto') {
    const resp = await page.goto(act.url, { timeout: 20000, waitUntil: 'domcontentloaded' });
    out = { ok: true, status: resp ? resp.status() : null, title: (await page.title()).slice(0, 200) };
  } else if (act.verb === 'cookie_set') {          // test seam: plant state in the profile
    // A PERSISTENT cookie (an expiry): a session cookie is dropped when the browser closes, and
    // every action closes it, so a session cookie would make "the profile persists" untestable.
    await ctx.addCookies([{ name: act.name, value: act.value, url: act.url,
                            expires: Math.floor(Date.now() / 1000) + 3600 }]);
    out = { ok: true };
  } else if (act.verb === 'cookies') {
    out = { ok: true, cookies: (await ctx.cookies()).map(c => ({ name: c.name, domain: c.domain })) };
  } else {
    out = { ok: false, error: `unknown verb ${act.verb}` };
  }
} catch (e) {
  out = { ok: false, error: String(e && e.message || e).slice(0, 300) };
} finally {
  await ctx.close();
}
console.log(JSON.stringify(out));
