# Changelog

## 0.3.4.2

- Keep volume clicks instant on screen while combining rapid clicks into the latest target after a 300 ms pause.
- Wait for SpotifyPlus to report the previous volume before sending another command, with at least one second between completed requests and the next write.
- Pause volume controls and discard queued changes if SpotifyPlus does not confirm within ten seconds. Resume when its reported volume catches up, without replaying discarded clicks.

## 0.3.4.1

- Filter Spotify suggestions by full artist names, so Arca no longer shows Arcane or other substring matches. Keep genuine collaborations and same-artist edition alternatives for review.
- Apply the same filter to cached suggestions when displaying albums, without additional Spotify requests or changing confirmed playback links.

## 0.3.4

- Raise the default recommendation threshold to 20 track scrobbles per album.
- Add a manual SpotifyPlus artist lookup: at least three unlinked albums of 20 scrobbles each, at most five artists and three pages per artist (20 Spotify requests maximum).
- Identify artists from confirmed album links, skip checked artists for 30 days, and preserve confirmed links. Complete unique exact matches can link automatically; incomplete or ambiguous results need review.
- Show artist batch progress, request counts and results. Persist interruption state and failure retry pauses; artist batches do not start playback or run automatically.

## 0.3.3

- Import saved Spotify albums through the selected SpotifyPlus account in Settings, using pages of 50 and local matching instead of one catalogue search per album.
- Automatically link a unique exact artist/title match from the saved library; retain ambiguous or restricted editions for review. Existing confirmed links are never replaced.
- Show import progress and results. Matching starts only after the complete snapshot is read; failed or interrupted imports leave links unchanged and can be restarted. No additional Spotify login or playback is triggered.

## 0.3.2

- Give Last.fm tags their own batch size and schedule: up to 50 albums per batch with a one-minute pause by default, retaining sequential rate-limited requests. Spotify stays at its existing batch size and interval.
- Add separate Last.fm tag update requests and show checked-album progress separately from tag coverage. Empty results are cached and existing metadata is preserved.
- Persist Last.fm metadata retry deadlines across restarts and manual requests. Pause temporary failures for 15 minutes and honor HTTP Retry-After; Spotify can continue independently.
- Existing `enrich_batch_size` and `enrich_interval_minutes` now control Spotify only. New `lastfm_batch_size` and `lastfm_interval_minutes` control album tags and images; history sync is unchanged.

## 0.3.1.5

- Replace the full Discover device form with a compact, expandable destination beside each album's Play button.
- Save the default playback device in Settings. Album-level device choices apply to the current page session without changing the saved default; reload or choose Use default to return to it.
- Preserve existing saved destinations as defaults. Device selection never starts playback, and controls follow the chosen destination.

## 0.3.1.4

- Fix device-targeted volume commands sending decimal percentages such as `31.0`, which Spotify rejects. Commands now send integer percentages while retaining the saved device destination and immediate local button feedback.

## 0.3.1.3

- Choose and save a Spotify Connect device directly in Discover. Album playback explicitly targets that device, even when Spotify was last used elsewhere.
- Read the device list from SpotifyPlus in Home Assistant without additional Spotify search requests. Unavailable devices never fall back to another player.
- Target playback controls to the saved device and disable them while another device is active, avoiding volume adjustments based on another device's reported level.

## 0.3.1.2

- Show Spotify quota pauses as quiet, readable status notes in Album library and Settings instead of a persistent red Discover banner.
- Display resume times to the next whole minute with today/tomorrow labels, rather than a raw seconds count.
- Keep background update failures in Settings with plain-language summaries and optional collapsed technical details; foreground action errors remain visible.

## 0.3.1

- Honor Spotify HTTP 429 Retry-After deadlines without immediately retrying the request.
- Persist the album lookup cooldown across worker cycles, manual requests and app restarts; keep Last.fm updates independent.
- Show the scheduled resume time in Album library and disable manual Spotify lookup requests during the cooldown.
- Use a 15-minute fallback when Retry-After is absent or invalid, and support both delay seconds and HTTP dates.

## 0.3.0

- Choose Light, Dark or Colorful under Music Settings → Appearance; Light preserves the current palette.
- Apply the palette across navigation, cards, fields, genre chips, playback controls and errors.
- Remember the choice per browser and apply it before the page styles load; theme changes also work when local storage is unavailable.
- Check text contrast, mobile layout and theme persistence in the browser smoke test.

## 0.2.4.2

- Make volume controls respond immediately to rapid clicks, combine queued targets, send absolute levels sequentially and reconcile with the reported player level after updates.
- Bump the app version so Home Assistant detects the volume fix as an available update.

## 0.2.4
- Review Spotify matches and confirm or change the recommended album's link directly in Discover, preserving the album and enabling explicit playback without switching to Album library.
- Handle non-JSON proxy responses with a named request and HTTP status, retry transient read failures once, clear recovered refresh errors and never automatically repeat playback commands.
- Add a quiet Last.fm source credit in the footer and album-specific catalogue links in discovery and library cards.

## 0.2.3

- Display reported volume on a 0.0–100.0 scale without a percent sign and add adjustment buttons in steps of 1.0, using fresh player state and disabling duplicate requests while a control is pending.
- Make the display range, step and decimal precision configurable in app options, with matching backend step conversion and slider scaling.
- Refresh Music with a light palette, blue navigation, coral playback buttons and pastel genre chips.
- Handle empty, null and missing Last.fm album tag/image containers without stopping metadata updates with AttributeError.
- Identify the background operation in UI errors and clear its message after recovery.
- Log the file, line and function for unexpected enrichment failures without exposing exception values or credentials.

## 0.2.2

- Find Spotify album URIs in independent background batches using optional catalogue credentials and a configurable market.
- Automatically link a unique exact artist/album name match after checking all results, up to 30; preserve edition suffixes and existing confirmed links.
- Show ambiguous editions with artwork, release dates, track counts and explicit selection/confirmation in Album library.
- Cache successful and empty lookups for 30 days; leave failed requests pending and keep Last.fm metadata updates independent.
- Move four-digit Last.fm year tags into album metadata and display the year beside the album name, including existing stored tags. Conflicting years remain unknown.
- Preserve history and links with an automatic database migration.

## 0.2.1

- Open Music directly in the HA sidebar through Ingress, using HA login.
- Select and save a discovered SpotifyPlus player in Music Settings.
- Preview and play confirmed albums without scripts, packages or custom dashboard resources.
- Add now-playing information, pause/resume, next-track and volume controls through the Core proxy.
- Keep direct token-authenticated REST access optional; disable its host port by default for new installs.
- Restrict Ingress to the Supervisor peer, keep credentials server-side and validate confirmed album URIs before playback.
- Replace the manual dashboard installation files with a short Ingress setup guide.

## 0.2.0

- Genre-first Music dashboard card with library tag counts, search and preferred genres.
- Local time suggestions for Monday–Thursday, Friday and Weekend listening patterns, with an All genres option.
- Authenticated genre catalogue API and matching genre cloud in the app interface.
- HA package and dashboard examples: select genre, preview an album, then explicitly start SpotifyPlus playback.
- Preserve all other genres; changing filters never starts playback or a recommendation request.
- Collect missing album tags in small batches every five minutes while history sync stays at six hours.

## 0.1.0

- English interface, messages, date formatting and user documentation.
- Resumable Last.fm history import and scheduled overlapping updates.
- Persistent SQLite database, timezone-aware calendar fields and consistent backups.
- Forgotten-album recommendations, Last.fm tags and optional unverified Spotify search suggestions.
- Manual album URI confirmation, local web interface and token-protected REST API.
- Home Assistant / SpotifyPlus playback script example.
