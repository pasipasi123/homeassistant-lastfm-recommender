"use strict";
// Apply the saved palette before styles load, including inside HA Ingress.
(() => {
  const key = "lastfm-theme";
  const themes = new Set(["light", "dark", "colorful"]);
  function apply(value, save = true) {
    const theme = themes.has(value) ? value : "light";
    document.documentElement.dataset.theme = theme;
    for (const input of document.querySelectorAll('input[name="theme"]')) input.checked = input.value === theme;
    if (save) {
      try { localStorage.setItem(key, theme); } catch { /* Appearance still works when storage is blocked. */ }
    }
  }
  let saved;
  try { saved = localStorage.getItem(key); } catch { /* Use the default palette. */ }
  apply(saved, false);
  window.musicTheme = Object.freeze({apply});
  window.addEventListener("storage", event => {
    if (event.key === key || event.key === null) apply(event.newValue, false);
  });
})();
