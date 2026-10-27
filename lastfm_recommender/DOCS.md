# Last.fm Recommender – User guide

## Install or update

1. Add `https://github.com/pasipasi123/homeassistant-lastfm-recommender` to the HA app store and install **Last.fm Recommender**. Version 0.3.4.2 builds locally on your HA server.
2. Enter your **Last.fm username** and **Last.fm API key** in app configuration. The Last.fm shared secret is not needed.
3. Start the app, enable **Show in sidebar**, and open **Music** or **Open Web UI**.
4. In Music's **Settings**, choose your SpotifyPlus player and select **Save player**.

Home Assistant authenticates the Ingress page. No extra app login, dashboard YAML, custom card or manually created HA access token is required. The app receives a server-side Supervisor token and the `homeassistant_api` permission for its restricted playback client. The token is never returned to the browser or stored in the listening database.

Existing Last.fm settings, history, tags, checkpoints and confirmed Spotify links are preserved. The saved SpotifyPlus entity belongs to this installation and is stored in the app database. [Music setup and daily use](../homeassistant/README.md).

## Options

```yaml
lastfm_username: "your_username"
lastfm_api_key: "your_lastfm_api_key"
api_token: ""
timezone: "Europe/Helsinki"
sync_interval_minutes: 360
enrich_batch_size: 10
enrich_interval_minutes: 5
lastfm_batch_size: 50
lastfm_interval_minutes: 1
spotify_client_id: ""
spotify_client_secret: ""
spotify_market: "FI"
volume_min: 0.0
volume_max: 100.0
volume_step: 1.0
volume_decimals: 1
```

- **Last.fm username/API key**: required. Get an API key from [Last.fm](https://www.last.fm/api/account/create). History reads do not require a password, shared secret or write permissions.
- **`api_token`**: optional, not used for Ingress login. Leave empty for Ingress-only use. For direct browser/REST access, generate a random secret of at least 32 characters and enable the optional port 8099 mapping in HA. Direct requests require `Authorization: Bearer TOKEN`. The listening database does not contain this token.
- **`timezone`**: IANA timezone for local calendar fields and listening context. Listening timestamps stay in UTC. Changing it recalculates calendar fields at startup. UI text is English; dates use English formatting in the browser's timezone.
- **`sync_interval_minutes`**: 5–1440 minutes; default 360 (six hours), measured after the previous history sync. Sync also runs on startup and can be requested manually.
- **`enrich_batch_size`**: 0–100 albums per Spotify lookup batch; default 10. Set 0 to disable Spotify album searches. This no longer controls Last.fm tags.
- **`enrich_interval_minutes`**: 1–1440 minutes; default 5, measured after a Spotify batch finishes. This does not control Last.fm tags.
- **`lastfm_batch_size`**: 0–100 albums per Last.fm metadata batch; default 50. Set 0 to disable album tag/image updates without disabling history sync or Spotify lookup.
- **`lastfm_interval_minutes`**: 1–1440 minutes; default 1, measured after a metadata batch finishes. Requests are sequential with the existing 0.5-second pause before each Last.fm call. A single worker runs history, tag and Spotify jobs on separate schedules, so a long history sync or service request may delay other jobs. Faster tag settings never schedule extra Spotify searches.
- **Spotify Client ID/Secret**: optional; set both or leave both empty. They enable background catalogue matching using Client Credentials authentication. Unique exact matches are linked automatically; uncertain results need confirmation. API restrictions may prevent useful results; manually pasted album links work independently. Restart the app after changing credentials.
- **`spotify_market`**: two-letter uppercase country code, default `FI`. Set this to your Spotify account country. Client Credentials tokens have no user country, so searches specify the market explicitly. Changing it requeues unresolved albums after a restart.
- **`volume_min` / `volume_max`**: display bounds, default 0.0–100.0. The reported HA level 0–1 maps linearly to this range. For a device with a 0–80 scale, set 0 and 80. Negative scales are supported when that linear mapping matches your device. These settings change display units, not the receiver's physical volume limits.
- **`volume_step`**: plus/minus step in display units, default 1.0. Use 0.5 for finer adjustment. Each click updates the local target; displayed values are converted to HA's 0–1 volume level before sending.
- **`volume_decimals`**: 0–2 decimal places, default 1. The precision must be sufficient to show the configured step. Restart after changing volume settings.

The optional Spotify catalogue credentials are separate from SpotifyPlus authentication. They are not used for playback. Music discovers entities belonging to the HA SpotifyPlus integration, including renamed entities, and calls that existing integration.

## Discover and play

**Settings → Appearance** offers **Light**, **Dark** and **Colorful** themes. Light is the default and preserves the previous palette. Changes apply immediately and are stored in this browser's local storage, independently of app configuration and backups. The saved palette is applied before styles load to avoid a light flash when reopening a dark page. Other open tabs on the same origin follow the selection. If storage is unavailable, themes still work until the page is reloaded.

1. In **Discover**, choose a genre, optionally adjust minimum years/count, then select **Find a forgotten favorite**.
2. Preview the artist, album, scrobble count and last-listened date.
3. If the Spotify link needs confirmation, review the Spotify matches directly on the recommendation card, choose **Use this edition**, then **Confirm Spotify link**. You can also paste an album link there. The same album stays visible and its **Play this album** button becomes available once a player is saved. For already linked albums, **Check or change Spotify link** lets you review or correct the edition in place.
4. Select **Play this album**. Confirming a link never starts playback automatically.

Choosing a genre or opening the page does not search or play automatically. Changing filters clears the previous result. A response arriving after filters changed is discarded. Playback submits an album ID and expected URI; the server checks the current confirmed URI in SQLite before making a SpotifyPlus call.

Save a **Default playback device** in **Settings**. Existing saved destinations remain the default after updating. Next to every album's **Play this album** button, a compact **Playback will start on…** summary expands to a device dropdown. **Use for this session** chooses a temporary destination for this page, without changing the saved default; reloading the page or selecting **Use default** restores the default. All album cards on the page share this destination. Choosing a device never starts or transfers playback. **Refresh devices** rereads SpotifyPlus's HA source list; if a device is missing, check its availability in SpotifyPlus first. Playback always supplies the chosen device name to SpotifyPlus, even if another device was last active. If the destination is unavailable, choose another device or refresh; the app does not fall back to the active device. Changing SpotifyPlus accounts clears the device selection.

**Now playing** shows the selected account's current track and source. Pause, resume, next-track and volume controls target the saved Connect device and are enabled only when HA reports that device as the account's current source. If Spotify is active elsewhere, play an album on the saved device first. The app never uses another device's reported volume as the starting point for adjustments.

By default, volume displays the SpotifyPlus level multiplied by 100 with one decimal place (for example, `0.32` becomes **32.0**), without a percent sign. The **−** and **+** buttons update the displayed target immediately, by 1.0 per click. Rapid clicks accumulate locally while absolute volume commands are sent one at a time; intermediate queued targets are combined into the latest target. Adjust the display scale, precision and step with the volume options above. Values stay within the configured range, and older player reports do not overwrite a pending target. After the final command, the app briefly polls for the reported value and reconciles the display within about five seconds. Failed commands are not retried and queued changes are dropped. If the player reports no volume, the display shows **—** and volume controls are disabled until a reading is available. A slider remains available for larger changes.

If your device is available in Spotify Connect, a separate HA power-on action is generally unnecessary: send the SpotifyPlus playback request directly. If unavailable, check its network standby settings and whether it needs to be powered on first. A successful request confirms that HA accepted the action, not that the receiver produced sound.

## Genre context

The cloud loads from the library before any recommendation search. **Around this time** suggests up to 12 tags using local hours within ±2 hours and these fixed listening periods:

- **Monday–Thursday**
- **Friday**
- **Weekend** (Saturday and Sunday)

At midnight, observations stay within the same period. All stored years contribute. Tags require at least three contextual scrobbles and rank by `context_scrobbles / sqrt(scrobbles_total + 20)`, balancing time relevance and overall tag size. Sparse context falls back to the library catalogue.

**All genres**, **Filter genres** and **Show more genres** expose other choices. The catalogue is limited to 500 tags per ordering in the UI. No genre is prohibited, and time context does not add a hidden album recommendation filter. Custom time periods and household-presence rules are future settings.

Counts describe all tagged albums, including unconfirmed ones, not albums eligible under the current discovery filters. Last.fm community tags can include moods or non-genre labels. Tags overlap, and some albums have none. Enrichment or manually added tags make the cloud more complete over time.

Four-digit year tags (1000–2999) are stored separately as `release_year` and displayed beside the album name. Existing year tags are migrated on update and removed from the genre cloud. A single distinct year is used; conflicting years leave it unknown. Decade tags such as `2000s` remain tags. This year comes from Last.fm community tags and may describe a different edition; Spotify edition dates are shown separately among search results.

## History import

Import starts at startup, using a fixed upper timestamp and pages of up to 200 events. A large history takes at least several minutes. Progress is visible in **Settings → Library status**. Wait for the first successful sync before evaluating total counts.

Each page and next checkpoint are committed in one SQLite transaction. An interrupted import resumes automatically. Updates include a two-day overlap before the previous successful upper boundary. Identical timestamp/artist/album/track events preserve the source multiplicity, even across page boundaries. The currently playing track is not counted as a completed scrobble.

Synchronization is additive. Deleted source scrobbles and corrections to old names are not automatically removed/replaced. Additions backdated beyond the overlap need a separate full-history reimport. A changed page count during an initial import stops pagination; changes without a page-count change cannot always be detected.

**Sync history** queues another cycle and rejects overlapping requests. If a changed page count interrupted import, wait for the worker to become idle and call `POST /api/sync/reset` to restart that import window's pagination without deleting existing history.

A forgotten favorite meets the minimum scrobble count and last-listened age cutoff. The cutoff uses UTC calendar years, clamping February 29 to February 28 as needed. Matching albums are selected randomly and can occasionally repeat. Genre matches are exact and case-insensitive. Original names are preserved; spelling variants and editions are not merged automatically. Missing album names remain in history but do not create album recommendations.

## Find and confirm Spotify links

Catalogue search suggestions must contain the full requested artist name (with case, whitespace and Unicode normalization), rather than just a substring. A genuine collaboration containing that artist may still be shown for review; automatic matching remains stricter. The same artist filter is applied when reading cached suggestions, so irrelevant old results disappear without another Spotify request. Confirmed playback links are kept.

**Settings → Find links by artist** runs one bounded artist batch through SpotifyPlus. Eligible artists have at least three unconfirmed albums with at least 20 track scrobbles per album and an already confirmed album link to establish identity. The batch chooses up to five artists, prioritizing missing album count and listening count. Artists without a confirmed reference are left for normal album searches.

Each artist uses at most one `get_album` request to resolve an exact artist identity, then at most three `get_artist_albums` pages of ten releases, including albums, singles and compilations. The hard budget is 20 Spotify service requests per batch. Resolved identities are cached per SpotifyPlus account, and checked artists are skipped for 30 days so another manual batch advances to other artists. This lookup runs only on request; it does not run repeatedly in the background.

Exact artist/title matches from a complete release list can be linked automatically. A partial list, multiple editions, or restrictions leave matches for review. Only eligible albums with at least 20 scrobbles are affected; confirmed links are preserved. Matching is committed per artist after that artist's pages have been read. If a later artist fails, earlier completed artists remain, the current artist is unchanged, and a 15-minute retry pause applies. Interrupted jobs do not restart automatically. Progress and linked/review counts are shown in Settings.

**Settings → Import saved Spotify albums** reads the selected SpotifyPlus account's saved library using `spotifyplus.get_album_favorites`. Each request reads at most 50 albums with a short pause between pages. It uses the existing HA Core API connection and SpotifyPlus login, so no new OAuth login or catalogue credentials are needed. The import runs on the background worker and reports progress in Settings. It does not play music, save/remove Spotify albums, or add unheard albums to Last.fm history.

Matching begins after the entire snapshot is read. Exact artist/title matches are compared locally without stripping edition suffixes. A unique unrestricted edition is linked; multiple exact editions or restricted editions become review candidates. Existing confirmed links are never replaced. Nonmatching albums remain on the regular catalogue lookup queue. Only the album metadata needed for matching is retained; the service's user profile and track lists are discarded.

If paging fails, the library count changes, the account changes, or shutdown interrupts the import, no partial matches are applied. The job is not automatically repeated; use the button to start again from page zero. Failed requests impose a 15-minute retry pause to avoid repeatedly hitting an unavailable or rate-limited service. Changing the selected account during an import cancels matching. An import supports up to 10,050 saved albums within SpotifyPlus's paging range. This is not a Spotify rate-limit bypass: service errors stop the import.

With Spotify catalogue credentials configured, a separate queue finds URIs for unlinked albums, including albums whose Last.fm metadata was already fetched. Each Spotify cycle processes up to `enrich_batch_size` albums. The default remains 10 Spotify lookups with five-minute pauses (up to 120 albums/hour before request time). API limits, history import and network delays can slow this down. **Find Spotify links** requests only the next Spotify batch when idle. **Settings → Update Last.fm tags** separately requests a metadata batch. Scheduled batches continue the remaining library. **Refresh albums** reloads the results without replacing forms while you edit.

Last.fm metadata defaults to 50 albums per batch with a one-minute pause after completion. The queue checks never-processed albums first, ordered by listening count, then refreshes metadata older than 30 days. Empty metadata and unknown albums count as checked; they are not requested again on every cycle. **Settings → Library status** and the genre cloud distinguish checked albums from albums with tags. Some albums never receive tags because Last.fm has none for them. Metadata failures pause this queue for 15 minutes, or honor HTTP Retry-After when provided. The saved deadline survives app restarts and manual requests cannot bypass it. Spotify continues on its own schedule during a Last.fm metadata pause, and vice versa.

Search examines up to 30 results in pages of 10. Automatic linking requires exactly one distinct URI with an exact artist and album name match, an unrestricted result, and a complete result set. Case, Unicode compatibility and whitespace are normalized; edition suffixes and punctuation are preserved. Multiple artists, multiple exact editions, approximate matches and searches with more results are left for review. A name match cannot prove edition identity or guarantee playback availability.

The **Review … Spotify matches** section lists artwork, artist, title, release date and track count when available. Open a candidate in Spotify to inspect it, select **Use this edition**, then **Confirm album link and tags** to save it. Selecting an edition does not start playback or save it automatically. Automatically linked albums are labelled and can be corrected the same way.

Successful and empty searches are cached for 30 days; failed requests remain pending. Confirmed links, including manually selected ones, are never overwritten by background searches. Spotify failures do not block Last.fm tags and Last.fm failures do not block Spotify lookups.

If Spotify responds with HTTP 429, album searches pause until its `Retry-After` deadline (15 minutes if the header is absent or invalid). The deadline is saved in the database, survives app restarts and cannot be bypassed with manual sync or enrichment requests. Album library shows the resume time; Last.fm updates continue. A scheduled cycle at or after the deadline retries the pending album, without caching a quota response as a missing match. Updating or restarting this app does not clear a rate limit imposed by Spotify or a separate SpotifyPlus cooldown.

Expected pauses appear as quiet status notes in Album library and Settings, without a red banner in Discover. Resume times use minutes and today/tomorrow labels, rounded up to avoid suggesting an earlier retry. Other background update failures have plain-language summaries under **Settings → Library status**; expand **Technical details** for the diagnostic message. Errors from an action you just requested, such as playback or volume changes, still appear at the top.

In **Album library**, search for an artist or album. Open the correct edition in Spotify, select **⋯ → Share → Copy album link**, paste it and select **Confirm album link and tags**. Tags can be edited at the same time.

A Spotify album ID follows `/album/`; `?si=...` is a sharing parameter. The app accepts the whole link or `spotify:album:ALBUM_ID`, removing sharing parameters automatically.

Manual confirmation accepts the supplied album link without an API availability check.

## Optional REST API

Ingress runs on internal port 8098 and accepts only the Supervisor peer `172.30.32.2`; forwarded headers are not authentication. The separate port 8099 listener never trusts Ingress headers and requires the optional app token for private endpoints. Its host mapping is disabled by default on new installs. Existing installs may retain their previous mapping; disable it if not needed.

Direct HTTP is unencrypted. Use a trusted local network or your own HTTPS reverse proxy and do not expose the port to the internet. POST requests require `Content-Type: application/json`; the API does not enable CORS. Tokens are not accepted in URL parameters.

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Process health |
| `GET /api/session` | Login mode and whether server-side HA access is available; no credentials |
| `GET /api/status` | Counts, progress, phase, last success and errors |
| `GET /api/genres?limit=200` | Tag counts, contextual rankings and coverage; limit 1–500 |
| `GET /api/albums?q=Illinois&limit=30` | Literal artist/album search; limit 1–100 |
| `GET /api/recommend` | Random matching album or `album: null` |
| `POST /api/albums/ID` | Confirm with `{"spotify_uri":"spotify:album:...","tags":["indie folk"]}` |
| `GET /api/players` | SpotifyPlus players with `devices` source lists, `selected_entity` and `selected_device` |
| `POST /api/player` | Save selection with `{"entity_id":"media_player.your_spotifyplus_player"}` |
| `POST /api/player/device` | Save default destination with `{"device_id":"Living room speaker","expected_entity":"media_player.your_spotifyplus_player"}`; does not start playback |
| `POST /api/play` | Request a confirmed album with `{"album_id":1,"spotify_uri":"spotify:album:..."}` |
| `POST /api/player/control` | `{"action":"pause"}`, `resume`, `next` or `{"action":"volume","volume":0.2}` |
| `POST /api/sync` | Queue history sync; 202 accepted, 409 busy/queued |
| `POST /api/enrich` | Queue next Spotify batch; 202 accepted, 409 busy/queued/disabled |
| `POST /api/metadata` | Queue next Last.fm tag batch; 202 accepted, 409 busy/queued/disabled/paused |
| `POST /api/spotify-library` | Queue the selected SpotifyPlus account's saved-album import; 202 accepted, 409 busy/queued/paused |
| `POST /api/spotify-artists` | Queue one bounded five-artist lookup batch; 202 accepted, 409 busy/queued/paused |
| `POST /api/sync/reset` | Reset interrupted pagination and queue sync; preserves history |
| `GET /api/backup` | Download a consistent SQLite backup |

Only `/health`, `/api/session` and static UI files are public on the direct listener. Private endpoints require a token even if forged Ingress headers are supplied. An empty token disables direct private access. All requests on the Ingress listener require the actual Supervisor network peer.

Playback and control requests can include `device_id` to target a temporary destination without changing the saved default. The device is validated against the selected account's source list. The UI includes `expected_entity` and `expected_device` guards with its requests.

Recommendation parameters: `min_years_unheard` (0–100, default 3), `min_total_scrobbles` (1–10000000, default 20), `genre` (optional exact tag), `playable_only` (`true` by default). Scrobbles count individual track listening events on an album, not complete album plays. The recommendation threshold remains editable in Discover. The UI also permits browsing unconfirmed recommendations. Omit `tags` in confirmation to preserve tags; `[]` removes them. Later enrichment may add tags again.

Playback endpoints can only invoke the fixed SpotifyPlus playback action and allowlisted media controls for a selected SpotifyPlus integration member. They do not accept arbitrary HA services. Playback/control calls are not automatically retried after a timeout; inspect the current player state before trying again.

## Backups and recovery

History, checkpoints, selected player and confirmed links live in `/data/scrobbles.db`. Supervisor manages options and credentials in `/data/options.json`. Include the app in HA backups.

**Download backup**, under Music's **Settings**, uses SQLite's backup API and works while the app is running. It includes private listening history and the saved player ID but no API keys or Supervisor token.

Prefer restoring the full app from an HA backup. Manual database recovery requires stopping the app, preserving the old data, replacing `/data/scrobbles.db` with a consistent backup and removing only the replaced database's old `scrobbles.db-wal`/`scrobbles.db-shm` files before restarting. Do not copy a live `.db` file separately from WAL files.

The database belongs to one Last.fm username. Switching users stops startup to avoid mixed histories and requires a separate clean database and a backup of the old one.

## Verification status

Offline tests cover history preservation, checkpoint recovery, calendar context, authentication/Ingress peer boundaries, confirmed-URI validation, restricted HA service calls and backup recovery. Browser tests use synthetic history, a fake HA and a prefixed Ingress proxy to exercise login-free access, saved player selection, explicit playback, controls and mobile layout. They never start real playback.

The existing HA OS installation, real history import/recommendations and standalone SpotifyPlus call were verified by the user. The new version's real Supervisor Ingress and Core proxy playback still need verification on the target HA server. No LLM or voice search is included.
