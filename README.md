# Last.fm Recommender

A Home Assistant OS app that imports your Last.fm listening history into a local SQLite database and helps you rediscover forgotten albums. Use the web interface to filter recommendations and confirm Spotify album links, then start playback through a Home Assistant script using SpotifyPlus.

## Installation

[![Add this app repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/?repository_url=https%3A%2F%2Fgithub.com%2Fpasipasi123%2Fhomeassistant-lastfm-recommender)

1. Add this repository to the Home Assistant app store. The source must be pushed to GitHub first.
2. Install **Last.fm Recommender**. This release builds from source on your HA server.
3. Set your Last.fm username, API key and a random `api_token` of at least 32 characters.
4. Start the app and open its web interface. Enter the same token. The initial import starts automatically.
5. Confirm Spotify links for a few albums and configure the HA playback script.

[Installation, configuration, API and SpotifyPlus script](lastfm_recommender/DOCS.md)

## Scope

- Supports `amd64` and `aarch64`, with its own container and database at `/data/scrobbles.db`.
- History and recommendations work without SpotifyPlus. Automatic playback requires the HA SpotifyPlus integration and Spotify Premium.
- Spotify search is optional. Without Spotify API credentials, paste album links from Spotify manually.
- No LLM, voice search or custom HACS integration in this release.
- Local HTTP web interface on port 8099, without ingress. Use a trusted local network or your own HTTPS reverse proxy.
- All application text and documentation are in English.

## Development

Requires Python 3.12+ and IANA timezone data. Install `tzdata` on Linux; on Windows, use `python -m pip install tzdata` if needed. There are no other Python dependencies.

```sh
python -m unittest discover -s tests -v
node --check lastfm_recommender/rootfs/app/static/app.js
```

Optional browser smoke test: `node tests/ui_smoke.cjs` (requires Playwright, Microsoft Edge and a `python` command; set `PYTHON_EXE` if needed). It starts a local server with synthetic history, checks the interface and saves a screenshot to `.local-data/ui-smoke.png`. It does not call Last.fm or Spotify.

For a local run, create `.local-data/options.json` using the documented options, then run:

```sh
python lastfm_recommender/rootfs/app/run.py --options .local-data/options.json --data .local-data --host 127.0.0.1
```

`.local-data/` and credential-containing `options.json` files are excluded from Git. CI runs offline tests, JavaScript syntax checking, HA app lint and container builds for both architectures. Builds do not automatically publish an image or deploy the app.
