# Last.fm Recommender – User guide

## Install on Home Assistant OS

1. Add `https://github.com/pasipasi123/homeassistant-lastfm-recommender` under **Settings → Apps → Install app → ⋮ → Repositories**.
2. Install **Last.fm Recommender**. Version 0.1.0 builds locally; a prebuilt registry image is not required.
3. Enter the app options below, save and start the app.
4. Select **Open Web UI** or visit `http://HA_SERVER_IP:8099/`. Enter the app's `api_token` and select **Connect**. The token is remembered only for the current browser tab's session.

The app does not need your HA configuration directory, Supervisor API access, host networking or hardware access. Port 8099 must be available. If necessary, change the host port in the app's network settings and update the URLs accordingly.

HTTP does not encrypt tokens or history in transit. Use a trusted local network or your own HTTPS reverse proxy; do not expose the port to the internet. This release does not support HA ingress. `/health` and static interface files are public; all `/api/` endpoints require a Bearer token.

## Options

```yaml
lastfm_username: "your_username"
lastfm_api_key: "your_lastfm_api_key"
api_token: "REPLACE_WITH_A_RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS"
timezone: "Europe/Helsinki"
sync_interval_minutes: 360
enrich_batch_size: 10
spotify_client_id: ""
spotify_client_secret: ""
```

- **Last.fm username and API key** are required. Get a key from [Last.fm](https://www.last.fm/api/account/create). Reading history does not require the user's password or write permissions.
- **`api_token`**: generate a random secret of at least 32 characters with a password manager. The example is a placeholder. Use the same value in the browser and HA REST requests. Changing it requires restarting the app and updating the HA secret.
- **`timezone`**: timezone for calendar fields in the listening history. Listening timestamps remain in UTC. Changing the timezone recalculates calendar fields at startup. This does not change the interface language, which is English. Displayed dates use English formatting and the browser's timezone.
- **`sync_interval_minutes`**: 5–1440 minutes; default 360 (six hours). The interval starts after the previous import/enrichment cycle finishes. You can also sync manually, and import runs on app startup.
- **`enrich_batch_size`**: 0–100 albums per cycle. Set to 0 to disable metadata enrichment. Large libraries are enriched gradually; the default of 10 limits API usage. History import and recommendations do not wait for the entire enrichment queue to finish.
- **Spotify Client ID and Secret** are optional: set both or leave both empty. They enable Spotify album suggestions using Client Credentials authentication. A search result does not verify availability in your market or the correct album edition; you must confirm it. Your Spotify app's API restrictions may prevent search. Manual album links work independently.

Credentials stored in SpotifyPlus are not read or copied automatically. This app's Spotify credentials are not used for playback.

## History import and recommendations

Import starts automatically at startup, one page at a time. The initial import fixes an upper timestamp and requests up to 200 events per page. The interface shows progress. A large history takes at least several minutes. Wait for the first successful sync before assessing total listening counts.

Each page and its next checkpoint are committed in one SQLite transaction. An interrupted import resumes on the next run. Subsequent updates include a two-day overlap before the previous successful window's upper boundary. Multiple identical timestamp/artist/album/track events are preserved, including across page boundaries. The currently playing track is not counted as a completed scrobble.

**Limitation:** synchronization is additive. Deleted scrobbles and corrections to old names are not automatically removed or replaced in the database. Additions backdated more than two days require a separate full-history reimport. Editing history during the initial import can change the page count and stop the import. Changes that do not affect the page count cannot always be detected.

**Sync history** queues another cycle. Concurrent cycles are rejected. If a changed page count stopped import, wait for the cycle to finish and call `POST /api/sync/reset`. This restarts pagination for the import window while preserving stored history.

A forgotten favorite meets the minimum scrobble count and the minimum time since its last listen. The age cutoff uses UTC calendar years; February 29 is clamped to February 28 when necessary. A matching album is selected randomly, so an album may occasionally repeat. Genre filtering is an exact, case-insensitive tag match, not a substring search.

Scrobbles without an album name remain in history but do not generate album recommendations. Original names are preserved. Spelling variants and different album editions are not merged automatically.

## Confirm Spotify album links

1. Search for an artist or album in **Album library**.
2. Open the correct edition in Spotify: **⋯ → Share → Copy album link**.
3. Paste the full link or `spotify:album:ALBUM_ID` and select **Confirm album link and tags**. You can edit tags at the same time.

The album ID follows `/album/` in the URL. `?si=...` is a sharing parameter, not the album ID. The app accepts the complete sharing URL and removes query parameters when converting it to a URI.

Automatic Spotify search suggests one result. Suggestions are always unverified and are not used for automatic playback until confirmed. Check the artist and edition by listening. Confirmation is a user decision, not an API availability check. Enrichment does not overwrite a confirmed URI.

History and recommendations work without SpotifyPlus or Spotify API credentials. Playback through Home Assistant requires a working SpotifyPlus integration and Spotify Premium.

## Home Assistant: recommend and play an album

Add the full Authorization value to HA's `secrets.yaml`:

```yaml
lastfm_recommender_authorization: "Bearer SAME_API_TOKEN_AS_THE_APP"
```

Add or merge the following into the existing `rest_command` section in HA's `configuration.yaml`:

```yaml
rest_command:
  lastfm_recommend:
    url: "http://HA_SERVER_IP:8099/api/recommend?min_years_unheard=3&min_total_scrobbles=10&playable_only=true"
    method: get
    headers:
      Authorization: !secret lastfm_recommender_authorization
    timeout: 30
```

Replace the server IP. Do not use `localhost`: HA Core and this app run in separate containers. Check the HA configuration, then reload REST commands or restart HA.

Create a script under **Settings → Automations & scenes → Scripts → Create script**, then select **⋮ → Edit in YAML**:

```yaml
alias: Last.fm – Play a forgotten favorite
mode: single
sequence:
  - action: rest_command.lastfm_recommend
    response_variable: recommendation
  - variables:
      album: "{{ recommendation.content.album if recommendation.status == 200 else none }}"
  - if:
      - condition: template
        value_template: "{{ album is not mapping or album.spotify_status != 'confirmed' }}"
    then:
      - stop: "No matching confirmed Spotify album. Adjust the filters or confirm album links."
  - action: spotifyplus.player_media_play_context
    data:
      entity_id: media_player.olohuone_spotifyplus
      context_uri: "{{ album.spotify_uri }}"
```

This uses the SpotifyPlus call tested in the current setup. A Marantz NR1508 started album playback from standby without a separate power-on action. The call targets the active Spotify device, or SpotifyPlus's default when no device is active. **It does not guarantee Marantz playback while another device is active.** Test `device_id: "Marantz NR1508"` separately with a valid album URI before adding it to the script.

Replace `media_player.olohuone_spotifyplus` with your own SpotifyPlus entity ID if different. This existing entity ID is an identifier, not interface text. No `turn_on` call is made to `media_player.marantz_nr1508_2`, which does not support that action.

The API returns `album: null` when no results match, and the script stops without starting playback. Confirm album links in the interface first: the API defaults to confirmed albums only.

## REST API

All `/api/` requests require `Authorization: Bearer TOKEN`. Tokens are not accepted as URL parameters. Responses are JSON; CORS is not enabled.

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Process health without listening data; no authentication |
| `GET /api/status` | Counts, last successful sync, checkpoint and errors |
| `GET /api/albums?q=Illinois&limit=30` | Literal artist/album search, up to 100 results |
| `GET /api/recommend` | Random matching album or `album: null` |
| `POST /api/albums/ID` | Confirm with JSON: `{"spotify_uri":"spotify:album:...","tags":["indie folk"]}` |
| `POST /api/sync` | Queue sync and enrichment; 202 accepted, 409 already running/queued |
| `POST /api/sync/reset` | Reset an interrupted window's checkpoint and queue another run; preserves history |
| `GET /api/backup` | Download a consistent SQLite backup |

Recommendation parameters: `min_years_unheard` (0–100, default 3), `min_total_scrobbles` (1–10000000, default 10), `genre` (optional exact tag), and `playable_only` (`true` by default; `false` includes unconfirmed albums). Omitting `tags` when confirming an album preserves its tags; an empty list removes them. Later Last.fm enrichment may add tags again.

The browser includes unconfirmed recommendations by default so you can add links. The HA playback example always uses `playable_only=true`.

## Backups and recovery

The database, checkpoints and user confirmations live in `/data/scrobbles.db`. Supervisor manages app options in `/data/options.json`. Include the app in HA backups.

**Download backup** uses the SQLite backup API and works while the service is running. The downloaded database contains private listening history but no API credentials or tokens.

Prefer restoring the complete app from an HA backup. To restore a database manually: stop the app, preserve a copy of the current data, replace `/data/scrobbles.db` with a consistent backup and remove only the old database's associated `scrobbles.db-wal` and `scrobbles.db-shm` sidecar files before restarting. This requires access to the app's own data directory. Do not copy a live `.db` file separately from its WAL files.

The database belongs to one Last.fm username. Changing the username stops startup to avoid mixing different listeners' history. Switching users requires a separate clean database and a backup of the old one.

## First-release status

No LLM, voice search, custom Lovelace card, separate HACS integration or custom playback OAuth. Filters and album confirmation are available in the app's web interface; HA uses a REST command and script.

Offline tests cover import resumption and replay, duplicate source events across page boundaries, transaction rollback, timezones, leap days, tag filtering, confirmed-link filtering, authentication and backup recovery. Browser testing uses synthetic history. A real 300,000-scrobble import and HA OS container installation remain to be verified during deployment. A separate SpotifyPlus playback test has already succeeded on the target hardware.
