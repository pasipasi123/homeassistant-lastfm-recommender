# Last.fm Recommender

Rediscover forgotten favorites from your Last.fm history. Runs locally as a Home Assistant OS app.

For the recommended setup, enter your Last.fm username/API key and Spotify Client ID/Secret in **Configuration**, set `spotify_market` to your Spotify account country, then start the app. Spotify credentials enable automatic album-link discovery; without them, album links need to be pasted and confirmed manually. Playback uses your existing SpotifyPlus integration and its own authentication.

Enable **Show in sidebar**, open **Music**, then select and save your SpotifyPlus player in Music's **Settings**. Album matching runs gradually in the background; review uncertain editions under **Album library**.

Choose **Light**, **Dark** or **Colorful** under **Music → Settings → Appearance**. The theme applies immediately and is remembered in this browser.

See [DOCS.md](DOCS.md) for installation, options, API and SpotifyPlus playback setup.
