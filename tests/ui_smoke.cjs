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
    await page.route('**/api/status',async route=>{
      const response = await route.fetch();
      await route.fulfill({response,json:{...await response.json(),enrichment_error:'AttributeError'}});
    });
    await page.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#background-status').textContent.includes('Some album details could not be updated'));
    assert.equal((await page.locator('#message').innerText()).includes('AttributeError'),false);
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    assert.equal(await page.locator('#background-status').isVisible(),true);
    assert.equal(await page.locator('#background-details-text').isVisible(),false);
    await page.getByText('Technical details',{exact:true}).click();
    assert.equal(await page.locator('#background-details-text').innerText(),'Last.fm metadata: AttributeError');
    await page.unroute('**/api/status');
    await page.getByRole('button',{name:'Album library',exact:true}).click();
    await page.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#background-status').hidden);
    assert.equal(await page.locator('#background-details').getAttribute('open'),null);
    let transientReads = 0;
    await page.route('**/api/status',async route=>{
      transientReads++;
      if (transientReads===1) await route.fulfill({status:502,contentType:'text/plain',body:'502: Bad Gateway'});
      else await route.continue();
    });
    const recoveredStatus = page.waitForResponse(response=>response.url().endsWith('/api/status')&&response.status()===200);
    await page.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await recoveredStatus;
    assert.equal(transientReads,2);
    await page.unroute('**/api/status');
    await page.route('**/api/status',route=>route.fulfill({status:200,contentType:'text/plain',body:'200: proxy response, not JSON'}));
    await page.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('Library status: HTTP 200, expected a JSON response'));
    await page.unroute('**/api/status');
    await page.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent==='');
    await page.locator('#albums').getByText('Review 2 Spotify matches',{exact:true}).click();
    await mkdir('.local-data',{recursive:true});
    await page.screenshot({path:'.local-data/spotify-matches.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.setViewportSize({width:1280,height:1000});
    await page.locator('#albums').getByRole('button',{name:'Use this edition',exact:true}).nth(1).click();
    assert.equal(await page.locator('#albums').getByLabel('Spotify album link or URI').inputValue(),'spotify:album:'+'A'.repeat(22));
    assert.equal(await page.locator('#albums').getByRole('link',{name:'Open confirmed album in Spotify'}).count(),0);
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
    await music.getByRole('button',{name:'Discover',exact:true}).click();
    await music.getByLabel('Spotify Connect device',{exact:true}).selectOption('Demo receiver');
    await music.getByRole('button',{name:'Use device',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#device-status').textContent.includes('Albums will play on Demo receiver'));
    await music.reload();
    await music.waitForFunction(()=>document.querySelector('#device-select').value === 'Demo receiver');
    assert.equal(requests.filter(request=>request.path.endsWith('/api/play')).length,0);
    // Another active device must not supply this receiver's volume or receive its controls.
    let deviceScenario='other-active';
    await music.route('**/api/players',async route=>{
      const response=await route.fetch();
      const data=await response.json();
      data.players=data.players.map(player=>({...player,source:'Work laptop',volume_level:0.9,
        devices:deviceScenario==='missing' ? ['Work laptop'] : player.devices}));
      await route.fulfill({response,json:data});
    });
    await music.getByRole('button',{name:'Refresh devices',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#device-status').textContent.includes('currently active on Work laptop'));
    assert.equal(await music.getByRole('button',{name:'Pause',exact:true}).isEnabled(),false);
    assert.equal(await music.locator('#player-volume-up').isEnabled(),false);
    assert.equal(await music.locator('#volume-value').innerText(),'—');
    deviceScenario='missing';
    await music.getByRole('button',{name:'Refresh devices',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#device-status').textContent.includes('Demo receiver is unavailable'));
    assert.equal(await music.locator('#device-select').inputValue(),'Demo receiver');
    await music.unroute('**/api/players');
    await music.getByRole('button',{name:'Refresh devices',exact:true}).click();
    await music.waitForFunction(()=>!document.querySelector('#player-volume-up').disabled);
    await music.getByRole('button',{name:'Settings',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#player-setup').textContent.includes('Saved player:'));
    let quotaDeadline=Math.floor(Date.now()/1000)+7*3600;
    await music.route('**/api/status',async route=>{
      const response=await route.fetch();
      await route.fulfill({response,json:{...await response.json(),spotify_configured:true,
        spotify_retry_at:quotaDeadline,spotify_error:'API quota exceeded; album requests paused for 25674 seconds'}});
    });
    await music.getByRole('button',{name:'Album library',exact:true}).click();
    await music.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#spotify-pause').textContent.includes('Spotify album lookup is paused until'));
    assert.match(await music.locator('#spotify-pause').innerText(),/until \d{2}:\d{2} (today|tomorrow)\./);
    assert.equal((await music.locator('body').innerText()).includes('25674 seconds'),false);
    assert.equal((await music.locator('#message').innerText()).includes('quota'),false);
    assert.equal(await music.getByRole('button',{name:'Find Spotify links',exact:true}).isEnabled(),false);
    assert.equal(await music.locator('#albums').getByRole('button',{name:'Play this album',exact:true}).isEnabled(),true);
    await music.screenshot({path:'.local-data/cooldown-library.png',fullPage:true,animations:'disabled'});
    await music.getByRole('button',{name:'Discover',exact:true}).click();
    assert.equal(await music.locator('#spotify-pause').isVisible(),false);
    assert.equal((await music.locator('body').innerText()).includes('Spotify album lookup is paused'),false);
    await music.getByRole('button',{name:'Settings',exact:true}).click();
    assert.equal(await music.locator('#background-status').isVisible(),true);
    assert.equal(await music.locator('#background-details-text').isVisible(),false);
    assert.equal((await music.locator('body').innerText()).includes('25674 seconds'),false);
    quotaDeadline=Math.floor(Date.now()/1000)-1;
    await music.getByRole('button',{name:'Album library',exact:true}).click();
    await music.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#spotify-pause').textContent.includes('next background update'));
    assert.equal(await music.getByRole('button',{name:'Find Spotify links',exact:true}).isEnabled(),true);
    await music.unroute('**/api/status');
    await music.getByRole('button',{name:'Refresh albums',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#spotify-pause').hidden);
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
    assert.equal(await music.locator('#volume-value').innerText(),'20.0');
    let failedWrites = 0;
    await music.route('**/api/player/control',route=>{
      failedWrites++;
      return route.fulfill({status:502,contentType:'text/plain',body:'502: Bad Gateway'});
    });
    await music.evaluate(()=>{
      for(let i=0;i<3;i++) document.querySelector('#player-volume-up').click();
    });
    assert.equal(await music.locator('#volume-value').innerText(),'23.0');
    await music.waitForFunction(()=>document.querySelector('#message').textContent.includes('Player control: HTTP 502, expected a JSON response'));
    assert.equal(failedWrites,1);
    assert.equal(await music.locator('#volume-value').innerText(),'20.0');
    await music.unroute('**/api/player/control');
    await music.getByRole('button',{name:'Increase volume by 1.0',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#volume-value').textContent==='21.0');
    await music.waitForFunction(()=>document.querySelector('#message').textContent==='');
    await music.getByRole('button',{name:'Decrease volume by 1.0',exact:true}).click();
    await music.waitForFunction(()=>document.querySelector('#volume-value').textContent==='20.0');
    await music.waitForFunction(()=>document.querySelector('#volume-value').getAttribute('aria-busy')==='false');
    // Hold the first volume response while rapid clicks update the local target.
    const volumeWrites = [];
    let releaseFirst, firstApplied;
    const firstGate = new Promise(resolve=>{releaseFirst=resolve;});
    const applied = new Promise(resolve=>{firstApplied=resolve;});
    let activeWrites=0, maxWrites=0, staleReads=0;
    await music.route('**/api/player/control',async route=>{
      const body = route.request().postDataJSON();
      volumeWrites.push(body); activeWrites++; maxWrites=Math.max(maxWrites,activeWrites);
      const response = await route.fetch();
      if(volumeWrites.length===1) {firstApplied(); await firstGate;}
      activeWrites--;
      await route.fulfill({response});
    });
    await music.route('**/api/players',async route=>{
      const response=await route.fetch();
      const data=await response.json();
      if(volumeWrites.length>=2 && staleReads<2) {
        staleReads++;
        data.players=data.players.map(player=>({...player,volume_level:0.21}));
      }
      await route.fulfill({response,json:data});
    });
    await music.evaluate(()=>{
      for(let i=0;i<5;i++) document.querySelector('#player-volume-up').click();
    });
    assert.equal(await music.locator('#volume-value').innerText(),'25.0');
    assert.equal(await music.getByRole('button',{name:'Increase volume by 1.0',exact:true}).isEnabled(),true);
    await applied;
    await music.evaluate(()=>loadPlayers());
    assert.equal(await music.locator('#volume-value').innerText(),'25.0');
    assert.equal(volumeWrites.length,1);
    await music.evaluate(()=>{
      for(let i=0;i<2;i++) document.querySelector('#player-volume-down').click();
    });
    assert.equal(await music.locator('#volume-value').innerText(),'23.0');
    releaseFirst();
    await music.waitForFunction(()=>document.querySelector('#volume-value').getAttribute('aria-busy')==='false');
    assert.deepEqual(volumeWrites.map(body=>body.volume),[0.21,0.23]);
    assert.equal(volumeWrites.every(body=>body.action==='volume'&&body.expected_entity==='media_player.demo_music'),true);
    assert.equal(maxWrites,1);
    assert.equal(staleReads,2);
    assert.equal(await music.locator('#volume-value').innerText(),'23.0');
    await music.unroute('**/api/player/control');
    await music.unroute('**/api/players');
    await music.evaluate(()=>{
      for(let i=0;i<3;i++) document.querySelector('#player-volume-down').click();
    });
    await music.waitForFunction(()=>document.querySelector('#volume-value').getAttribute('aria-busy')==='false');
    assert.equal(await music.locator('#volume-value').innerText(),'20.0');
    await mkdir('.local-data',{recursive:true});
    await music.screenshot({path:'.local-data/music-ingress.png',fullPage:true});
    await music.setViewportSize({width:390,height:844});
    assert.equal(await music.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await music.screenshot({path:'.local-data/music-mobile.png',fullPage:true});
    await music.reload();
    await music.locator('#genres button').first().waitFor();
    await music.waitForFunction(()=>document.querySelector('#player-state').textContent.includes('Chicago'));
    assert.equal(await music.locator('#auth').isVisible(),false);
    assert.equal(requests.filter(request=>request.path.startsWith('/api/')&&!request.path.startsWith(prefix)).length,0);
    assert.equal(requests.filter(request=>request.headers.authorization).length,0);
    const inline = await browser.newPage({viewport:{width:390,height:844}});
    inline.on('pageerror',error=>errors.push(error.message));
    const inlineRequests = [];
    inline.on('request',request=>inlineRequests.push(new URL(request.url()).pathname));
    await inline.route('**/api/recommend?*',async route=>{
      const response = await route.fetch();
      const data = await response.json();
      // Show the pending-link state even though another test has linked this album.
      await route.fulfill({response,json:{...data,album:{...data.album,spotify_status:'candidate',spotify_uri:null}}});
    });
    await inline.goto(`http://127.0.0.1:${ports.ingress}${prefix}`);
    await inline.waitForFunction(()=>!document.querySelector('#player-pause').disabled);
    await inline.getByRole('button',{name:'Find a forgotten favorite',exact:true}).click();
    const card = inline.locator('#recommendation');
    await card.locator('h3').waitFor();
    assert.equal(await card.getByRole('button',{name:'Play this album',exact:true}).isEnabled(),false);
    await card.getByText('Review 2 Spotify matches',{exact:true}).click();
    await card.getByRole('button',{name:'Use this edition',exact:true}).first().click();
    await card.getByRole('button',{name:'Confirm Spotify link',exact:true}).click();
    await card.getByRole('link',{name:'Open confirmed album in Spotify'}).waitFor();
    assert.equal(await card.locator('h3').innerText(),'Illinois (2005)');
    assert.equal(await inline.locator('#discovery-section').isVisible(),true);
    assert.equal(await card.getByRole('button',{name:'Play this album',exact:true}).isEnabled(),true);
    assert.equal(inlineRequests.filter(path=>path.endsWith('/api/recommend')).length,1);
    assert.equal(inlineRequests.filter(path=>path.endsWith('/api/play')).length,0);
    await card.getByRole('button',{name:'Play this album',exact:true}).click();
    await inline.waitForFunction(()=>document.querySelector('#message').textContent==='Playback requested.');
    assert.equal(inlineRequests.filter(path=>path.endsWith('/api/play')).length,1);
    await card.getByText('Check or change Spotify link',{exact:true}).click();
    await card.getByText('Review 2 Spotify matches',{exact:true}).click();
    await card.getByRole('button',{name:'Use this edition',exact:true}).nth(1).click();
    await card.getByRole('button',{name:'Confirm Spotify link',exact:true}).click();
    await inline.waitForFunction(()=>document.querySelector('#recommendation a[href="https://open.spotify.com/album/AAAAAAAAAAAAAAAAAAAAAA"]'));
    assert.equal(inlineRequests.filter(path=>path.endsWith('/api/recommend')).length,1);
    assert.equal(await card.locator('p').filter({hasText:'indie folk'}).count(),1);
    assert.equal(await inline.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await inline.screenshot({path:'.local-data/discover-spotify.png',fullPage:true});

    const custom = await browser.newPage();
    custom.on('pageerror',error=>errors.push(error.message));
    await custom.route('**/api/session',async route=>{
      const response = await route.fetch();
      await route.fulfill({response,json:{...await response.json(),volume:{min:-80,max:20,step:0.5,decimals:1}}});
    });
    await custom.goto(`http://127.0.0.1:${ports.ingress}${prefix}`);
    await custom.waitForFunction(()=>document.querySelector('#volume-value').textContent==='-60.0');
    assert.equal(await custom.locator('#player-volume').getAttribute('step'),'0.5');
    assert.equal(await custom.getByRole('button',{name:'Increase volume by 0.5',exact:true}).count(),1);
    await custom.locator('#player-volume').evaluate(input=>{
      input.value='-55'; input.dispatchEvent(new Event('change',{bubbles:true}));
    });
    await custom.waitForFunction(()=>document.querySelector('#volume-value').textContent==='-55.0');

    // Theme choices are local, persist across reloads and work without storage access.
    const themeContext = await browser.newContext({viewport:{width:1280,height:1000}});
    const themed = await themeContext.newPage();
    themed.on('pageerror',error=>errors.push(error.message));
    await themed.goto(`http://127.0.0.1:${ports.ingress}${prefix}`);
    await themed.locator('#genres button').first().waitFor();
    assert.equal(await themed.locator('html').getAttribute('data-theme'),'light');
    await themed.getByRole('button',{name:'Find a forgotten favorite',exact:true}).click();
    await themed.locator('#recommendation h3').waitFor();
    for (const [value,name] of [['light','Light'],['dark','Dark'],['colorful','Colorful']]) {
      await themed.getByRole('button',{name:'Settings',exact:true}).click();
      await themed.getByRole('radio',{name,exact:true}).check();
      assert.equal(await themed.locator('html').getAttribute('data-theme'),value);
      assert.equal(await themed.evaluate(()=>localStorage.getItem('lastfm-theme')||'light'),value);
      await themed.getByRole('button',{name:'Discover',exact:true}).click();
      assert.equal(await themed.locator('#appearance-settings').isVisible(),false);
      const contrasts = await themed.evaluate(()=>{
        const styles=getComputedStyle(document.documentElement);
        const luminance=name=>{
          const color=styles.getPropertyValue(name).trim().slice(1);
          const rgb=[0,2,4].map(i=>parseInt(color.slice(i,i+2),16)/255)
            .map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
          return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
        };
        return [['--text','--panel'],['--muted','--panel'],['--accent','--panel'],
          ['--on-accent','--accent'],['--on-coral','--coral'],['--placeholder','--input-bg'],
          ['--chip-text','--chip-bg'],['--chip-warm-text','--chip-warm-bg'],['--chip-alt-text','--chip-alt-bg'],
          ['--player-title','--player-bg'],['--error','--panel']].map(([foreground,background])=>{
            const a=luminance(foreground),b=luminance(background);
            return {foreground,ratio:(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05)};
          });
      });
      assert.equal(contrasts.every(pair=>pair.ratio>=4.5),true,`${name}: ${JSON.stringify(contrasts)}`);
      await themed.screenshot({path:`.local-data/music-theme-${value}.png`,fullPage:true,animations:'disabled'});
      await themed.setViewportSize({width:390,height:844});
      assert.equal(await themed.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      await themed.getByRole('button',{name:'Settings',exact:true}).click();
      assert.equal(await themed.getByRole('radio',{name,exact:true}).isChecked(),true);
      await themed.screenshot({path:`.local-data/music-theme-${value}-settings-mobile.png`,fullPage:true,animations:'disabled'});
      await themed.setViewportSize({width:1280,height:1000});
    }
    await themed.reload();
    assert.equal(await themed.locator('html').getAttribute('data-theme'),'colorful');
    await themed.getByRole('button',{name:'Settings',exact:true}).click();
    assert.equal(await themed.getByRole('radio',{name:'Colorful',exact:true}).isChecked(),true);
    await themed.evaluate(()=>localStorage.setItem('lastfm-theme','unknown-theme'));
    await themed.reload();
    assert.equal(await themed.locator('html').getAttribute('data-theme'),'light');
    const blockedContext=await browser.newContext();
    await blockedContext.addInitScript(()=>{
      Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Blocked','SecurityError');}});
    });
    const blocked=await blockedContext.newPage();
    blocked.on('pageerror',error=>errors.push(error.message));
    await blocked.goto(`http://127.0.0.1:${ports.ingress}${prefix}`);
    await blocked.getByRole('button',{name:'Settings',exact:true}).click();
    await blocked.getByRole('radio',{name:'Dark',exact:true}).check();
    assert.equal(await blocked.locator('html').getAttribute('data-theme'),'dark');
    await blockedContext.close();
    await themeContext.close();
    assert.deepEqual(errors,[]);
    console.log('Browser smoke test passed: direct auth, prefixed ingress without login, player persistence, explicit playback, controls, mobile layout, backup.');
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
