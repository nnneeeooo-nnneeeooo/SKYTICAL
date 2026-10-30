(() => {
  "use strict";
  const base = document.currentScript.dataset.base || "";
  const state = document.getElementById("entry-state");
  let revision = 0;
  async function activate() {
    const key = location.hash.slice(1);
    if (!key) return;
    const request = ++revision;
    history.replaceState(null, "", location.pathname);
    state.textContent = "正在驗證私人連結並啟用管理模式…";
    try {
      const value = decodeURIComponent(key).trim();
      if (value.length < 32) throw new Error("ADMIN_KEY 至少需要 32 個字元。");
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
      const slug = [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, "0")).join("");
      const route = `${base}/admin/${slug}/`;
      const response = await fetch(route, {cache:"no-store",referrerPolicy:"no-referrer"});
      if (request !== revision) return;
      if (!response.ok) throw new Error("找不到對應的管理入口，請確認金鑰與 GitHub Secret ADMIN_KEY 相同，且已完成部署。");
      const source = new DOMParser().parseFromString(await response.text(), "text/html");
      if (request !== revision) return;
      if (source.body.dataset.skyticalAdmin !== "true") throw new Error("管理入口內容不完整，請稍後重新開啟私人連結。");
      try {sessionStorage.removeItem("skytical-admin-route-v1-disabled");sessionStorage.setItem("skytical-admin-route-v1", route);}
      catch (_) {throw new Error("瀏覽器禁止儲存管理模式，請允許網站儲存後重新開啟私人連結。");}
      location.replace(`${base}/`);
    } catch (error) {
      if (request !== revision) return;
      state.textContent = error instanceof TypeError
        ? "無法連線至管理入口，請確認網路後重新開啟私人連結。"
        : error.message;
    }
  }
  window.addEventListener("hashchange", activate);
  return activate();
})();
