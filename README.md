# Last.fm Recommender

A Home Assistant OS app that imports Last.fm history into a local SQLite database and helps you rediscover forgotten albums. Its **Music** sidebar page provides a genre cloud, listening-time suggestions, album previews and playback through your existing SpotifyPlus integration.

## Installation

[![Add this app repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/?repository_url=https%3A%2F%2Fgithub.com%2Fpasipasi123%2Fhomeassistant-lastfm-recommender)

1. Add this repository and install **Last.fm Recommender** from the HA app store.
2. Set your Last.fm username and API key in app configuration, then start it.
3. Enable **Show in sidebar** and open **Music**. Home Assistant handles login.
4. In Music's **Settings**, choose and save your SpotifyPlus player.
5. Confirm Spotify links under **Album library**, then discover and play albums.

No dashboard YAML, custom card, HA configuration package or separately created HA access token is required. The app builds locally on your HA server. Existing history and app settings survive an update.

[Music setup and daily use](homeassistant/README.md) · [Options, API and backups](lastfm_recommender/DOCS.md)

## Scope

- Supports `amd64` and `aarch64`, with its own container and `/data/scrobbles.db`.
- Last.fm history and recommendations work without SpotifyPlus. Playback requires SpotifyPlus and Spotify Premium.
- Spotify catalogue credentials are optional; album links can be confirmed manually.
- History sync defaults to six hours; small metadata batches run every five minutes.
- Ingress is the default interface. An optional port 8099 API requires a separate app token.
- English interface and user documentation. No LLM or voice search in this release.

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
