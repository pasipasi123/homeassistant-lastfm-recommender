// Optional: Playwright + Microsoft Edge. Uses synthetic data and never real playback.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdir} = require('node:fs/promises');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const child = spawn(process.env.PYTHON_EXE || 'python', [path.join(__dirname,'ui_fixture.py')], {
    stdio:['ignore','pipe','inherit'], windowsHide:true
  });
  let browser;
  try {
    const ports = await Promise.race([
      once(child.stdout,'data').then(([chunk])=>JSON.parse(chunk.toString().trim())),
      once(child,'exit').then(([code])=>{throw new Error(`Fixture exited: ${code}`);})
    ]);
    browser = await chromium.launch({channel:'msedge',headless:true});
    const page = await browser.newPage({viewport:{width:1280,height:1000},acceptDownloads:true});
    const errors = [];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${ports.direct}/`);
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    await page.getByLabel('API token',{exact:true}).fill('browser-test-'+'x'.repeat(32));
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.locator('#genres button').first().waitFor();
    await page.getByRole('button',{name:'Find a forgotten favorite',exact:true}).click();
    await page.locator('#recommendation h3').waitFor();
    assert.equal(await page.locator('#recommendation h3').innerText(),'Illinois (2005)');
    assert.equal(await page.locator('#recommendation').getByRole('button',{name:'Play this album'}).isEnabled(),false);
    await page.getByRole('button',{name:'Album library',exact:true}).click();
    await page.locator('#albums h3').waitFor();
    await page.getByText('Review 2 Spotify matches',{exact:true}).click();
    await mkdir('.local-data',{recursive:true});
    await page.screenshot({path:'.local-data/spotify-matches.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.setViewportSize({width:1280,height:1000});
    await page.getByRole('button',{name:'Use this edition',exact:true}).nth(1).click();
    assert.equal(await page.locator('#albums').getByLabel('Spotify album link or URI').inputValue(),'spotify:album:'+'A'.repeat(22));
    assert.equal(await page.getByRole('link',{name:'Open confirmed album in Spotify'}).count(),0);
    const form = page.locator('#albums .album form');
    await form.getByLabel('Spotify album link or URI').fill('https://open.spotify.com/album/0S2DmRfqWM51FUprHs0qil?si=notanalbumid');
    await form.getByLabel('Tags, separated by commas').fill('indie folk');
    await form.getByRole('button').click();
    await page.locator('#albums').getByRole('link',{name:'Open confirmed album in Spotify'}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('1 confirmed Spotify links'));
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    const download = page.waitForEvent('download');
    await page.getByRole('button',{name:'Download backup'}).click();
    assert.equal((await download).suggestedFilename(),'scrobbles.db');
    await page.getByRole('button',{name:'Forget token'}).click();
    assert.equal(await page.locator('#albums').innerText(),'');

    const music = await browser.newPage({viewport:{width:1280,height:1000},acceptDownloads:true});
    music.on('pageerror',error=>errors.push(error.message));
    const prefix = '/api/hassio_ingress/test-session/';
    const requests = [];
    music.on('request',request=>requests.push({path:new URL(request.url()).pathname,headers:request.headers()}));
    await music.goto(`http://127.0.0.1:${ports.ingress}${prefix}`);
    await music.locator('#genres button').first().waitFor();
    assert.equal(await music.locator('#auth').isVisible(),false);
    assert.equal(await music.locator('#token').inputValue(),'');
    assert.equal(await music.locator('#discovery-section').isVisible(),true);
    assert.equal(requests.filter(request=>request.path.endsWith('/api/recommend')).length,0);
    await music.getByRole('button',{name:'Settings',exact:true}).click();
    await music.locator('#player-select option[value="media_player.demo_music"]').waitFor({state:'attached'});
    await music.getByRole('combobox',{name:'SpotifyPlus player',exact:true}).selectOption('media_player.demo_music');
    await music.getByRole('button',{name:'Save player',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#player-setup').textContent.includes('Saved player:'));
    await music.getByRole('button',{name:'Discover',exact:true}).click();
    await music.locator('#genres').getByRole('button',{name:'indie folk (1)',exact:true}).click();
    assert.equal(requests.filter(request=>request.path.endsWith('/api/recommend')).length,0);
    await music.getByLabel('Only albums with confirmed Spotify links').check();
    await music.getByRole('button',{name:'Find a forgotten favorite',exact:true}).click();
    await music.locator('#recommendation h3').waitFor();
    assert.equal(requests.filter(request=>request.path.endsWith('/api/play')).length,0);
    // Changing a filter discards the old album, without another recommendation request.
    await music.locator('input[name="min_years_unheard"]').fill('4');
    assert.equal(await music.locator('#recommendation h3').count(),0);
    await music.getByRole('button',{name:'Find a forgotten favorite',exact:true}).click();
    const play = music.locator('#recommendation').getByRole('button',{name:'Play this album',exact:true});
    await play.waitFor();
    await play.click();
    await music.waitForFunction(()=>document.querySelector('#player-state').textContent.includes('Chicago'));
    assert.equal(requests.filter(request=>request.path.endsWith('/api/play')).length,1);
    await music.getByRole('button',{name:'Pause',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#player-state').textContent.includes('paused'));
    await music.getByRole('button',{name:'Resume',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#player-state').textContent.includes('playing'));
    await mkdir('.local-data',{recursive:true});
    await music.screenshot({path:'.local-data/music-ingress.png',fullPage:true});
    await music.setViewportSize({width:390,height:844});
    assert.equal(await music.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await music.reload();
    await music.locator('#genres button').first().waitFor();
    await music.waitForFunction(()=>document.querySelector('#player-state').textContent.includes('Chicago'));
    assert.equal(await music.locator('#auth').isVisible(),false);
    assert.equal(requests.filter(request=>request.path.startsWith('/api/')&&!request.path.startsWith(prefix)).length,0);
    assert.equal(requests.filter(request=>request.headers.authorization).length,0);
    assert.deepEqual(errors,[]);
    console.log('Browser smoke test passed: direct auth, prefixed ingress without login, player persistence, explicit playback, controls, mobile layout, backup.');
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
