# Music sidebar setup

Version **0.2.4.2** uses Home Assistant Ingress. No dashboard YAML, configuration package, custom card, resource registration or separate Home Assistant token is required.

## Update and open Music

1. Update **Last.fm Recommender** under **Settings → Apps**. If needed, open **Install app → ⋮ → Check for updates** first.
2. In the app's **Configuration** tab, set your Last.fm username/API key. For automatic album links, **we recommend also setting Spotify Client ID/Secret** and `spotify_market` to your account country (default `FI`). Start or restart the app, then enable **Show in sidebar** on its app page.
3. Select **Music** in the sidebar, or use **Open Web UI**.
4. Open **Settings** inside Music, select your **SpotifyPlus player** from the list, and select **Save player**.

The player list comes from your installed SpotifyPlus integration, including entities you have renamed. The saved selection belongs to your installation and is stored in the app's database. Example documentation contains no personal entity IDs.

Your existing Last.fm username, API key, history, tags and confirmed Spotify links are preserved during the update. You do not need to repeat the import. New installations require only the Last.fm username and API key in app configuration before starting.

Home Assistant handles login for the Music page. Do not enter your Last.fm API key, Last.fm shared secret or an HA access token in the Music page. The app uses its Supervisor-provided Core API permission to call SpotifyPlus; that credential stays on the server.

## Daily use

- **Discover**: choose a genre first, adjust the age/count filters, then select **Find a forgotten favorite**. Review Spotify matches and confirm the album link on the same card; there is no need to switch to Album library. **Check or change Spotify link** also lets you correct an already linked edition.
- **Play this album**: start a confirmed album on the selected SpotifyPlus account's active/default Spotify Connect device.
- **Now playing**: view the current track/source, pause, resume or skip. Volume is shown on a 0.0–100.0 scale (for example, **32.0**); use **− / +** for steps of 1.0 or the slider for larger changes.
- **Album library**: find Spotify links, review uncertain editions, confirm a link and edit tags. Unique exact artist/album matches are linked automatically when catalogue credentials are configured.
- **Settings**: choose your SpotifyPlus player, check history import progress, request a sync or download a backup.

Configure the volume scale in the HA app's **Configuration** tab with `volume_min`, `volume_max`, `volume_step` and `volume_decimals`, then restart. Defaults are 0.0–100.0, step 1.0 and one decimal place. For gentler adjustment, set `volume_step: 0.5`. These are display units mapped linearly to HA's 0–1 volume level.

Opening Music or choosing genres does not fetch a recommendation or start playback. Changing recommendation filters clears the previous result. Playback always requires a separate button press and a confirmed Spotify album link.

If your device is available in Spotify Connect, a separate Home Assistant power-on action is generally unnecessary: the app sends the SpotifyPlus playback request directly. If unavailable, check the device's network standby settings and whether it needs to be powered on before retrying.

The selected SpotifyPlus entity represents a Spotify account, not a guaranteed physical receiver. Playback uses that account's active/default Connect device. Make the intended receiver active in Spotify or configure the account's default in SpotifyPlus when you use multiple devices.

## Genre suggestions

**Around this time** shows up to 12 relevant tags from your own history, combining these periods:

- **Monday–Thursday**
- **Friday**
- **Weekend** (Saturday and Sunday)

Within the current period it uses hours within ±2 hours of the current local hour, in the app's configured timezone. Observations stay in the same period near midnight. All stored years contribute. Tags need at least three matching scrobbles; ranking is `context_scrobbles / sqrt(total_scrobbles + 20)`.

If there is not enough evidence, it falls back to library tags. **All genres**, **Filter genres** and **Show more genres** expose other choices. The API returns up to 500 tags per ordering. No genre is prohibited, and the time weighting does not silently restrict album recommendations to a time window.

Counts describe all tagged albums, including unconfirmed ones, rather than albums eligible for the current recommendation filters. Tags overlap and can include moods or other community labels. Enrichment gradually adds tags in small batches; the history sync interval remains six hours by default.

Four-digit year tags are moved to album metadata and displayed beside album names, rather than as genre buttons. Conflicting years remain unknown; decade tags such as `2000s` stay in the cloud.

## Recommended: automatic Spotify links

Add Spotify Client ID/Secret in the app configuration, set `spotify_market` to your account country (default `FI`), and restart. This is recommended for everyday use: it avoids manually copying Spotify links for each album in your history. Without these credentials, links must be pasted and confirmed manually before albums can be played from Music.

The app searches unlinked albums in batches of 10 every five minutes by default, independently of Last.fm metadata. Large libraries fill in gradually, and already linked albums can be played immediately. Confirmed links survive updates. The catalogue credentials are separate from SpotifyPlus authentication; no changes to your existing SpotifyPlus login are needed.

Under **Album library**, **Find Spotify links** queues the next batch; **Refresh albums** loads new results. A unique exact artist and album match is linked automatically. Other results appear in **Review … Spotify matches** with edition details. Select **Use this edition**, then **Confirm album link and tags**. You can always paste a link manually. Searching and confirming never start playback.

Custom listening periods and household-presence rules are future settings. This version does not infer whether family members are home.

## Troubleshooting

- **No SpotifyPlus players found**: check that SpotifyPlus is installed and configured in HA, then select **Refresh players**. There is no need to rename your entity to include `spotifyplus`.
- **Home Assistant denied access**: update and restart the app so its `homeassistant_api` permission takes effect.
- **No matching confirmed albums**: confirm more album links under **Album library**, loosen the filters or include unconfirmed albums to browse suggestions.
- **No genre tags yet**: wait for metadata enrichment, or add tags when confirming an album. A history import alone does not contain album genre tags.
- **Music is not in the sidebar**: enable **Show in sidebar** on the app page. The panel is administrator-only by default.
- **No track change after playback**: check the selected account's active/default Connect device and HA's SpotifyPlus logs. The app reports that playback was requested; it cannot guarantee the device produced sound.

## Optional direct access

Ingress needs no exposed host port and no app API token. For external REST automations or direct browser access, set a random `api_token` of at least 32 characters in the app options and enable the optional port 8099 mapping. Direct access continues to require that token. Existing installations may retain their previous port mapping and token; close the mapping if no longer needed.

## Migrating an earlier dashboard

If you have not installed the 0.2.0 dashboard files, skip those instructions and use Ingress instead. The old package, dashboard YAML and JavaScript card are no longer needed for Music. If you already installed them, you can remove those specific old files/resources/dashboard after verifying the Ingress page. Do not remove unrelated HA configuration.

References: [HA Ingress](https://contributors.home-assistant.io/apps/guides/ingress/) and [Core API access from apps](https://contributors.home-assistant.io/apps/guides/communication/).
