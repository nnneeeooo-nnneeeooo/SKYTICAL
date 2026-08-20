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

  /* — global header search: random suggestion, submit fallback and clear — */
  var headerSearchForm = document.getElementById("news-search-form");
  var headerSearchInput = document.getElementById("news-search-input");
  var headerSearchClear = document.getElementById("news-search-clear");
  function queryFromSearchPlaceholder(value) {
    return String(value || "")
      .replace(
        /^(?:搜尋|查詢|尋找|看看|想看|探索|了解|Search|Explore|Find|Look\s+up|Show\s+me)\s*[：:]?\s*/i,
        ""
      )
      .trim();
  }
  if (headerSearchInput) {
    try {
      var searchPlaceholders = JSON.parse(
        headerSearchInput.getAttribute("data-search-placeholders") || "[]"
      );
      if (Array.isArray(searchPlaceholders) && searchPlaceholders.length) {
        var randomPlaceholder = Math.floor(Math.random() * searchPlaceholders.length);
        headerSearchInput.placeholder = searchPlaceholders[randomPlaceholder];
      }
    } catch (e) { /* keep the server-rendered fallback */ }
  }
  if (headerSearchForm && headerSearchInput) {
    headerSearchForm.addEventListener("submit", function () {
      if (headerSearchInput.value.trim()) return;
      var suggestedQuery = queryFromSearchPlaceholder(
        headerSearchInput.placeholder
      );
      if (!suggestedQuery) return;
      headerSearchInput.value = suggestedQuery;
      headerSearchInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
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

  /* — LIVE ticker: keep a readable speed even as headline length changes — */
  var marqueeTrack = document.querySelector(".marquee-track");
  function setMarqueeDuration() {
    if (!marqueeTrack) return;
    var tickerPass = marqueeTrack.querySelector(".ticker-pass");
    if (!tickerPass) return;
    var pixelsPerSecond = window.matchMedia("(max-width: 720px)").matches ? 32 : 52;
    var seconds = Math.max(20, tickerPass.scrollWidth / pixelsPerSecond);
    marqueeTrack.style.setProperty("--ticker-duration", seconds.toFixed(1) + "s");
  }
  if (marqueeTrack) {
    setMarqueeDuration();
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(setMarqueeDuration);
    }
    window.addEventListener("resize", setMarqueeDuration);
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
  function applyIncidentFilter(v, button, updateUrl) {
    var n = 0;
    sevBtns.forEach(function (x) { x.classList.toggle("active", x === button); });
    Array.prototype.forEach.call(document.querySelectorAll("[data-sev]"), function (row) {
      var matches = v === "all" ||
        (v === "week" ? row.dataset.weeklySerious === "true" : row.dataset.sev === v);
      row.classList.toggle("is-hidden", !matches);
      if (matches) n += 1;
    });
    if (countEl) countEl.textContent = String(n);
    if (updateUrl && window.history && window.history.replaceState) {
      var url = new URL(window.location.href);
      if (v === "all") url.searchParams.delete("filter");
      else url.searchParams.set("filter", v);
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  }
  sevBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      applyIncidentFilter(b.dataset.filterSev, b, true);
    });
  });
  if (sevBtns.length) {
    var requestedFilter = new URLSearchParams(window.location.search).get("filter") || "all";
    var initialButton = sevBtns.find(function (b) {
      return b.dataset.filterSev === requestedFilter;
    }) || sevBtns.find(function (b) { return b.dataset.filterSev === "all"; });
    applyIncidentFilter(initialButton.dataset.filterSev, initialButton, false);
  }
})();
