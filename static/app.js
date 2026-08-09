/* AVWIRE client behavior: clocks, theme toggle, client-side filters.
   Language switching is pure links — nothing to do here. */
(function () {
  "use strict";

  /* — UTC + TPE clocks, updated every 10 s (per the design) — */
  var utcEl = document.getElementById("clock-utc");
  var tpeEl = document.getElementById("clock-tpe");
  function clock12(date, timeZone) {
    return date.toLocaleTimeString("en-US", {
      timeZone: timeZone,
      hour: "numeric",
      minute: "2-digit",
      hour12: true
    });
  }
  function tick() {
    var now = new Date();
    if (utcEl) utcEl.textContent = "UTC " + clock12(now, "UTC");
    if (tpeEl) {
      tpeEl.textContent = "TPE " + clock12(now, "Asia/Taipei");
    }
  }
  tick();
  setInterval(tick, 10000);

  /* — theme seg: data-theme on <html> + localStorage persistence — */
  var themeBtns = Array.prototype.slice.call(document.querySelectorAll("[data-set-theme]"));
  function reflectTheme() {
    var cur = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    themeBtns.forEach(function (b) {
      b.classList.toggle("active", b.dataset.setTheme === cur);
    });
  }
  themeBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      document.documentElement.dataset.theme = b.dataset.setTheme;
      try { localStorage.setItem("avwire-theme", b.dataset.setTheme); } catch (e) { /* private mode */ }
      reflectTheme();
    });
  });
  reflectTheme();

  /* — global header search: operate the Google-style clear key — */
  var headerSearchInput = document.getElementById("news-search-input");
  var headerSearchClear = document.getElementById("news-search-clear");
  if (headerSearchInput && headerSearchClear) {
    headerSearchClear.addEventListener("click", function () {
      headerSearchInput.value = "";
      headerSearchInput.dispatchEvent(new Event("input", { bubbles: true }));
      headerSearchInput.focus();
    });
  }

  /* — mobile navigation: compact by default, keyboard and screen-reader safe — */
  var navToggle = document.querySelector("[data-nav-toggle]");
  var siteNav = document.getElementById("site-nav");
  function setNavOpen(open) {
    if (!navToggle || !siteNav) return;
    siteNav.classList.toggle("is-open", open);
    navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    navToggle.querySelector(".nav-toggle-icon").textContent = open ? "×" : "☰";
  }
  if (navToggle && siteNav) {
    navToggle.addEventListener("click", function () {
      setNavOpen(navToggle.getAttribute("aria-expanded") !== "true");
    });
    siteNav.addEventListener("click", function (event) {
      if (event.target.closest("a")) setNavOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setNavOpen(false);
    });
    var desktopNav = window.matchMedia("(min-width: 721px)");
    desktopNav.addEventListener("change", function (event) {
      if (event.matches) setNavOpen(false);
    });
  }

  /* — home: category filter over feed rows ([data-cat]) — */
  var catBtns = Array.prototype.slice.call(document.querySelectorAll("[data-filter-cat]"));
  catBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      var v = b.dataset.filterCat;
      catBtns.forEach(function (x) { x.classList.toggle("active", x === b); });
      Array.prototype.forEach.call(document.querySelectorAll("[data-cat]"), function (row) {
        row.classList.toggle("is-hidden", v !== "all" && row.dataset.cat !== v);
      });
    });
  });

  /* — incidents: severity filter over rows ([data-sev]) + live record count — */
  var sevBtns = Array.prototype.slice.call(document.querySelectorAll("[data-filter-sev]"));
  var countEl = document.getElementById("inc-count");
  sevBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      var v = b.dataset.filterSev;
      var n = 0;
      sevBtns.forEach(function (x) { x.classList.toggle("active", x === b); });
      Array.prototype.forEach.call(document.querySelectorAll("[data-sev]"), function (row) {
        var hide = v !== "all" && row.dataset.sev !== v;
        row.classList.toggle("is-hidden", hide);
        if (!hide) n += 1;
      });
      if (countEl) countEl.textContent = String(n);
    });
  });
})();
