/* AVWIRE client behavior: clocks, theme toggle, client-side filters.
   Language switching is pure links — nothing to do here. */
(function () {
  "use strict";

  /* — UTC + TPE clocks, updated every 10 s (per the design) — */
  var utcEl = document.getElementById("clock-utc");
  var tpeEl = document.getElementById("clock-tpe");
  function tick() {
    var now = new Date();
    if (utcEl) utcEl.textContent = "UTC " + now.toISOString().slice(11, 16);
    if (tpeEl) {
      tpeEl.textContent = "TPE " + now.toLocaleTimeString("en-GB", {
        timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit"
      });
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
