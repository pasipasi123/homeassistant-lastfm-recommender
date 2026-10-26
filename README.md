# Last.fm Recommender

A Home Assistant OS app that imports Last.fm history into a local SQLite database and helps you rediscover forgotten albums. Its **Music** sidebar page provides a genre cloud, listening-time suggestions, album previews and playback through your existing SpotifyPlus integration.

## Installation

[![Add this app repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/?repository_url=https%3A%2F%2Fgithub.com%2Fpasipasi123%2Fhomeassistant-lastfm-recommender)

1. Add this repository and install **Last.fm Recommender** from the HA app store.
2. Set your **Last.fm username** and **Last.fm API key** in the app's **Configuration** tab. The Last.fm shared secret is not needed.
3. **Recommended for everyday use:** add your Spotify application's **Client ID** and **Client Secret** as `spotify_client_id` and `spotify_client_secret`. Set `spotify_market` to your Spotify account country (default `FI`). These enable automatic album-link discovery, so you can play recommendations without copying each album's link by hand.
4. Start the app, enable **Show in sidebar**, and open **Music**. Home Assistant handles login. Restart if you change configuration later.
5. In Music's **Settings**, choose and save your SpotifyPlus player and **Default playback device**. Each album's Play button shows its destination; expand that text to temporarily choose another device.
6. Let the background import and album lookups run. Under **Album library**, use **Refresh albums** to see new links and review uncertain matches. Then use **Discover** to find and play an album.

No dashboard YAML, custom card, HA configuration package or separately created HA access token is required. The app builds locally on your HA server. Existing history and app settings survive an update.

[Music setup and daily use](homeassistant/README.md) · [Options, API and backups](lastfm_recommender/DOCS.md)

## Why add Spotify credentials?

Spotify catalogue credentials make the app practical for a large listening history: album URIs are found in background batches, unique exact artist/album matches are linked automatically, and ambiguous editions are presented for review. The default is 10 album lookups every five minutes, so a large library takes time to fill in. You can already use albums whose links have been found.

These credentials are separate from your Last.fm API key and SpotifyPlus login. They are used for catalogue searches; playback uses the SpotifyPlus integration you have already configured in Home Assistant. Installing SpotifyPlus alone does not enable the app's background URI search.

The app also works without Spotify catalogue credentials, but each album's Spotify link must then be pasted and confirmed manually under **Album library** before it can be played from Music. Manual links are also available when API access is restricted or an album cannot be matched.

## Scope

- Supports `amd64` and `aarch64`, with its own container and `/data/scrobbles.db`.
- Last.fm history and recommendations work without SpotifyPlus. Playback requires SpotifyPlus and Spotify Premium.
- Spotify catalogue credentials are recommended for automatic album linking. Manual link entry is supported as a fallback.
- History sync defaults to six hours; metadata and Spotify lookup batches run every five minutes.
- Four-digit year tags are displayed beside album names instead of in the genre cloud.
- Ingress is the default interface. An optional port 8099 API requires a separate app token.
- English interface and user documentation. No LLM or voice search in this release.
- Light, Dark and Colorful themes under **Music → Settings → Appearance**, remembered per browser.

## Development

Requires Python 3.12+ and IANA timezone data (`tzdata` on Linux, or `python -m pip install tzdata` on Windows if needed). No other Python dependencies.

```sh
python -m unittest discover -s tests -v
node --check lastfm_recommender/rootfs/app/static/app.js
```

Optional browser smoke test: `node tests/ui_smoke.cjs` requires Playwright and Microsoft Edge. Set `PYTHON_EXE` if `python` is not on PATH. It uses synthetic history, a fake HA and a prefixed ingress proxy; it never starts real playback. The screenshot is saved to `.local-data/music-ingress.png`.

For local development, create `.local-data/options.json` with the documented options and a 32+ character `api_token`, then run:

```sh
python lastfm_recommender/rootfs/app/run.py --options .local-data/options.json --data .local-data --host 127.0.0.1
```

Open `http://127.0.0.1:8099/` and enter that app token. Direct local runs do not have Supervisor-provided playback access. Do not supply a real Supervisor token to tests.

`.local-data/`, `options.json`, database files and caches are excluded from Git. CI runs offline tests, JavaScript syntax checking, HA app lint and both container architecture builds. Builds do not automatically publish images or deploy to HA.
