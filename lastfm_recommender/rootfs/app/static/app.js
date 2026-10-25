"use strict";
const $ = (selector) => document.querySelector(selector);
let token = sessionStorage.getItem("lastfm-token") || "";
$("#token").value = token;

function message(text, error = false) {
  $("#message").textContent = text;
  $("#message").className = error ? "error" : "";
}
async function api(path, options = {}) {
  if (!token) throw new Error("Enter the app's API token first.");
  const response = await fetch(path, {...options, headers: {
    Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...options.headers
  }});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || (response.status === 409
    ? "A sync is already running or queued." : `HTTP ${response.status}`));
  return data;
}
function date(timestamp) {
  return timestamp ? new Date(timestamp * 1000).toLocaleString("en-GB") : "not yet";
}
async function status() {
  const data = await api("/api/status");
  const progress = data.import ? ` Import page ${data.import.page}/${data.import.total_pages || "?"}.` : "";
  $("#status").textContent = `${data.scrobbles.toLocaleString("en-GB")} scrobbles · ${data.albums} albums · ` +
    `${data.confirmed_albums} confirmed Spotify links. Last successful sync: ${date(data.last_sync_at)}. ` +
    `${data.running ? "Sync in progress." : data.pending ? "Sync queued." : "Waiting for the next sync."}${progress}`;
  $("#sync").disabled = data.running || data.pending;
  if (data.last_error || data.enrichment_error) message(data.last_error || data.enrichment_error, true);
}
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
function albumCard(album) {
  const article = element("article"); article.className = "album";
  const image = safeImage(album.image_url);
  if (image) {
    const img = element("img", undefined, article); img.src = image; img.alt = ""; img.loading = "lazy";
  } else {
    const cover = element("div", "♫", article); cover.className = "cover-placeholder";
    cover.setAttribute("aria-hidden", "true");
  }
  const content = element("div", undefined, article);
  element("h3", album.album, content);
  element("p", `${album.artist} · ${album.scrobbles_total} scrobbles · last played ${date(album.last_listened_at)}`, content);
  element("p", album.tags.length ? album.tags.join(", ") : "No tags yet", content);
  let candidate = null;
  try { candidate = JSON.parse(album.spotify_candidate); } catch { /* No candidate. */ }
  if (candidate) element("p", `Spotify suggestion (unverified): ${candidate.artists.join(", ")} – ${candidate.name}`, content);
  if (album.spotify_status === "confirmed" && album.spotify_uri) {
    const link = element("a", "Open confirmed album in Spotify", content);
    link.href = "https://open.spotify.com/album/" + album.spotify_uri.split(":").pop();
    link.target = "_blank"; link.rel = "noopener noreferrer";
  }
  const form = element("form", undefined, content);
  const label = element("label", "Spotify album link or URI", form);
  const uri = element("input", undefined, label);
  uri.type = "text"; uri.required = true; uri.maxLength = 2048;
  uri.value = album.spotify_uri || candidate?.uri || "";
  uri.placeholder = "https://open.spotify.com/album/…";
  const tagLabel = element("label", "Tags, separated by commas", form);
  const tags = element("input", undefined, tagLabel); tags.value = album.tags.join(", ");
  const button = element("button", "Confirm album link and tags", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); button.disabled = true;
    try {
      await api(`/api/albums/${album.id}`, {method: "POST", body: JSON.stringify({
        spotify_uri: uri.value, tags: tags.value.split(",").map(t => t.trim()).filter(Boolean)
      })});
      message("Spotify album link confirmed.");
      await loadAlbums(); await status();
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });
  return article;
}
async function loadAlbums() {
  const data = await api("/api/albums?limit=30&q=" + encodeURIComponent($("#query").value));
  $("#albums").replaceChildren(...data.albums.map(albumCard));
  if (!data.albums.length) element("p", "No albums found. Wait for the import or try another search.", $("#albums"));
}
$("#auth").addEventListener("submit", async (event) => {
  event.preventDefault(); token = $("#token").value;
  try {
    await status(); sessionStorage.setItem("lastfm-token", token);
    message("Connected."); await loadAlbums();
  } catch (error) { message(error.message, true); }
});
$("#logout").addEventListener("click", () => {
  token = ""; sessionStorage.removeItem("lastfm-token"); $("#token").value = "";
  $("#albums").replaceChildren(); $("#recommendation").replaceChildren();
  $("#status").textContent = "Disconnected."; message("Token removed from this tab.");
});
$("#sync").addEventListener("click", async () => {
  try { await api("/api/sync", {method:"POST", body:"{}"}); message("Sync queued."); await status(); }
  catch (error) { message(error.message, true); }
});
$("#search").addEventListener("submit", async event => {
  event.preventDefault(); try { await loadAlbums(); } catch (error) { message(error.message, true); }
});
$("#recommend").addEventListener("submit", async event => {
  event.preventDefault(); const form = new FormData(event.target);
  form.set("playable_only", form.has("playable_only") ? "true" : "false");
  try {
    const data = await api("/api/recommend?" + new URLSearchParams(form));
    $("#recommendation").replaceChildren();
    if (data.album) $("#recommendation").append(albumCard(data.album));
    else element("p", "No matching albums. Adjust the filters or include albums without confirmed links.", $("#recommendation"));
  } catch (error) { message(error.message, true); }
});
$("#backup").addEventListener("click", async () => {
  try {
    if (!token) throw new Error("Connect first.");
    const response = await fetch("/api/backup", {headers: {Authorization: `Bearer ${token}`}});
    if (!response.ok) throw new Error(`Backup failed: HTTP ${response.status}`);
    const url = URL.createObjectURL(await response.blob());
    const a = element("a"); a.href = url; a.download = "scrobbles.db"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); message("Backup downloaded.");
  } catch (error) { message(error.message, true); }
});
if (token) { status().then(loadAlbums).catch(error => message(error.message, true)); }
setInterval(() => { if (token) status().catch(error => message(error.message, true)); }, 15000);
