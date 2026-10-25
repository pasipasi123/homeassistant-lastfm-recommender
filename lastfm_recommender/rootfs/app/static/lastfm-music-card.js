/* HA custom card. All data and playback requests go through Home Assistant. */
class LastfmMusicCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this._query = "";
    this._expanded = false;
    this._busy = false;
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block}ha-card{display:block;padding:24px;border-radius:12px;background:var(--card-background-color);color:var(--primary-text-color)}
        h2{margin:0 0 8px;font-size:24px;font-weight:500}p{color:var(--secondary-text-color);line-height:1.5}
        input{box-sizing:border-box;width:100%;padding:11px;border:1px solid var(--divider-color,#888);border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color);font:inherit}
        .cloud{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0;max-height:300px;overflow:auto;padding:3px}
        button{cursor:pointer;border:1px solid var(--divider-color,#888);border-radius:24px;padding:9px 14px;background:transparent;color:var(--primary-text-color);font:inherit;font-size:14px}
        button[aria-pressed="true"],.primary{background:var(--primary-color,#03a9f4);border-color:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff)}
        button:disabled{opacity:.45;cursor:default}button:focus-visible,input:focus-visible{outline:2px solid var(--primary-color);outline-offset:3px}
        .actions{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}.note{font-size:12px}.selection{font-weight:500}
        .album{display:flex;align-items:start;gap:18px;border-top:1px solid var(--divider-color);padding-top:20px;margin-top:20px}
        .cover{width:100px;height:100px;object-fit:cover;border-radius:10px;flex-shrink:0}.placeholder{display:grid;place-items:center;background:var(--secondary-background-color);font-size:38px}
        h3{margin:0;font-size:20px;overflow-wrap:anywhere}.details{min-width:0}.details p{margin:6px 0}.error{color:var(--error-color,#db4437)}
        [hidden]{display:none!important}@media(max-width:450px){ha-card{padding:18px}.cover{width:72px;height:72px}}
      </style>
      <ha-card>
        <h2 id="title"></h2>
        <p>Start with a genre. Rediscover an album when you are ready.</p>
        <input id="search" type="search" aria-label="Filter genres" placeholder="Filter genres…">
        <div id="cloud" class="cloud" role="group" aria-label="Choose a genre"></div>
        <button id="more" type="button" hidden>Show more genres</button>
        <p id="coverage" class="note"></p>
        <p id="selection" class="selection"></p>
        <p id="setup" class="error" role="status"></p>
        <div class="actions">
          <button id="find" class="primary" type="button">Find a forgotten favorite</button>
          <button id="refresh" type="button">Refresh genres</button>
        </div>
        <div id="album" aria-live="polite"></div>
        <p id="error" class="error" role="status"></p>
      </ha-card>`;
    this._node("search").addEventListener("input", event => {
      this._query = event.target.value.toLocaleLowerCase("en");
      this._renderCloud();
    });
    this._node("more").addEventListener("click", () => {
      this._expanded = !this._expanded;
      this._renderCloud();
    });
    this._node("find").addEventListener("click", () => this._call(
      "script", this._config.recommend_script.split(".")[1], {}));
    this._node("refresh").addEventListener("click", () => this._call(
      "homeassistant", "update_entity", {entity_id: this._config.genre_entity}));
  }

  _node(id) { return this.shadowRoot.getElementById(id); }

  setConfig(config) {
    this._config = {
      title: "Forgotten favorites", genre_entity: "sensor.lastfm_genres",
      selected_genre_entity: "input_text.lastfm_genre",
      context_entity: "input_select.lastfm_genre_context",
      recommendation_entity: "sensor.lastfm_recommendation",
      years_entity: "input_number.lastfm_years_unheard",
      scrobbles_entity: "input_number.lastfm_min_scrobbles",
      recommend_script: "script.lastfm_music_recommend",
      play_script: "script.lastfm_music_play",
      preferred_genres: [], max_genres: 12, ...config
    };
    if (!Number.isInteger(this._config.max_genres) || this._config.max_genres < 1 ||
        !Array.isArray(this._config.preferred_genres) ||
        this._config.preferred_genres.some(genre => typeof genre !== "string")) {
      throw new Error("Use a positive max_genres and a list of preferred_genres.");
    }
    for (const key of ["recommend_script", "play_script"]) {
      if (!/^script\.[a-z0-9_]+$/.test(this._config[key])) throw new Error(`${key} must be a script entity ID.`);
    }
    this._lastStates = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const states = ["genre_entity", "selected_genre_entity", "recommendation_entity", "years_entity",
      "scrobbles_entity", "context_entity", "recommend_script", "play_script"].map(key => hass.states[this._config[key]]);
    if (!this._lastStates || states.some((state, index) => state !== this._lastStates[index])) {
      this._lastStates = states;
      this._render();
    }
  }

  getCardSize() { return 8; }
  _state(key) { return this._hass?.states[this._config[key]]; }
  _genre() {
    const state = this._state("selected_genre_entity")?.state;
    return !state || ["unknown", "unavailable"].includes(state) ? "" : state;
  }

  async _call(domain, service, data) {
    if (this._busy || !this._hass) return;
    this._busy = true;
    this._node("error").textContent = "";
    this._render();
    try { await this._hass.callService(domain, service, data); }
    catch (error) { this._node("error").textContent = error.message || "Home Assistant could not complete the action."; }
    finally { this._busy = false; this._render(); }
  }

  _button(text, onClick, parent) {
    const button = document.createElement("button");
    button.type = "button"; button.textContent = text; button.disabled = this._busy;
    button.addEventListener("click", onClick); parent.append(button);
    return button;
  }

  _renderCloud() {
    if (!this._config || !this._hass) return;
    const data = this._state("genre_entity")?.attributes || {};
    const aroundNow = this._state("context_entity")?.state !== "All genres";
    const contextual = Array.isArray(data.contextual_genres) ? data.contextual_genres : [];
    // Searching always searches the full catalogue; sparse history falls back to all tags.
    const source = aroundNow && !this._query && contextual.length ? contextual : data.genres;
    const genres = Array.isArray(source) ? source.filter(g => typeof g.name === "string") : [];
    const preferred = this._config.preferred_genres.map(g => g.toLocaleLowerCase("en"));
    genres.sort((a, b) => {
      const rank = name => { const index = preferred.indexOf(name.toLocaleLowerCase("en")); return index < 0 ? Infinity : index; };
      return (rank(a.name) - rank(b.name)) ||
        (aroundNow && !this._query ? (b.context_score || 0) - (a.context_score || 0) : 0) ||
        (b.album_count - a.album_count) || a.name.localeCompare(b.name, "en");
    });
    const matching = genres.filter(g => g.name.toLocaleLowerCase("en").includes(this._query));
    const shown = this._expanded || this._query ? matching : matching.slice(0, this._config.max_genres);
    const cloud = this._node("cloud"); cloud.replaceChildren();
    const all = this._button("All genres", () => this._selectGenre(""), cloud);
    all.setAttribute("aria-pressed", String(!this._genre()));
    for (const genre of shown) {
      const button = this._button(`${genre.name} (${genre.album_count})`, () => this._selectGenre(genre.name), cloud);
      button.setAttribute("aria-pressed", String(this._genre() === genre.name));
      button.title = `${genre.album_count} albums; ${genre.playable_album_count} with confirmed Spotify links; ${genre.context_scrobbles || 0} scrobbles around this time`;
    }
    this._node("more").hidden = Boolean(this._query) || matching.length <= this._config.max_genres;
    this._node("more").textContent = this._expanded ? "Show fewer genres" : `Show all ${matching.length} genres`;
    const context = data.context;
    const contextNote = aroundNow && context && contextual.length && !this._query
      ? `Based on your ${context.period || context.weekday} listening around ${String(context.hour).padStart(2, "0")}:00 (±2 hours, ${context.timezone}). `
      : aroundNow && !contextual.length ? "Not enough listening history for this time yet; showing library tags. " : "";
    this._node("coverage").textContent = genres.length
      ? contextNote + `Last.fm tags: ${data.tagged_albums ?? "?"} of ${data.total_albums ?? "?"} albums tagged. Counts describe the library, not the current filters.` +
        (data.has_more ? ` Showing the top ${genres.length} of ${data.total_genres} tags.` : "")
      : "No genre tags yet. Enrichment adds them gradually; you can also add tags in the app.";
  }

  _selectGenre(genre) {
    return this._call("input_text", "set_value", {entity_id: this._config.selected_genre_entity, value: genre});
  }

  _render() {
    if (!this._config || !this._hass) return;
    this._node("title").textContent = this._config.title;
    this._renderCloud();
    this._node("selection").textContent = `Selected genre: ${this._genre() || "All genres"}`;
    const missing = ["genre_entity", "selected_genre_entity", "context_entity", "years_entity", "scrobbles_entity",
      "recommend_script", "play_script"].filter(key => !this._state(key)).map(key => this._config[key]);
    const unavailable = this._state("genre_entity")?.state === "unavailable";
    this._node("setup").textContent = missing.length ? `Missing entities: ${missing.join(", ")}. Install the Music package first.`
      : unavailable ? "Genre library is unavailable. Check the app connection and refresh genres." : "";
    const running = this._state("recommend_script")?.state === "on";
    this._node("find").disabled = this._busy || running || missing.length > 0;
    this._node("find").textContent = running ? "Finding an album…" : "Find a forgotten favorite";
    this._node("refresh").disabled = this._busy || !this._state("genre_entity");
    const recommendation = this._state("recommendation_entity")?.attributes;
    const container = this._node("album"); container.replaceChildren();
    const paragraph = (text, parent = container) => {
      const p = document.createElement("p"); p.textContent = text; parent.append(p); return p;
    };
    const current = recommendation && recommendation.genre === this._genre() &&
      Number(recommendation.min_years_unheard) === Number(this._state("years_entity")?.state) &&
      Number(recommendation.min_total_scrobbles) === Number(this._state("scrobbles_entity")?.state);
    if (!current) {
      paragraph("Choose a genre, then find an album. Changing filters does not start a search or playback.");
      return;
    }
    if (recommendation.error) { paragraph(recommendation.error).className = "error"; return; }
    const album = recommendation.album;
    if (!album || typeof album.album !== "string") {
      paragraph("No matching confirmed albums. Try different filters or confirm more Spotify links in the app.");
      return;
    }
    const wrapper = document.createElement("div"); wrapper.className = "album";
    container.append(wrapper);
    let image;
    try { const url = new URL(album.image_url); if (url.protocol === "https:") image = url.href; } catch { /* No cover. */ }
    const cover = document.createElement(image ? "img" : "div"); cover.className = "cover";
    if (image) { cover.src = image; cover.alt = ""; }
    else { cover.classList.add("placeholder"); cover.textContent = "♫"; }
    wrapper.append(cover);
    const details = document.createElement("div"); details.className = "details"; wrapper.append(details);
    const heading = document.createElement("h3"); heading.textContent = album.album; details.append(heading);
    paragraph(album.artist, details);
    const lastPlayed = album.last_listened_at ? new Date(album.last_listened_at * 1000).toLocaleDateString("en-GB") : "unknown";
    paragraph(`${album.scrobbles_total} scrobbles · Last played ${lastPlayed}`, details);
    const play = this._button("Play this album", () => this._call("script", this._config.play_script.split(".")[1], {}), details);
    play.className = "primary";
    play.disabled = this._busy || album.spotify_status !== "confirmed" || !/^spotify:album:[A-Za-z0-9]{22}$/.test(album.spotify_uri);
    this._node("find").textContent = running ? "Finding an album…" : "Another suggestion";
  }
}

if (!customElements.get("lastfm-music-card")) customElements.define("lastfm-music-card", LastfmMusicCard);
window.customCards = window.customCards || [];
window.customCards.push({type: "lastfm-music-card", name: "Last.fm Music", description: "Genre-first album discovery and SpotifyPlus playback"});
