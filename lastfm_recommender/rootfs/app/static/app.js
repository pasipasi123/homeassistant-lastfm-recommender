"use strict";
const $ = selector => document.querySelector(selector);
const apiUrl = path => path.replace(/^\/+/, "");
let token = sessionStorage.getItem("lastfm-token") || "";
let ingress = false;
let playbackAvailable = false;
let selectedPlayer = null;
let playerReady = false;
let playerDraft = null;
let playerLoading = false;
let genreData = null;
let expandedGenres = false;
let recommendationGeneration = 0;
$("#token").value = token;

function message(text, error = false) {
  $("#message").textContent = text;
  $("#message").className = error ? "error" : "";
}
function authHeaders() {
  return !ingress && token ? {Authorization: `Bearer ${token}`} : {};
}
async function api(path, options = {}) {
  if (!ingress && !token) throw new Error("Enter the app's API token first, or open Music through Home Assistant.");
  const requestToken = token;
  const response = await fetch(apiUrl(path), {...options, headers: {
    ...authHeaders(), "Content-Type": "application/json", ...options.headers
  }});
  const data = await response.json();
  if (!ingress && token !== requestToken) throw new Error("Connection changed. Connect again to refresh the page.");
  if (!response.ok) throw new Error(data.error || (response.status === 409
    ? "A sync is already running or queued." : `HTTP ${response.status}`));
  return data;
}
function date(timestamp) {
  return timestamp ? new Date(timestamp * 1000).toLocaleString("en-GB") : "not yet";
}
function showView(view) {
  for (const name of ["music", "library", "settings"]) {
    $(`#nav-${name}`).setAttribute("aria-pressed", String(name === view));
  }
  $("#discovery-section").hidden = view !== "music";
  $("#now-playing").hidden = view !== "music";
  $("#library-section").hidden = view !== "library";
  $("#status-section").hidden = view !== "settings";
  $("#player-settings").hidden = view !== "settings";
}
for (const view of ["music", "library", "settings"]) {
  $(`#nav-${view}`).addEventListener("click", () => showView(view));
}
function clearRecommendation() {
  recommendationGeneration++;
  $("#recommendation").replaceChildren();
}
async function status() {
  const data = await api("api/status");
  const progress = data.import ? ` Import page ${data.import.page}/${data.import.total_pages || "?"}.` : "";
  $("#status").textContent = `${data.scrobbles.toLocaleString("en-GB")} scrobbles · ${data.albums} albums · ` +
    `${data.confirmed_albums} confirmed Spotify links. Last successful sync: ${date(data.last_sync_at)}. ` +
    `${data.phase === "enrichment" ? "Updating album metadata." : data.running ? "Sync in progress." : data.pending ? "Sync queued." : "Waiting for the next sync."}${progress}`;
  $("#sync").disabled = data.running || data.pending;
  $("#enrich").disabled = !data.spotify_configured || !data.enrichment_enabled || data.running || data.pending || data.enrichment_pending;
  $("#spotify-status").textContent = !data.spotify_configured
    ? "Add Spotify Client ID and Secret in the app configuration to find album links automatically."
    : `${data.confirmed_albums} linked albums (${data.automatic_albums} matched automatically) · ${data.spotify_candidates} awaiting review. Market: ${data.spotify_market}. ` +
      (!data.enrichment_enabled ? "Album updates are disabled; set enrich_batch_size above zero in app configuration."
        : data.enrichment_pending ? "Album updates queued."
        : "Links are checked in small background batches. Use Refresh albums to see new matches.");
  if (data.last_error || data.enrichment_error || data.spotify_error) message(data.last_error || data.enrichment_error || data.spotify_error, true);
  await loadGenres();
}
async function loadGenres() {
  genreData = await api("api/genres?limit=500");
  renderGenres();
}
function renderGenres() {
  if (!genreData) return;
  const data = genreData;
  const selected = $('#recommend input[name="genre"]').value;
  const query = $("#genre-search").value.trim().toLocaleLowerCase("en");
  const aroundNow = $("#genre-context").value === "Around this time";
  const contextual = data.contextual_genres || [];
  const source = aroundNow && contextual.length && !query ? contextual : data.genres;
  const matching = source.filter(genre => genre.name.toLocaleLowerCase("en").includes(query));
  const genres = aroundNow && !query && !expandedGenres ? matching.slice(0, 12) : matching;
  const entries = [{name: "", album_count: data.total_albums}, ...genres];
  $("#genres").replaceChildren(...entries.map(genre => {
    const button = element("button", `${genre.name || "All genres"} (${genre.album_count})`);
    button.type = "button"; button.className = "genre-chip";
    button.setAttribute("aria-pressed", String(genre.name === selected));
    button.addEventListener("click", () => {
      $('#recommend input[name="genre"]').value = genre.name;
      clearRecommendation(); renderGenres();
    });
    return button;
  }));
  $("#more-genres").hidden = !aroundNow || Boolean(query) || matching.length <= 12;
  $("#more-genres").textContent = expandedGenres ? "Show fewer genres" : "Show more genres";
  const context = data.context;
  const contextNote = aroundNow && contextual.length && context && !query
    ? `Based on your ${context.period || context.weekday} listening around ${String(context.hour).padStart(2, "0")}:00 (±2 hours, ${context.timezone}). `
    : aroundNow && !contextual.length ? "Not enough listening history for this time yet; showing library tags. " : "";
  $("#genre-status").textContent = data.genres.length
    ? contextNote + `Last.fm tags cover ${data.tagged_albums} of ${data.total_albums} albums. Counts describe your library, not the current filters.` +
      (data.has_more ? ` Showing the top ${data.genres.length} of ${data.total_genres} tags.` : "")
    : "No genre tags yet. Metadata enrichment adds them gradually; you can also add tags when confirming an album.";
}
$("#genre-context").addEventListener("change", () => { expandedGenres = false; renderGenres(); });
$("#genre-search").addEventListener("input", renderGenres);
$("#more-genres").addEventListener("click", () => { expandedGenres = !expandedGenres; renderGenres(); });
$("#recommend").addEventListener("input", () => { clearRecommendation(); renderGenres(); });
function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}
function safeImage(value) {
  try { const url = new URL(value); return url.protocol === "https:" ? url.href : null; }
  catch { return null; }
}
function albumCard(album, editable = true) {
  const article = element("article"); article.className = "album";
  const image = safeImage(album.image_url);
  if (image) {
    const img = element("img", undefined, article); img.src = image; img.alt = ""; img.loading = "lazy";
  } else {
    const cover = element("div", "♫", article); cover.className = "cover-placeholder"; cover.setAttribute("aria-hidden", "true");
  }
  const content = element("div", undefined, article);
  element("h3", album.album + (album.release_year ? ` (${album.release_year})` : ""), content);
  element("p", `${album.artist} · ${album.scrobbles_total} scrobbles · last played ${date(album.last_listened_at)}`, content);
  element("p", album.tags.length ? album.tags.join(", ") : "No tags yet", content);
  const confirmed = album.spotify_status === "confirmed" && album.spotify_uri;
  if (confirmed) {
    const link = element("a", "Open confirmed album in Spotify", content);
    link.href = "https://open.spotify.com/album/" + album.spotify_uri.split(":").pop();
    link.target = "_blank"; link.rel = "noopener noreferrer";
    if (album.spotify_match_source === "automatic") element("p", "Automatically linked: unique exact artist and album name match. You can change the edition below.", content);
  }
  if (playbackAvailable) {
    const play = element("button", "Play this album", content);
    play.type = "button"; play.className = "play-album";
    play.dataset.confirmed = String(Boolean(confirmed)); play.disabled = !confirmed || !playerReady;
    play.addEventListener("click", async () => {
      play.disabled = true;
      try {
        await api("api/play", {method:"POST", body:JSON.stringify({album_id:album.id, spotify_uri:album.spotify_uri})});
        message("Playback requested."); await loadPlayers();
      } catch (error) { message(error.message, true); }
      finally { play.disabled = !confirmed || !playerReady; }
    });
    if (!confirmed) element("p", "Confirm this album's Spotify link in Album library before playback.", content);
  }
  if (!editable) {
    if (!confirmed) {
      const edit = element("button", "Confirm link in library", content); edit.type = "button"; edit.className = "secondary";
      edit.addEventListener("click", () => {
        $("#query").value = album.album; showView("library"); loadAlbums().catch(error => message(error.message, true));
      });
    }
    return article;
  }
  let candidate = null;
  try { candidate = JSON.parse(album.spotify_candidate); } catch { /* No candidate. */ }
  const choices = candidate?.alternatives || (candidate ? [candidate] : []);
  if (choices.length) {
    const details = element("details", undefined, content);
    element("summary", `Review ${choices.length} Spotify ${choices.length === 1 ? "match" : "matches"}`, details);
    if (!confirmed) element("p", "Choose an edition, then confirm its link below.", details);
    if (candidate.complete === false) element("p", "More results exist. This search is incomplete, so no link was accepted automatically.", details);
    for (const choice of choices) {
      if (!/^spotify:album:[A-Za-z0-9]{22}$/.test(choice.uri)) continue;
      const row = element("div", undefined, details); row.className = "spotify-option";
      const cover = safeImage(choice.image_url);
      if (cover) { const img = element("img", undefined, row); img.src = cover; img.alt = ""; img.loading = "lazy"; }
      const info = element("div", undefined, row);
      element("p", `${(choice.artists || []).join(", ")} – ${choice.name}`, info);
      element("p", [choice.release_date, choice.total_tracks ? `${choice.total_tracks} tracks` : "", choice.exact ? "Exact name match" : "Check artist and edition"].filter(Boolean).join(" · "), info);
      const link = element("a", "Open album in Spotify", info);
      link.href = "https://open.spotify.com/album/" + choice.uri.split(":").pop(); link.target = "_blank"; link.rel = "noopener noreferrer";
      const choose = element("button", "Use this edition", info); choose.type = "button"; choose.className = "secondary";
      choose.addEventListener("click", () => { uri.value = choice.uri; uri.focus(); message("Edition selected. Confirm the album link to save it."); });
    }
  } else if (!confirmed) {
    element("p", album.spotify_checked_at ? "No Spotify match found. You can paste an album link below."
      : "Spotify lookup pending. You can also paste an album link below.", content);
  }
  const form = element("form", undefined, content);
  const label = element("label", "Spotify album link or URI", form);
  const uri = element("input", undefined, label); uri.type = "text"; uri.required = true; uri.maxLength = 2048;
  uri.value = album.spotify_uri || candidate?.uri || ""; uri.placeholder = "https://open.spotify.com/album/…";
  const tagLabel = element("label", "Tags, separated by commas", form);
  const tags = element("input", undefined, tagLabel); tags.value = album.tags.join(", ");
  const button = element("button", "Confirm album link and tags", form);
  form.addEventListener("submit", async event => {
    event.preventDefault(); button.disabled = true;
    try {
      await api(`api/albums/${album.id}`, {method:"POST", body:JSON.stringify({
        spotify_uri:uri.value, tags:tags.value.split(",").map(t=>t.trim()).filter(Boolean)
      })});
      clearRecommendation(); message("Spotify album link confirmed."); await loadAlbums(); await status();
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });
  return article;
}
async function loadAlbums() {
  const data = await api("api/albums?limit=30&q=" + encodeURIComponent($("#query").value));
  $("#albums").replaceChildren(...data.albums.map(album => albumCard(album)));
  if (!data.albums.length) element("p", "No albums found. Wait for the import or try another search.", $("#albums"));
}
function updatePlaybackButtons() {
  for (const button of document.querySelectorAll(".play-album")) button.disabled = !playerReady || button.dataset.confirmed !== "true";
  for (const id of ["player-pause", "player-resume", "player-next", "player-volume"]) $(`#${id}`).disabled = !playerReady;
}
async function loadPlayers() {
  if (!playbackAvailable) {
    $("#player-setup").textContent = "Playback is available when this app runs on Home Assistant OS with SpotifyPlus installed.";
    return;
  }
  if (playerLoading) return;
  playerLoading = true;
  try {
    const data = await api("api/players"); selectedPlayer = data.selected_entity;
    const select = $("#player-select"); select.replaceChildren();
    const placeholder = element("option", "Select a SpotifyPlus player", select); placeholder.value = "";
    for (const player of data.players) { const option = element("option", `${player.name} (${player.entity_id})`, select); option.value = player.entity_id; }
    select.value = playerDraft ?? selectedPlayer ?? "";
    const player = data.players.find(item => item.entity_id === selectedPlayer);
    playerReady = Boolean(player && player.state !== "unavailable");
    $("#player-setup").textContent = !data.players.length
      ? "No SpotifyPlus players found. Install and configure SpotifyPlus in Home Assistant, then refresh players."
      : player ? `Saved player: ${player.name}.` : "Select and save your SpotifyPlus player to enable playback.";
    $("#player-state").textContent = player
      ? `${player.title || "No track playing"}${player.artist ? " — " + player.artist : ""} · ${player.source || player.name} · ${player.state}`
      : "Choose your SpotifyPlus player in Settings to enable playback.";
    if (typeof player?.volume_level === "number" && document.activeElement !== $("#player-volume")) $("#player-volume").value = Math.round(player.volume_level * 100);
  } catch (error) { playerReady = false; message(error.message, true); }
  finally { playerLoading = false; updatePlaybackButtons(); }
}
$("#player-select").addEventListener("change", event => { playerDraft = event.target.value; });
$("#player-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("api/player", {method:"POST", body:JSON.stringify({entity_id:$("#player-select").value})});
    playerDraft = null; message("SpotifyPlus player saved."); await loadPlayers();
  } catch (error) { message(error.message, true); }
});
$("#refresh-players").addEventListener("click", loadPlayers);
for (const action of ["pause", "resume", "next"]) {
  $(`#player-${action}`).addEventListener("click", () => control(action));
}
$("#player-volume").addEventListener("change", event => control("volume", Number(event.target.value) / 100));
async function control(action, volume) {
  try { await api("api/player/control", {method:"POST", body:JSON.stringify({action, volume})}); await loadPlayers(); }
  catch (error) { message(error.message, true); }
}
async function connect() {
  await status();
  if (!ingress) sessionStorage.setItem("lastfm-token", token);
  await Promise.all([loadAlbums(), loadPlayers()]);
}
$("#auth").addEventListener("submit", async event => {
  event.preventDefault(); token = $("#token").value;
  try { await connect(); message("Connected."); } catch (error) { message(error.message, true); }
});
$("#logout").addEventListener("click", () => {
  token = ""; sessionStorage.removeItem("lastfm-token"); $("#token").value = "";
  $("#albums").replaceChildren(); clearRecommendation();
  $("#genres").replaceChildren(); $("#genre-status").textContent = "";
  $("#status").textContent = "Disconnected."; message("Token removed from this tab.");
  $("#player-state").textContent = "Disconnected."; $("#player-setup").textContent = "Connect to choose a player.";
  $("#player-select").replaceChildren(); selectedPlayer = null; playerDraft = null;
  playerReady = false; updatePlaybackButtons();
});
$("#sync").addEventListener("click", async () => {
  try { await api("api/sync", {method:"POST", body:"{}"}); message("Sync queued."); await status(); }
  catch (error) { message(error.message, true); }
});
$("#enrich").addEventListener("click", async () => {
  try { await api("api/enrich", {method:"POST", body:"{}"}); message("Album updates queued. The remaining library continues in scheduled batches."); await status(); }
  catch (error) { message(error.message, true); }
});
$("#refresh-albums").addEventListener("click", async () => {
  try { await loadAlbums(); await status(); } catch (error) { message(error.message, true); }
});
$("#search").addEventListener("submit", async event => {
  event.preventDefault(); try { await loadAlbums(); } catch (error) { message(error.message, true); }
});
$("#recommend").addEventListener("submit", async event => {
  event.preventDefault(); const form = new FormData(event.target);
  form.set("playable_only", form.has("playable_only") ? "true" : "false");
  const generation = ++recommendationGeneration;
  try {
    const data = await api("api/recommend?" + new URLSearchParams(form));
    if (generation !== recommendationGeneration) return;
    $("#recommendation").replaceChildren();
    if (data.album) $("#recommendation").append(albumCard(data.album, false));
    else element("p", "No matching albums. Adjust the filters or include albums without confirmed links.", $("#recommendation"));
  } catch (error) { if (generation === recommendationGeneration) message(error.message, true); }
});
$("#backup").addEventListener("click", async () => {
  try {
    if (!ingress && !token) throw new Error("Connect first.");
    const response = await fetch(apiUrl("api/backup"), {headers:authHeaders()});
    if (!response.ok) throw new Error(`Backup failed: HTTP ${response.status}`);
    const url = URL.createObjectURL(await response.blob());
    const a = element("a"); a.href = url; a.download = "scrobbles.db"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); message("Backup downloaded.");
  } catch (error) { message(error.message, true); }
});
async function bootstrap() {
  const response = await fetch(apiUrl("api/session"));
  if (!response.ok) throw new Error("Could not initialize the Music page.");
  const session = await response.json(); ingress = session.ingress; playbackAvailable = session.home_assistant_available;
  $("#auth").hidden = ingress;
  if (ingress) { token = ""; sessionStorage.removeItem("lastfm-token"); $("#token").value = ""; }
  if (ingress || token) await connect();
}
bootstrap().catch(error => message(error.message, true));
setInterval(() => {
  if (ingress || token) {
    status().catch(error => message(error.message, true));
    loadPlayers();
  }
}, 15000);
