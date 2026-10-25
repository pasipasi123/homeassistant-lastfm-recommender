# Music dashboard setup

This dashboard puts genre selection before recommendations. It uses one small custom card, standard HA helpers/sensors/scripts and your existing SpotifyPlus installation. No additional HACS integration is required.

The API token stays in HA's `secrets.yaml`. The card communicates through HA's authenticated connection; it does not connect to the app directly or need CORS access.

## 1. Update the app

Update **Last.fm Recommender** to **0.2.0** or newer under **Settings → Apps**. Refresh the app store's repositories if the update is not listed. Keep your existing configuration and database; no reimport is required. The additional context index is created automatically at startup.

The app now provides `/api/genres`. It includes counts from your imported library and context-based suggestions. Genre tags are gathered gradually by metadata enrichment. The default is 10 albums every five minutes, independently of the six-hour history sync. These settings can be adjusted in app options; `enrich_batch_size: 0` disables enrichment.

## 2. Add the HA package

Use your existing HA file editor or configuration file access:

1. Create `/config/packages/` if it does not exist.
2. Copy [lastfm_music.yaml](lastfm_music.yaml) to `/config/packages/lastfm_music.yaml`.
3. Replace **both** `HA_SERVER_IP` placeholders in that file with your HA server's LAN IP. Do not use `localhost`: Core and the app are separate containers.
4. In `/config/secrets.yaml`, set the full Bearer header, using the same token as the app:

   ```yaml
   lastfm_recommender_authorization: "Bearer YOUR_APP_API_TOKEN"
   ```

5. Enable packages in `/config/configuration.yaml`. Merge this into the existing `homeassistant:` section; do not add a duplicate section or replace existing configuration:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

6. Check the HA configuration, then restart **Home Assistant Core**. The separate app can continue its history import.

The package adds:

- `sensor.lastfm_genres`: tag catalogue, counts and current listening context; refreshed every 15 minutes.
- `input_text.lastfm_genre`: selected genre, empty for all genres.
- `input_select.lastfm_genre_context`: **Around this time** or **All genres**.
- `input_number.lastfm_years_unheard` and `input_number.lastfm_min_scrobbles`: recommendation filters.
- `script.lastfm_music_recommend`: explicitly fetch a recommendation.
- `sensor.lastfm_recommendation`: the resulting album and the filters used for that request.
- `script.lastfm_music_play`: play the displayed confirmed album through SpotifyPlus.

Check these IDs under **Developer tools → States**. Existing entities with the same names may cause HA to assign a suffix. If necessary, update the entity IDs consistently in the package and card configuration. `sensor.lastfm_recommendation` may be unavailable until the first search; this is expected.

Replace `media_player.your_spotifyplus_player` in both the package's playback script and the dashboard's media-control card with your actual SpotifyPlus entity ID. Find it under **Developer tools → States** by searching for `spotifyplus`. This is the SpotifyPlus account player entity, not the receiver's HEOS entity.

Playback uses the active Spotify device, or the SpotifyPlus default when no device is active. To target a particular receiver regardless of the active device, separately test an explicit `device_id: "Your Spotify Connect device name"` in the SpotifyPlus call. A Spotify Connect name is different from an HA entity ID.

If your device is available in Spotify Connect, a separate Home Assistant power-on action is generally unnecessary: send the SpotifyPlus playback request directly, as shown in the package. If the device is unavailable, check its network standby settings and whether it needs to be powered on before retrying.

## 3. Install the card resource

1. Copy [lastfm-music-card.js](../lastfm_recommender/rootfs/app/static/lastfm-music-card.js) to `/config/www/lastfm-music-card.js`. Create `www` if needed. The same file is available from your updated app at `http://HA_SERVER_IP:8099/lastfm-music-card.js`; save its contents without changing the extension.
2. Enable **Advanced mode** in your HA user profile if necessary.
3. Open **Settings → Dashboards → ⋮ → Resources** and add:
   - URL: `/local/lastfm-music-card.js?v=0.2.0`
   - Resource type: **JavaScript Module**
4. Reload the browser after saving. When updating the card later, replace the local file and change the version suffix to refresh the cache. The app update alone does not replace the copy in `/config/www`.

## 4. Create the Music dashboard

1. Open **Settings → Dashboards → Add dashboard → New dashboard from scratch**.
2. Name it **Music**, choose `mdi:music`, enable **Show in sidebar**, and create it.
3. Open the new dashboard, select **Edit dashboard**, and take control if prompted.
4. Open **⋮ → Raw configuration editor**. Replace only this new dashboard's content with [music-dashboard.yaml](music-dashboard.yaml) and save.

The dashboard contains the genre cloud, discovery filters and a SpotifyPlus player card. Genre information loads when the REST sensor starts, before any recommendation request. Opening the dashboard, choosing a genre and changing filters do not start a recommendation request or playback.

## Daily use

1. Choose a genre from the cloud. The active genre is highlighted. **All genres** clears the filter.
2. Select **Find a forgotten favorite** to preview an album with its cover, artist, scrobble count and last-listened date.
3. Select **Another suggestion** for a new result, or **Play this album** to start playback.

Changing a genre or numeric filter hides an old recommendation until you search again. The playback script also checks these filters so an outdated suggestion is not accidentally played.

**Around this time** shows up to 12 time-relevant tags by default. It learns from local listening calendar fields using three fixed periods:

- **Monday–Thursday**: combined weekday history.
- **Friday**: Friday history only.
- **Weekend**: combined Saturday and Sunday history.

Within that period it examines hours within ±2 hours of the current local hour, using the app's configured timezone. At midnight it keeps observations within the same period, so Friday and weekend histories remain separate. The pattern uses all stored years, not just recent listening.

Tags need at least three matching scrobbles to enter the contextual list. Ranking uses `context_scrobbles / sqrt(total_scrobbles + 20)` to balance relevant listening against a tag's overall size and reduce the influence of tiny samples. If there is not enough evidence, the cloud falls back to the full library. This affects genre ordering only; it does not silently restrict album recommendations to a time window.

Choose **All genres** in **Discovery filters** to browse by overall album counts. **Filter genres** searches the full downloaded catalogue regardless of the current time, and **Show more genres** expands the cloud. The endpoint returns the top 500 tags for each ordering; the card reports when the library has more. Selecting a tag that was found through search still uses that exact tag as the recommendation filter.

Counts describe all tagged albums, including those without confirmed Spotify links. They are not counts of currently eligible forgotten albums. A genre can therefore produce no matching confirmed recommendation. Confirm more links in the app or adjust the filters.

Last.fm tags are community metadata, not a clean genre taxonomy; moods and other labels may appear. Tags can overlap, so counts cannot be added to obtain a unique album total. Manually added tags appear too.

## Customize favorite genres

Edit `preferred_genres` in the card YAML to promote the tags you use most. Names must match the library's tags. This does not invent missing tags or exclude other music. In contextual mode, preferences are promoted among the contextual suggestions; search or **All genres** exposes other tags.

```yaml
type: custom:lastfm-music-card
title: Forgotten favorites
max_genres: 12
preferred_genres:
  - jazz
  - indie folk
  - ambient
```

The card also accepts `genre_entity`, `selected_genre_entity`, `context_entity`, `recommendation_entity`, `years_entity`, `scrobbles_entity`, `recommend_script` and `play_script` for installations with different entity IDs.

## Future listening contexts

Custom weekday groups, time blocks and household-presence rules are planned separately. This release uses the three periods above; it does not infer whether family members are home. HA presence data and explicitly chosen quiet-listening genres can be added later without changing how album confirmation or playback works.

## Verification status

The genre API and time-period logic have offline tests. The app and custom card have browser tests with synthetic history and simulated HA states/services. Package/dashboard YAML has been parsed, but a full HA Core configuration check and end-to-end dashboard installation are still required on the target server. The card test never starts real playback.

References: [HA packages](https://www.home-assistant.io/docs/configuration/packages/), [REST sensors](https://www.home-assistant.io/integrations/rest/), [template entities](https://www.home-assistant.io/integrations/template/), [custom cards](https://contributors.home-assistant.io/frontend/custom-ui/card/), [dashboards](https://www.home-assistant.io/dashboards/dashboards/).
