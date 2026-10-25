// Optional: requires Playwright and a local Microsoft Edge installation.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdir} = require('node:fs/promises');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const child = spawn(process.env.PYTHON_EXE || 'python', [path.join(__dirname, 'ui_fixture.py')], {
    stdio: ['ignore', 'pipe', 'inherit'], windowsHide: true
  });
  let browser;
  try {
    const port = await Promise.race([
      once(child.stdout, 'data').then(([chunk]) => Number(chunk.toString().trim())),
      once(child, 'exit').then(([code]) => {throw new Error(`Fixture exited: ${code}`);})
    ]);
    assert.ok(port > 0);
    browser = await chromium.launch({channel: 'msedge', headless: true});
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}, acceptDownloads: true});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}`);
    await page.locator('#token').fill('browser-test-' + 'x'.repeat(32));
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.locator('#albums h3').waitFor();
    assert.match(await page.locator('#status').innerText(), /20 scrobbles/);
    await page.getByRole('button', {name: 'Find a forgotten favorite'}).click();
    await page.locator('#recommendation h3').waitFor();
    assert.equal(await page.locator('#recommendation h3').innerText(), 'Illinois');
    const form = page.locator('#albums .album form');
    await form.getByLabel('Spotify album link or URI').fill(
      'https://open.spotify.com/album/0S2DmRfqWM51FUprHs0qil?si=thisisnotanalbumid');
    await form.getByLabel('Tags, separated by commas').fill('indie folk');
    await form.getByRole('button').click();
    await page.locator('#albums').getByRole('link', {name:'Open confirmed album in Spotify'}).waitFor();
    assert.match(await page.locator('#status').innerText(), /1 confirmed Spotify links/);
    await page.getByLabel('Only albums with confirmed Spotify links').check();
    await page.locator('input[name="genre"]').fill('indie folk');
    const recommended = page.waitForResponse(response => response.url().includes('/api/recommend?'));
    await page.getByRole('button', {name: 'Find a forgotten favorite'}).click();
    const payload = await (await recommended).json();
    assert.equal(payload.album.spotify_uri, 'spotify:album:0S2DmRfqWM51FUprHs0qil');
    const downloaded = page.waitForEvent('download');
    await page.getByRole('button', {name:'Download backup'}).click();
    assert.equal((await downloaded).suggestedFilename(), 'scrobbles.db');
    await mkdir('.local-data', {recursive: true});
    await page.screenshot({path:'.local-data/ui-smoke.png', fullPage:true});
    await page.setViewportSize({width:390, height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole('button', {name:'Forget token'}).click();
    assert.equal(await page.locator('#albums').innerText(), '');
    assert.deepEqual(errors, []);
    console.log('Browser smoke test passed: auth, recommendation, album confirmation, tag filter, backup, mobile layout, logout.');
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
