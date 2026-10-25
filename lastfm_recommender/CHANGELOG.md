# Changelog

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
