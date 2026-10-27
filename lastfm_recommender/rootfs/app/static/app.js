"use strict";
const $ = selector => document.querySelector(selector);
const apiUrl = path => path.replace(/^\/+/, "");
let token = sessionStorage.getItem("lastfm-token") || "";
let ingress = false;
let playbackAvailable = false;
let selectedPlayer = null;
let selectedDevice = null;
let defaultDevice = null;
let temporaryDevice = null;
let availableDevices = [];
let libraryActionBlocked = true;
let artistActionBlocked = true;
let deviceDraft = null;
let deviceSaving = false;
let controlReady = false;
let playerReady = false;
let playerDraft = null;
let playerLoading = false;
let playerVolume = null;
let controlBusy = false;
let controlError = "";
let volumeConfig = {min: 0, max: 100, step: 1, decimals: 1};
let volumeRequestActive = false;
let volumeNextSendAt = 0;
let volumeState = newVolumeState();
let genreData = null;
let expandedGenres = false;
let recommendationGeneration = 0;
let backgroundMessage = false;
const refreshErrors = new Map();
$("#token").value = token;
for (const input of document.querySelectorAll('input[name="theme"]')) {
  input.checked = input.value === document.documentElement.dataset.theme;
  input.addEventListener("change", () => { if (input.checked) window.musicTheme.apply(input.value); });
}

function message(text, error = false, background = false) {
  backgroundMessage = background || (error && [...refreshErrors.values()].includes(text));
  $("#message").textContent = text;
  $("#message").className = error ? "error" : "";
}
function authHeaders() {
  return !ingress && token ? {Authorization: `Bearer ${token}`} : {};
}
function backgroundErrors() {
  const errors = [...refreshErrors.values()];
  if (errors.length) message(errors.join(" · "), true, true);
  else if (backgroundMessage) message("");
}
async function requestJson(path, options = {}) {
  const endpoint = path.split("?")[0].replace(/^\/+/, "");
  const label = {"api/session":"Music connection", "api/status":"Library status", "api/genres":"Genre list",
    "api/players":"Player status", "api/albums":"Album library", "api/recommend":"Album recommendation",
    "api/play":"Playback", "api/player/control":"Player control"}[endpoint] || "Music request";
  const readOnly = !options.method || options.method === "GET";
  for (let attempt = 0; attempt < 2; attempt++) {
    let response;
    try { response = await fetch(apiUrl(path), options); }
    catch { throw new Error(`${label}: connection failed. Check the app and reopen Music from the Home Assistant sidebar.`); }
    if (readOnly && attempt === 0 && [502, 503, 504].includes(response.status)) {
      await response.body?.cancel();
      await new Promise(resolve => setTimeout(resolve, 750));
      continue;
    }
    let data;
    try { data = await response.json(); }
    catch {
      const advice = !readOnly && ["api/play", "api/player/control"].includes(endpoint)
        ? "Check the player state before retrying; the command was not automatically repeated."
        : "The app or Home Assistant proxy returned an unexpected response. Reopen Music from the sidebar.";
      throw new Error(`${label}: HTTP ${response.status}, expected a JSON response. ${advice}`);
    }
    if (!response.ok) throw new Error(`${label}: ${data?.error || `HTTP ${response.status}`}`);
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error(`${label}: invalid response format. Reopen Music from the sidebar.`);
    return data;
  }
}
async function api(path, options = {}) {
  if (!ingress && !token) throw new Error("Enter the app's API token first, or open Music through Home Assistant.");
  const requestToken = token;
  const endpoint = path.split("?")[0];
  const refresh = ["api/status", "api/genres", "api/players"].includes(endpoint);
  try {
    const data = await requestJson(path, {...options, headers: {
      ...authHeaders(), "Content-Type": "application/json", ...options.headers
    }});
    if (!ingress && token !== requestToken) throw new Error("Connection changed. Connect again to refresh the page.");
    if (refresh) { refreshErrors.delete(endpoint); backgroundErrors(); }
    return data;
  } catch (error) {
    if (refresh && (ingress || token === requestToken)) refreshErrors.set(endpoint, error.message);
    throw error;
  }
}
function date(timestamp) {
  return timestamp ? new Date(timestamp * 1000).toLocaleString("en-GB") : "not yet";
}
function resumeTime(timestamp) {
  // Round up: a minute-only label must not promise a retry before the deadline.
  const until = new Date(Math.ceil(timestamp / 60) * 60000);
  const now = new Date();
  const tomorrow = new Date(now); tomorrow.setDate(tomorrow.getDate() + 1);
  const clock = until.toLocaleTimeString("en-GB", {hour:"2-digit", minute:"2-digit"});
  if (until.toDateString() === now.toDateString()) return `${clock} today`;
  if (until.toDateString() === tomorrow.toDateString()) return `${clock} tomorrow`;
  return until.toLocaleDateString("en-GB", {day:"numeric", month:"short",
    ...(until.getFullYear() !== now.getFullYear() ? {year:"numeric"} : {})}) + ` at ${clock}`;
}
function maintenanceStatus(data, pauseText) {
  const notes = [];
  const details = [];
  if (data.last_error) {
    notes.push("Listening history could not be updated. The app will try again automatically.");
    details.push(`History sync: ${data.last_error}`);
  }
  if (data.enrichment_error) {
    notes.push(data.lastfm_retry_at && data.lastfm_retry_at * 1000 > Date.now()
      ? `Last.fm album details are paused until ${resumeTime(data.lastfm_retry_at)}. You can continue using your library.`
      : "Some album details could not be updated. You can continue using your library.");
    details.push(`Last.fm metadata: ${data.enrichment_error}`);
  }
  if (pauseText) notes.push(pauseText);
  else if (data.spotify_error) notes.push("Spotify album links could not be updated. You can still play linked albums.");
  if (data.spotify_error) details.push(`Spotify lookup: ${data.spotify_error}`);
  $("#background-status").textContent = notes.join(" ");
  $("#background-status").hidden = !notes.length;
  $("#background-details").hidden = !details.length;
  if (!details.length) $("#background-details").open = false;
  $("#background-details-text").textContent = details.join("\n");
}
function showView(view) {
  for (const name of ["music", "library", "settings"]) {
    $(`#nav-${name}`).setAttribute("aria-pressed", String(name === view));
  }
  $("#discovery-section").hidden = view !== "music";
  $("#now-playing").hidden = view !== "music";
  $("#library-section").hidden = view !== "library";
  $("#status-section").hidden = view !== "settings";
  $("#appearance-settings").hidden = view !== "settings";
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
    `${data.phase === "spotify_artists" ? "Looking up artists' albums." : data.phase === "spotify_library" ? "Importing saved Spotify albums." : data.phase === "enrichment" ? "Updating album metadata." : data.running ? "Sync in progress." : data.pending ? "Sync queued." : "Waiting for the next sync."}${progress}`;
  $("#sync").disabled = data.running || data.pending;
  const library = data.spotify_library_import;
  const artistJob = data.spotify_artist_import;
  const artistPaused = artistJob?.retry_at && artistJob.retry_at * 1000 > Date.now();
  const artistBusy = ["queued", "running"].includes(artistJob?.status);
  const libraryPaused = library?.retry_at && library.retry_at * 1000 > Date.now();
  const importBusy = data.running || data.pending || ["queued", "running"].includes(library?.status) || artistBusy;
  libraryActionBlocked = importBusy || libraryPaused;
  artistActionBlocked = importBusy || artistPaused;
  $("#import-spotify-artists").disabled = !playbackAvailable || !selectedPlayer || artistActionBlocked;
  $("#spotify-artist-status").textContent = !artistJob ? "Uses known artist identities from confirmed albums. Artists are checked at most once every 30 days."
    : artistJob.status === "queued" ? "Artist lookup queued."
    : artistJob.status === "running" ? `Checked ${artistJob.artists} of ${artistJob.selected ?? 5} artists; ${artistJob.requests} Spotify requests so far.`
    : artistJob.status === "complete" ? `${artistJob.artists} artists checked using ${artistJob.requests} Spotify requests. ${artistJob.linked} albums linked; ${artistJob.review} need review. ${artistJob.truncated} release lists reached the limit or were incomplete.`
    : artistJob.status === "interrupted" ? "Artist lookup was interrupted. Completed artists were kept; start another batch to continue."
    : `${artistJob.error || "Artist lookup failed."}${artistPaused ? ` Try again after ${resumeTime(artistJob.retry_at)}.` : ""}`;
  $("#import-spotify-library").disabled = !playbackAvailable || !selectedPlayer || libraryActionBlocked;
  $("#spotify-library-status").textContent = !library ? "Import your saved albums to find links without searching for each album separately."
    : library.status === "complete" ? `Read ${library.fetched} saved albums. ${library.linked} Last.fm albums linked; ${library.review} need edition review. Existing confirmed links were kept.`
    : library.status === "queued" ? "Saved album import queued."
    : library.status === "running" ? `Reading saved Spotify albums: ${library.fetched} of ${library.total ?? "?"}. Links are matched after all pages are read.`
    : library.status === "interrupted" ? "The saved album import was interrupted. Start it again to read the library from the beginning."
    : `${library.error || "Saved album import failed."}${libraryPaused ? ` You can try again after ${resumeTime(library.retry_at)}.` : ""}`;
  const metadataPaused = data.lastfm_retry_at && data.lastfm_retry_at * 1000 > Date.now();
  $("#metadata-status").textContent = `Last.fm album details checked: ${data.metadata_checked ?? 0} of ${data.albums}. ` +
    `${data.tagged_albums ?? 0} ${data.tagged_albums === 1 ? "album has" : "albums have"} tags; some albums have no tags on Last.fm. ` +
    (!data.metadata_enabled ? "Tag updates are disabled."
      : metadataPaused ? `Updates paused until ${resumeTime(data.lastfm_retry_at)}.`
      : data.metadata_pending ? "Tag update queued."
      : `Up to ${data.lastfm_batch_size} albums per batch, with ${data.lastfm_interval_minutes} ${data.lastfm_interval_minutes === 1 ? "minute" : "minutes"} between batches.`);
  $("#update-tags").disabled = !data.metadata_enabled || data.running || data.pending || data.metadata_pending || metadataPaused;
  const spotifyPaused = data.spotify_retry_at && data.spotify_retry_at * 1000 > Date.now();
  const pauseText = data.spotify_configured && data.spotify_retry_at
    ? spotifyPaused ? `Spotify album lookup is paused until ${resumeTime(data.spotify_retry_at)}. You can still play linked albums.`
      : "Spotify album lookup will resume with the next background update. You can still play linked albums."
    : "";
  $("#enrich").disabled = !data.spotify_configured || !data.enrichment_enabled || data.running || data.pending || data.enrichment_pending || spotifyPaused;
  $("#spotify-status").textContent = !data.spotify_configured
    ? "Add Spotify Client ID and Secret in the app configuration to find album links automatically."
    : `${data.confirmed_albums} linked albums (${data.automatic_albums} matched automatically) · ${data.spotify_candidates} awaiting review. Market: ${data.spotify_market}. ` +
      (!data.enrichment_enabled ? "Spotify link updates are disabled; set enrich_batch_size above zero in app configuration."
        : pauseText ? "Last.fm updates continue in the background."
        : data.enrichment_pending ? "Album updates queued."
        : "Links are checked in small background batches. Use Refresh albums to see new matches.");
  $("#spotify-pause").textContent = pauseText;
  $("#spotify-pause").hidden = !pauseText;
  maintenanceStatus(data, pauseText);
  backgroundErrors();
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
    ? contextNote + `Album details checked: ${data.metadata_checked ?? 0} of ${data.total_albums}. Last.fm tags cover ${data.tagged_albums} albums. Counts describe your library, not the current filters.` +
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
  const source = element("a", "Last.fm", content);
  source.className = "album-source";
  source.href = "https://www.last.fm/music/" + encodeURIComponent(album.artist) + "/" + encodeURIComponent(album.album);
  source.target = "_blank"; source.rel = "noopener noreferrer";
  source.setAttribute("aria-label", `View ${album.album} by ${album.artist} on Last.fm`);
  const confirmed = album.spotify_status === "confirmed" && album.spotify_uri;
  if (confirmed) {
    const link = element("a", "Open confirmed album in Spotify", content);
    link.href = "https://open.spotify.com/album/" + album.spotify_uri.split(":").pop();
    link.target = "_blank"; link.rel = "noopener noreferrer";
    if (album.spotify_match_source === "automatic") element("p", "Automatically linked: unique exact artist and album name match. You can change the edition below.", content);
    if (album.spotify_match_source === "saved_library") element("p", "Linked from your saved Spotify albums: exact artist and album name match. You can change the edition below.", content);
    if (album.spotify_match_source === "artist_catalog") element("p", "Linked from a complete artist release list: exact artist and album name match. You can change the edition below.", content);
  }
  if (playbackAvailable) {
    const playback = element("div", undefined, content); playback.className = "album-playback";
    const play = element("button", "Play this album", playback);
    play.type = "button"; play.className = "play-album";
    play.dataset.confirmed = String(Boolean(confirmed)); play.disabled = !confirmed || !playerReady;
    play.addEventListener("click", async () => {
      play.disabled = true;
      try {
        await api("api/play", {method:"POST", body:JSON.stringify({album_id:album.id, spotify_uri:album.spotify_uri,
          device_id:selectedDevice, expected_device:selectedDevice, expected_entity:selectedPlayer})});
        message("Playback requested."); await loadPlayers();
      } catch (error) { message(error.message, true); }
      finally { play.disabled = !confirmed || !playerReady; }
    });
    const picker = element("details", undefined, playback); picker.className = "playback-device";
    element("summary", "", picker);
    const deviceForm = element("form", undefined, picker); deviceForm.className = "inline";
    const label = element("label", "Playback device", deviceForm);
    const deviceSelect = element("select", undefined, label); deviceSelect.required = true;
    deviceSelect.setAttribute("aria-label", "Playback device");
    deviceSelect.addEventListener("change", () => { deviceSelect.dataset.draft = deviceSelect.value; });
    const use = element("button", "Use for this session", deviceForm); use.type = "submit";
    const refresh = element("button", "Refresh devices", deviceForm); refresh.type = "button";
    refresh.className = "secondary"; refresh.addEventListener("click", loadPlayers);
    const restore = element("button", "Use default", deviceForm); restore.type = "button";
    restore.className = "secondary";
    restore.addEventListener("click", async () => {
      temporaryDevice = null; delete deviceSelect.dataset.draft; picker.open = false;
      resetVolume(); await loadPlayers();
    });
    deviceForm.addEventListener("submit", async event => {
      event.preventDefault();
      if (!availableDevices.includes(deviceSelect.value)) return;
      temporaryDevice = deviceSelect.value; delete deviceSelect.dataset.draft; picker.open = false;
      resetVolume(); await loadPlayers();
    });
    renderDevicePicker(picker);
    if (!confirmed) element("p", "Confirm this album's Spotify link below before playback.", content);
  }
  const editor = element(!editable && confirmed ? "details" : "div", undefined, content);
  if (!editable && confirmed) element("summary", "Check or change Spotify link", editor);
  let candidate = null;
  try { candidate = JSON.parse(album.spotify_candidate); } catch { /* No candidate. */ }
  const choices = candidate?.alternatives || (candidate ? [candidate] : []);
  if (choices.length) {
    const details = element("details", undefined, editor);
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
      : "Spotify lookup pending. You can also paste an album link below.", editor);
  }
  const form = element("form", undefined, editor);
  const label = element("label", "Spotify album link or URI", form);
  const uri = element("input", undefined, label); uri.type = "text"; uri.required = true; uri.maxLength = 2048;
  uri.value = album.spotify_uri || candidate?.uri || ""; uri.placeholder = "https://open.spotify.com/album/…";
  let tags;
  if (editable) {
    const tagLabel = element("label", "Tags, separated by commas", form);
    tags = element("input", undefined, tagLabel); tags.value = album.tags.join(", ");
  }
  const button = element("button", editable ? "Confirm album link and tags" : "Confirm Spotify link", form);
  form.addEventListener("submit", async event => {
    event.preventDefault(); button.disabled = true;
    const generation = recommendationGeneration;
    try {
      const result = await api(`api/albums/${album.id}`, {method:"POST", body:JSON.stringify({
        spotify_uri:uri.value, ...(editable ? {tags:tags.value.split(",").map(t=>t.trim()).filter(Boolean)} : {})
      })});
      if (editable) { clearRecommendation(); await loadAlbums(); }
      else if (article.isConnected && generation === recommendationGeneration) article.replaceWith(albumCard(result.album, false));
      message("Spotify album link confirmed."); await status();
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
  for (const id of ["player-pause", "player-resume", "player-next"]) $(`#${id}`).disabled = !controlReady || controlBusy;
  const volumeReady = controlReady && playerVolume !== null && !volumeState.blocked;
  $("#player-volume").disabled = !volumeReady;
  $("#player-volume-down").disabled = !volumeReady || playerVolume <= 0;
  $("#player-volume-up").disabled = !volumeReady || playerVolume >= 1;
}
function renderDevicePicker(picker) {
  picker.querySelector("summary").textContent = !selectedDevice ? "Choose a playback device"
    : !availableDevices.includes(selectedDevice) ? `${selectedDevice} is unavailable · Change device`
    : `Playback will start on ${selectedDevice}`;
  const select = picker.querySelector("select");
  const draft = select.dataset.draft;
  const desired = draft ?? selectedDevice ?? "";
  // Leave a focused menu alone while background status refreshes.
  if (document.activeElement !== select) {
    select.replaceChildren(); element("option", "Choose a device", select).value = "";
    for (const name of availableDevices) element("option", name, select).value = name;
    if (desired && !availableDevices.includes(desired)) element("option", `${desired} (unavailable)`, select).value = desired;
    select.value = desired;
  }
  for (const button of picker.querySelectorAll('button[type="submit"]')) button.disabled = !selectedPlayer || deviceSaving;
}
function renderVolume() {
  const display = playerVolume === null ? null : volumeConfig.min + playerVolume * (volumeConfig.max - volumeConfig.min);
  $("#volume-value").textContent = display === null ? "—" : display.toFixed(volumeConfig.decimals);
  $("#volume-value").setAttribute("aria-busy", String(!volumeState.blocked && (volumeState.sending || volumeState.target !== null || Boolean(volumeState.awaiting))));
  if (display !== null && document.activeElement !== $("#player-volume")) $("#player-volume").value = display;
  updatePlaybackButtons();
}
function newVolumeState() {
  return {target: null, sending: false, awaiting: null, reported: null, revision: 0,
    timer: null, due: 0, blocked: false};
}
function resetVolume() {
  clearTimeout(volumeState.timer);
  volumeState = newVolumeState();
}
function scheduleVolumeRead(state) {
  clearTimeout(state.timer);
  if (state !== volumeState || state.blocked || state.sending) return;
  if (state.awaiting) {
    // Read HA's cached state without forcing Spotify to refresh.
    state.timer = setTimeout(async () => {
      if (state !== volumeState) return;
      await loadPlayers();
    }, 500);
  } else if (state.target !== null) {
    state.timer = setTimeout(() => sendVolume(state),
      Math.max(0, state.due - performance.now(), volumeNextSendAt - performance.now()));
  }
}
function queueVolume(value) {
  if (!controlReady || volumeState.blocked || playerVolume === null || !Number.isFinite(value)) return;
  const state = volumeState;
  const target = Math.round(Math.max(0, Math.min(1, value)) * 1e8) / 1e8;
  if (target === playerVolume) return;
  state.target = target; state.revision++;
  // Accumulate rapid clicks locally before sending the latest target.
  state.due = performance.now() + 300;
  playerVolume = target; renderVolume();
  scheduleVolumeRead(state);
}
async function sendVolume(state) {
  if (state !== volumeState || state.sending || state.awaiting || state.blocked || state.target === null) return;
  if (performance.now() < Math.max(state.due, volumeNextSendAt)) {
    scheduleVolumeRead(state);
    return;
  }
  // A request from a previous device selection must finish before a new one.
  if (volumeRequestActive) {
    state.timer = setTimeout(() => sendVolume(state), 500);
    return;
  }
  const target = state.target;
  state.target = null;
  state.sending = true; volumeRequestActive = true; renderVolume();
  try {
    await api("api/player/control", {method:"POST", body:JSON.stringify({
      action:"volume", volume:target, expected_entity:selectedPlayer, expected_device:selectedDevice, device_id:selectedDevice
    })});
    if (state !== volumeState) return;
    // HTTP completion does not mean SpotifyPlus's volume has caught up.
    state.awaiting = {target, until:performance.now() + 10000};
    if (controlError && $("#message").textContent === controlError) message("");
    controlError = "";
  } catch (error) {
    if (state !== volumeState) return;
    // A failed write is never retried, including clicks queued behind it.
    state.target = null; state.awaiting = null;
    playerVolume = state.reported;
    controlError = error.message; message(error.message, true);
  } finally {
    volumeRequestActive = false;
    volumeNextSendAt = performance.now() + 1000;
    state.sending = false;
    if (state === volumeState) {
      renderVolume();
      await loadPlayers();
      scheduleVolumeRead(state);
    }
  }
}
async function loadPlayers() {
  if (!playbackAvailable) {
    $("#player-setup").textContent = "Playback is available when this app runs on Home Assistant OS with SpotifyPlus installed.";
    return;
  }
  if (playerLoading) return;
  playerLoading = true;
  const stateAtStart = volumeState;
  const revision = stateAtStart.revision;
  try {
    const data = await api("api/players");
    if (selectedPlayer !== data.selected_entity) { deviceDraft = null; temporaryDevice = null; }
    defaultDevice = data.selected_device || null;
    const effectiveDevice = temporaryDevice || defaultDevice;
    if (selectedPlayer !== data.selected_entity || selectedDevice !== effectiveDevice) resetVolume();
    selectedPlayer = data.selected_entity;
    $("#import-spotify-library").disabled = !selectedPlayer || libraryActionBlocked;
    $("#import-spotify-artists").disabled = !selectedPlayer || artistActionBlocked;
    selectedDevice = effectiveDevice;
    const select = $("#player-select"); select.replaceChildren();
    const placeholder = element("option", "Select a SpotifyPlus player", select); placeholder.value = "";
    for (const player of data.players) { const option = element("option", `${player.name} (${player.entity_id})`, select); option.value = player.entity_id; }
    select.value = playerDraft ?? selectedPlayer ?? "";
    const player = data.players.find(item => item.entity_id === selectedPlayer);
    const devices = player?.devices || [];
    availableDevices = devices;
    const deviceSelect = $("#device-select"); deviceSelect.replaceChildren();
    element("option", "Choose a device", deviceSelect).value = "";
    for (const name of devices) { const option = element("option", name, deviceSelect); option.value = name; }
    if (defaultDevice && !devices.includes(defaultDevice)) element("option", `${defaultDevice} (unavailable)`, deviceSelect).value = defaultDevice;
    deviceSelect.value = deviceDraft ?? defaultDevice ?? "";
    deviceSelect.disabled = !player || deviceSaving;
    $("#save-device").disabled = !player || deviceSaving;
    playerReady = Boolean(player && player.state !== "unavailable" && devices.includes(selectedDevice) && !deviceSaving);
    const wasControlReady = controlReady;
    controlReady = playerReady && player.source === selectedDevice;
    if (wasControlReady && !controlReady) resetVolume();
    $("#device-status").textContent = !player ? "Choose your SpotifyPlus account in Settings first."
      : !defaultDevice ? "Save a default device, or choose a temporary device next to an album's Play button."
      : `Default: ${defaultDevice}.${!devices.includes(defaultDevice) ? " This device is unavailable." : ""}${temporaryDevice ? ` This session uses ${temporaryDevice}.` : ""}`;
    for (const picker of document.querySelectorAll(".playback-device")) renderDevicePicker(picker);
    const reported = controlReady && Number.isFinite(player?.volume_level) && player.volume_level >= 0 && player.volume_level <= 1 ? player.volume_level : null;
    const state = volumeState;
    state.reported = reported;
    const currentRead = state !== stateAtStart || revision === state.revision;
    if (currentRead && !state.sending) {
      if (state.awaiting) {
        // Match the integer percentage actually sent to SpotifyPlus.
        const acknowledged = reported !== null &&
          Math.round(reported * 100) === Math.round(state.awaiting.target * 100);
        if (acknowledged) {
          state.awaiting = null;
          if (state.blocked) {
            state.blocked = false;
            if ($("#message").textContent === controlError) message("");
            controlError = "";
          }
        } else if (!state.blocked && performance.now() >= state.awaiting.until) {
          state.blocked = true; state.target = null;
          controlError = "SpotifyPlus has not confirmed the volume change. Volume controls are paused until it catches up. Check the player in Home Assistant.";
          message(controlError, true);
        }
      }
      if (state.blocked || (!state.awaiting && state.target === null)) playerVolume = reported;
    }
    $("#player-setup").textContent = !data.players.length
      ? "No SpotifyPlus players found. Install and configure SpotifyPlus in Home Assistant, then refresh players."
      : player ? `Saved player: ${player.name}.` : "Select and save your SpotifyPlus player to enable playback.";
    $("#player-state").textContent = player
      ? `${player.title || "No track playing"}${player.artist ? " — " + player.artist : ""} · ${player.source || player.name} · ${player.state}`
      : "Choose your SpotifyPlus player in Settings to enable playback.";
  } catch (error) { playerReady = false; controlReady = false; resetVolume(); playerVolume = null; message(error.message, true); }
  finally { playerLoading = false; renderVolume(); scheduleVolumeRead(volumeState); }
}
$("#player-select").addEventListener("change", event => { playerDraft = event.target.value; });
$("#player-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    resetVolume();
    await api("api/player", {method:"POST", body:JSON.stringify({entity_id:$("#player-select").value})});
    playerDraft = null; message("SpotifyPlus player saved."); await loadPlayers();
  } catch (error) { message(error.message, true); }
});
$("#refresh-players").addEventListener("click", loadPlayers);
$("#import-spotify-library").addEventListener("click", async () => {
  $("#import-spotify-library").disabled = true;
  try { await api("api/spotify-library", {method:"POST", body:"{}"}); message("Saved Spotify album import queued."); await status(); }
  catch (error) { message(error.message, true); await status(); }
});
$("#import-spotify-artists").addEventListener("click", async () => {
  $("#import-spotify-artists").disabled = true;
  try { await api("api/spotify-artists", {method:"POST", body:"{}"}); message("Artist lookup queued."); await status(); }
  catch (error) { message(error.message, true); await status(); }
});
$("#refresh-devices").addEventListener("click", loadPlayers);
$("#device-select").addEventListener("change", event => { deviceDraft = event.target.value; });
$("#device-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (deviceSaving) return;
  deviceSaving = true; playerReady = false; controlReady = false; resetVolume(); renderVolume();
  $("#save-device").disabled = true; $("#device-select").disabled = true;
  try {
    await api("api/player/device", {method:"POST", body:JSON.stringify({device_id:deviceDraft ?? defaultDevice, expected_entity:selectedPlayer})});
    deviceDraft = null; temporaryDevice = null; message("Default playback device saved.");
  } catch (error) { message(error.message, true); }
  finally { deviceSaving = false; await loadPlayers(); }
});
for (const action of ["pause", "resume", "next"]) {
  $(`#player-${action}`).addEventListener("click", () => control(action));
}
$("#player-volume").addEventListener("change", event => queueVolume(
  (Number(event.target.value) - volumeConfig.min) / (volumeConfig.max - volumeConfig.min)));
$("#player-volume-up").addEventListener("click", () => queueVolume(playerVolume + volumeConfig.step / (volumeConfig.max - volumeConfig.min)));
$("#player-volume-down").addEventListener("click", () => queueVolume(playerVolume - volumeConfig.step / (volumeConfig.max - volumeConfig.min)));
async function control(action, volume) {
  if (controlBusy) return;
  controlBusy = true; updatePlaybackButtons();
  try {
    await api("api/player/control", {method:"POST", body:JSON.stringify({action, volume, expected_entity:selectedPlayer, expected_device:selectedDevice, device_id:selectedDevice})});
    await loadPlayers();
    if (controlError && $("#message").textContent === controlError) message("");
    controlError = "";
  }
  catch (error) { controlError = error.message; message(error.message, true); }
  finally { controlBusy = false; updatePlaybackButtons(); }
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
  resetVolume();
  refreshErrors.clear();
  $("#background-status").textContent = ""; $("#background-status").hidden = true;
  $("#background-details-text").textContent = ""; $("#background-details").hidden = true;
  $("#spotify-pause").textContent = ""; $("#spotify-pause").hidden = true;
  token = ""; sessionStorage.removeItem("lastfm-token"); $("#token").value = "";
  $("#albums").replaceChildren(); clearRecommendation();
  $("#genres").replaceChildren(); $("#genre-status").textContent = "";
  $("#status").textContent = "Disconnected."; message("Token removed from this tab.");
  $("#player-state").textContent = "Disconnected."; $("#player-setup").textContent = "Connect to choose a player.";
  $("#player-select").replaceChildren(); selectedPlayer = null; playerDraft = null;
  playerReady = false; controlReady = false; selectedDevice = null; defaultDevice = null; temporaryDevice = null; availableDevices = []; deviceDraft = null;
  libraryActionBlocked = true; $("#import-spotify-library").disabled = true; $("#spotify-library-status").textContent = "Connect to import saved albums.";
  artistActionBlocked = true; $("#import-spotify-artists").disabled = true; $("#spotify-artist-status").textContent = "Connect to look up artists.";
  $("#device-select").replaceChildren(); $("#device-status").textContent = "Connect to choose a device.";
  playerVolume = null; $("#volume-value").textContent = "—"; updatePlaybackButtons();
});
$("#sync").addEventListener("click", async () => {
  try { await api("api/sync", {method:"POST", body:"{}"}); message("Sync queued."); await status(); }
  catch (error) { message(error.message, true); }
});
$("#enrich").addEventListener("click", async () => {
  try { await api("api/enrich", {method:"POST", body:"{}"}); message("Album updates queued. The remaining library continues in scheduled batches."); await status(); }
  catch (error) { message(error.message, true); }
});
$("#update-tags").addEventListener("click", async () => {
  try { await api("api/metadata", {method:"POST", body:"{}"}); message("Last.fm tag update queued."); await status(); }
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
  const session = await requestJson("api/session"); ingress = session.ingress; playbackAvailable = session.home_assistant_available;
  volumeConfig = session.volume || volumeConfig;
  $("#player-volume").min = volumeConfig.min; $("#player-volume").max = volumeConfig.max; $("#player-volume").step = volumeConfig.step;
  $("#player-volume-up").setAttribute("aria-label", `Increase volume by ${volumeConfig.step.toFixed(volumeConfig.decimals)}`);
  $("#player-volume-down").setAttribute("aria-label", `Decrease volume by ${volumeConfig.step.toFixed(volumeConfig.decimals)}`);
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
