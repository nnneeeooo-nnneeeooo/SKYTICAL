/* Planespotters metadata is cached in memory; images load directly from the
 * unchanged provider URL. Never substitute a photo from a different airframe. */
(function (root) {
  "use strict";
  const cache = new Map();
  const pending = new Map();
  function safeUrl(value, hosts, prefix) {
    if (typeof value !== "string") return false;
    try {
      const url = new URL(value);
      return url.protocol === "https:" && !url.username && !url.password &&
        !url.port && hosts.includes(url.hostname) && url.pathname.startsWith(prefix);
    } catch (_) { return false; }
  }
  function normalize(payload) {
    const photo = payload && Array.isArray(payload.photos) && payload.photos[0];
    if (!photo) return null;
    const src = (photo.thumbnail_large || photo.thumbnail || {}).src;
    if (!safeUrl(src, ["t.plnspttrs.net", "cdn.planespotters.net"], "/") ||
        !safeUrl(photo.link, ["www.planespotters.net"], "/photo/") ||
        typeof photo.photographer !== "string" || !photo.photographer.trim()) return null;
    return { src, link: photo.link, photographer: photo.photographer };
  }
  async function fetchPhoto(hex) {
    const key = String(hex || "").toLowerCase();
    if (!/^[a-f0-9]{6}$/.test(key)) return null;
    const cached = cache.get(key);
    if (cached && cached.expires > Date.now()) return cached.photo;
    if (pending.has(key)) return pending.get(key);
    const request = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(`https://api.planespotters.net/pub/photos/hex/${key}`, {
          mode: "cors", credentials: "omit", signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Photo HTTP ${response.status}`);
        const payload = await response.json();
        if (!payload || !Array.isArray(payload.photos)) throw new Error("Invalid photo response");
        const photo = normalize(payload);
        if (cache.size >= 100) cache.delete(cache.keys().next().value);
        cache.set(key, { photo, expires: Date.now() + (photo ? 3600000 : 900000) });
        return photo;
      } finally { clearTimeout(timeout); }
    })();
    pending.set(key, request);
    try { return await request; } finally { pending.delete(key); }
  }
  async function render(container, hex, label, copy, onLayout = () => {}) {
    if (container.dataset.requested) return;
    container.dataset.requested = "true";
    container.setAttribute("aria-busy", "true");
    container.textContent = copy.photoLoading;
    try {
      const photo = await fetchPhoto(hex);
      if (!photo) { container.textContent = copy.photoMissing; return; }
      const link = document.createElement("a");
      link.href = photo.link;
      link.target = "_blank";
      link.rel = "noopener";
      link.setAttribute("aria-label", `${copy.photoOriginal} · ${photo.photographer}`);
      const img = document.createElement("img");
      img.alt = `${label} · ${copy.photoAircraft}`;
      img.decoding = "async";
      img.addEventListener("error", () => {
        cache.delete(String(hex).toLowerCase());
        container.textContent = copy.photoError;
        onLayout();
      }, { once: true });
      img.addEventListener("load", () => {
        container.setAttribute("aria-busy", "false");
        onLayout();
      }, { once: true });
      img.src = photo.src;
      link.appendChild(img);
      const credit = document.createElement("span");
      credit.className = "radar-photo-credit";
      credit.textContent = `© ${photo.photographer} / Planespotters.net`;
      container.replaceChildren(link, credit);
    } catch (_) { container.textContent = copy.photoError; }
    finally {
      container.setAttribute("aria-busy", "false");
      onLayout();
    }
  }
  const api = { normalize, fetchPhoto, render };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SkyticalPhotos = api;
})(typeof window === "undefined" ? this : window);
