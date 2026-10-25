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
    await page.waitForFunction(() => document.querySelector('#status').textContent.includes('1 confirmed Spotify links'));
    assert.match(await page.locator('#status').innerText(), /1 confirmed Spotify links/);
    await page.getByLabel('Only albums with confirmed Spotify links').check();
    await page.locator('#genres').getByRole('button', {name:'indie folk (1)', exact:true}).click();
    assert.equal(await page.locator('input[name="genre"]').inputValue(), 'indie folk');
    assert.equal(await page.locator('#genres button[aria-pressed="true"]').innerText(), 'indie folk (1)');
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
    // Exercise the custom card with HA state/service doubles; no playback is sent.
    const musicPage = await browser.newPage({viewport: {width: 1050, height: 1000}});
    musicPage.on('pageerror', error => errors.push(error.message));
    // HA has its own document/CSP; do not inherit the app's strict no-inline-style policy.
    await musicPage.setContent('<!doctype html><html lang="en"><body></body></html>');
    await musicPage.addScriptTag({url: `http://127.0.0.1:${port}/lastfm-music-card.js`});
    const albumResponse = await page.request.get(`http://127.0.0.1:${port}/api/albums`, {
      headers: {Authorization: 'Bearer browser-test-' + 'x'.repeat(32)}
    });
    const albumForCard = (await albumResponse.json()).albums[0];
    await musicPage.evaluate(async ({album}) => {
      const folk = {name: 'indie folk', album_count: 1, playable_album_count: 1, context_scrobbles: 8, context_score: 2};
      const metal = {name: 'metal', album_count: 12, playable_album_count: 2, context_scrobbles: 0, context_score: 0};
      const card = document.createElement('lastfm-music-card');
      card.setConfig({type:'custom:lastfm-music-card', max_genres:12});
      document.body.replaceChildren(card);
      document.body.style.cssText = 'max-width:750px;margin:30px auto;background:#111;color:#eee;--primary-text-color:#eee;--secondary-text-color:#bbc6bc;--card-background-color:#1b251f;--primary-color:#86a85b;--divider-color:#455047;font-family:system-ui';
      const state = (value, attributes = {}) => ({state:value, attributes});
      const test = window.musicTest = {card, calls:[], states:{
        'sensor.lastfm_genres': state('2', {genres:[metal,folk], contextual_genres:[folk],
          tagged_albums:13,total_albums:15,total_genres:2,context:{weekday:'Sunday',period:'Weekend',hour:10,timezone:'Europe/Helsinki'}}),
        'input_text.lastfm_genre':state(''),
        'input_select.lastfm_genre_context':state('Around this time'),
        'input_number.lastfm_years_unheard':state('3'),
        'input_number.lastfm_min_scrobbles':state('10'),
        'sensor.lastfm_recommendation':state('unknown'),
        'script.lastfm_music_recommend':state('off'),
        'script.lastfm_music_play':state('off')
      }};
      test.update = () => { card.hass = {states:test.states, callService:async (domain, service, data) => {
        test.calls.push({domain,service,data});
        if (domain === 'input_text') test.states[data.entity_id] = state(data.value);
        if (domain === 'script' && service === 'lastfm_music_recommend') {
          test.states['sensor.lastfm_recommendation'] = state('ready', {album,
            genre:test.states['input_text.lastfm_genre'].state,min_years_unheard:3,min_total_scrobbles:10,error:''});
        }
        test.update();
      }}; };
      test.update();
    }, {album:albumForCard});
    const card = musicPage.locator('lastfm-music-card');
    assert.equal(await card.locator('#cloud button').first().evaluate(button=>getComputedStyle(button).borderRadius), '24px');
    assert.equal(await card.getByRole('button', {name:'metal (12)',exact:true}).count(), 0);
    assert.equal(await musicPage.evaluate(() => musicTest.calls.length), 0);
    await card.getByRole('button', {name:'indie folk (1)',exact:true}).click();
    assert.equal(await musicPage.evaluate(() => musicTest.calls.filter(c=>c.domain==='script').length), 0);
    await card.getByRole('button', {name:'Find a forgotten favorite',exact:true}).click();
    await card.getByRole('button', {name:'Play this album',exact:true}).waitFor();
    assert.equal(await card.locator('h3').innerText(), 'Illinois');
    await card.getByRole('button', {name:'Play this album',exact:true}).click();
    assert.equal(await musicPage.evaluate(() => musicTest.calls.filter(c=>c.service==='lastfm_music_play').length), 1);
    await musicPage.screenshot({path:'.local-data/music-card.png',fullPage:true});
    await musicPage.evaluate(() => {
      musicTest.states['input_select.lastfm_genre_context'] = {state:'All genres',attributes:{}};
      musicTest.update();
    });
    await card.getByRole('button', {name:'metal (12)',exact:true}).waitFor();
    await card.getByRole('button', {name:'metal (12)',exact:true}).click();
    assert.equal(await card.getByRole('button', {name:'Play this album',exact:true}).count(), 0);
    assert.equal(await musicPage.evaluate(() => musicTest.calls.filter(c=>c.service==='lastfm_music_play').length), 1);
    await card.getByLabel('Filter genres').fill('folk');
    assert.equal(await card.getByRole('button', {name:'metal (12)',exact:true}).count(), 0);
    await musicPage.setViewportSize({width:390,height:844});
    assert.equal(await musicPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    assert.deepEqual(errors, []);
    console.log('Browser smoke test passed: app flow and HA card genre context, explicit search/play, stale-result protection, mobile layout.');
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
