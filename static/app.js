/* SKYTICAL client behavior: clocks, theme toggle, client-side filters.
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
    headerSearchForm.addEventListener("submit", function (event) {
      if (headerSearchInput.value.trim()) return;
      var suggestedQuery = queryFromSearchPlaceholder(
        headerSearchInput.placeholder
      );
      if (!suggestedQuery) return;
      headerSearchInput.value = suggestedQuery;
      headerSearchInput.dispatchEvent(new Event("input", { bubbles: true }));
      if (document.getElementById("news-search-app")) return;

      /* Build the navigation URL explicitly.  Some browsers snapshot the
         form controls before this submit handler fills the suggestion, which
         otherwise opens the search page without q. */
      event.preventDefault();
      var searchUrl = new URL(headerSearchForm.action, window.location.href);
      searchUrl.searchParams.set(headerSearchInput.name || "q", suggestedQuery);
      window.location.assign(searchUrl.toString());
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
    var desktopNav = window.matchMedia("(min-width: 1101px)");
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
  /* — Taiwan-focus hero carousel: timed, controllable and pauseable — */
  var heroCandidatesNode = document.getElementById("hero-candidates");
  var heroLink = document.getElementById("hero-story-link");
  if (heroCandidatesNode && heroLink) {
    var heroCandidates = [];
    try {
      heroCandidates = JSON.parse(heroCandidatesNode.textContent || "[]");
    } catch (e) {
      heroCandidates = [];
    }
    var heroImage = document.getElementById("hero-story-image");
    var heroImageCaption = document.getElementById("hero-image-caption");
    var heroKicker = document.getElementById("hero-story-kicker");
    var heroTitle = document.getElementById("hero-story-title");
    var heroSummary = document.querySelector(
      ".summary-preview--hero .summary-preview__text"
    );
    var heroTime = document.getElementById("hero-story-time");
    var heroSource = document.getElementById("hero-story-source");
    var heroCarousel = document.getElementById("hero-carousel");
    var heroPrev = document.getElementById("hero-prev");
    var heroNext = document.getElementById("hero-next");
    var heroDots = Array.prototype.slice.call(
      document.querySelectorAll("[data-hero-index]")
    );
    var heroIndex = 0;
    var heroTimer = null;
    var heroPaused = false;
    var heroChanging = false;
    var reduceHeroMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var heroTransitionMs = reduceHeroMotion ? 0 : 220;
    var heroRotationMs = Number(heroCarousel && heroCarousel.dataset.rotationMs) || 8000;

    function renderPriorityHero(story) {
      if (!story || !heroImage) return;
      heroLink.href = story.url || "#";
      heroLink.setAttribute("aria-label", story.title || "SKYTICAL");
      if (story.external) {
        heroLink.target = "_blank";
        heroLink.rel = "noopener";
      } else {
        heroLink.removeAttribute("target");
        heroLink.removeAttribute("rel");
      }
      var image = story.image && story.image.url ? story.image : null;
      if (image) {
        heroImage.src = image.url;
        heroImage.alt = story.image_alt || "";
        heroImage.removeAttribute("data-image-fallback");
      } else {
        heroImage.src = heroImage.dataset.fallbackSrc;
        heroImage.alt = story.image_alt || "SKYTICAL";
        heroImage.setAttribute("data-image-fallback", "true");
      }
      if (heroImageCaption) {
        heroImageCaption.textContent = story.image_caption || "";
      }
      if (heroKicker) heroKicker.textContent = story.kicker || "";
      if (heroTitle) heroTitle.textContent = story.title || "";
      if (heroSummary) heroSummary.textContent = story.summary || "";
      if (heroTime) heroTime.textContent = story.time || "";
      if (heroSource) heroSource.textContent = story.source_meta || "";
    }

    function reflectHeroDots() {
      heroDots.forEach(function (dot, index) {
        var active = index === heroIndex;
        dot.classList.toggle("active", active);
        if (active) dot.setAttribute("aria-current", "true");
        else dot.removeAttribute("aria-current");
      });
    }

    function stopHeroTimer() {
      if (heroTimer !== null) window.clearTimeout(heroTimer);
      heroTimer = null;
    }

    function scheduleHeroRotation() {
      stopHeroTimer();
      if (heroPaused || document.hidden || heroCandidates.length < 2) return;
      heroTimer = window.setTimeout(function () {
        showHero((heroIndex + 1) % heroCandidates.length, "next");
      }, heroRotationMs);
    }

    function showHero(nextIndex, direction) {
      if (heroChanging || !heroCandidates.length) return;
      nextIndex = (nextIndex + heroCandidates.length) % heroCandidates.length;
      stopHeroTimer();
      if (nextIndex === heroIndex) {
        scheduleHeroRotation();
        return;
      }
      heroChanging = true;
      heroLink.classList.add(direction === "previous" ?
        "hero-exit-right" : "hero-exit-left");
      window.setTimeout(function () {
        heroIndex = nextIndex;
        renderPriorityHero(heroCandidates[heroIndex]);
        heroLink.classList.remove("hero-exit-left", "hero-exit-right");
        heroLink.classList.add(direction === "previous" ?
          "hero-enter-left" : "hero-enter-right");
        reflectHeroDots();
        window.requestAnimationFrame(function () {
          window.requestAnimationFrame(function () {
            heroLink.classList.remove("hero-enter-left", "hero-enter-right");
            heroChanging = false;
            scheduleHeroRotation();
          });
        });
      }, heroTransitionMs);
    }

    if (heroCandidates.length) {
      renderPriorityHero(heroCandidates[heroIndex]);
      if (heroCandidates.length > 1) {
        if (heroPrev) heroPrev.addEventListener("click", function () {
          showHero(heroIndex - 1, "previous");
        });
        if (heroNext) heroNext.addEventListener("click", function () {
          showHero(heroIndex + 1, "next");
        });
        heroDots.forEach(function (dot) {
          dot.addEventListener("click", function () {
            var nextIndex = Number(dot.dataset.heroIndex);
            showHero(nextIndex, nextIndex < heroIndex ? "previous" : "next");
          });
        });
        if (heroCarousel) {
          heroCarousel.addEventListener("mouseenter", function () {
            heroPaused = true;
            stopHeroTimer();
          });
          heroCarousel.addEventListener("mouseleave", function () {
            heroPaused = false;
            scheduleHeroRotation();
          });
          heroCarousel.addEventListener("focusin", function () {
            heroPaused = true;
            stopHeroTimer();
          });
          heroCarousel.addEventListener("focusout", function () {
            window.setTimeout(function () {
              if (!heroCarousel.contains(document.activeElement)) {
                heroPaused = false;
                scheduleHeroRotation();
              }
            }, 0);
          });
        }
        document.addEventListener("visibilitychange", scheduleHeroRotation);
        reflectHeroDots();
        scheduleHeroRotation();
      }
    }
  }

})();
