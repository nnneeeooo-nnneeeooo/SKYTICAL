(async () => {
  "use strict";
  const key = location.hash.slice(1);
  history.replaceState(null, "", location.pathname);
  if (!key) return;
  const state = document.getElementById("entry-state");
  try {
    const value = decodeURIComponent(key).trim();
    if (value.length < 32) throw new Error("ADMIN_KEY 至少需要 32 個字元。");
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
    const slug = [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, "0")).join("");
    location.replace(`${location.pathname.replace(/index\.html$/, "").replace(/\/$/, "")}/${slug}/`);
  } catch (error) { state.textContent = error.message; }
})();
