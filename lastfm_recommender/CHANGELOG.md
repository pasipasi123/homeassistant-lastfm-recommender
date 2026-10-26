# Changelog

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
