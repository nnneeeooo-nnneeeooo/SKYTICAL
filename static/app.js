/* SKYTICAL client behavior: clocks, theme toggle, client-side filters.
   Language switching is pure links — nothing to do here. */
(function () {
  "use strict";

  document.querySelectorAll(".news-thumbnail img[data-fallback]").forEach(function (image) {
    function useFallback() {
      if (image.dataset.fallbackTried === "true") return;
      image.dataset.fallbackTried = "true";
      image.alt = "SKYTICAL";
      var row = image.closest(".feed-row");
      var credit = row && row.querySelector(".news-image-credit");
      if (credit) credit.hidden = true;
      image.src = image.dataset.fallback;
    }
    image.addEventListener("error", useFallback);
    if (image.complete && image.naturalWidth === 0) useFallback();
  });

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
  var themeKey = "avwire-theme";
  var unlockKey = "skytical-8bit-unlocked";
  var pixelUnlocked = document.documentElement.dataset.pixelUnlocked === "true";
  var themeBtns = Array.prototype.slice.call(document.querySelectorAll("[data-set-theme]"));
  var unlockBtn = document.querySelector("[data-unlock-8bit]");
  var pixelDialog = document.querySelector(".pixel-dialog");
  var pixelRefresh = document.querySelector("[data-pixel-refresh]");
  var pixelClose = document.querySelector("[data-pixel-close]");
  var favicon = document.querySelector('link[rel="icon"]');
  var themeColor = document.querySelector('meta[name="theme-color"]');
  var classicFavicon = favicon ? favicon.getAttribute("href") : "";
  var isZh = document.documentElement.lang.indexOf("zh") === 0;
  function reflectTheme() {
    var cur = document.documentElement.dataset.theme || "light";
    themeBtns.forEach(function (b) {
      var selected = b.dataset.setTheme === cur;
      b.classList.toggle("active", selected);
      b.setAttribute("aria-pressed", String(selected));
      if (b.dataset.setTheme === "8bit") b.hidden = !pixelUnlocked;
    });
    if (favicon) favicon.setAttribute("href", cur === "8bit" ? favicon.dataset.pixelHref : classicFavicon);
    if (themeColor) themeColor.setAttribute("content", cur === "8bit" ? "#122039" : cur === "dark" ? "#171514" : "#f3f2f2");
  }
  function setTheme(theme, persist) {
    if (["light", "dark", "8bit"].indexOf(theme) < 0 || (theme === "8bit" && !pixelUnlocked)) theme = "light";
    document.documentElement.dataset.theme = theme;
    if (persist) {
      try { localStorage.setItem(themeKey, theme); } catch (e) { /* unavailable storage */ }
    }
    reflectTheme();
  }
  themeBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      setTheme(b.dataset.setTheme, true);
    });
  });
  if (unlockBtn && pixelDialog && pixelClose && pixelRefresh) {
    unlockBtn.addEventListener("click", function () {
      try {
        localStorage.setItem(unlockKey, "true");
      } catch (e) {
        // A refresh would discard an in-memory unlock; offer this tab instead.
        pixelUnlocked = true;
        reflectTheme();
        pixelDialog.querySelector(".pixel-dialog-copy").textContent = isZh
          ? "瀏覽器無法儲存設定，此分頁已暫時解鎖，可直接切換 8-bit。"
          : "Storage is unavailable. 8-bit mode is available in this tab.";
        pixelRefresh.hidden = true;
        pixelClose.textContent = isZh ? "關閉" : "Close";
      }
      pixelDialog.showModal();
    });
    pixelClose.addEventListener("click", function () { pixelDialog.close(); });
    pixelRefresh.addEventListener("click", function () {
      pixelUnlocked = true;
      setTheme("8bit", false);
      try {
        localStorage.setItem(unlockKey, "true");
        localStorage.setItem(themeKey, "8bit");
      } catch (e) {
        pixelDialog.close();
        return; // Keep the applied theme if storage becomes unavailable.
      }
      window.location.reload();
    });
  }
  window.addEventListener("storage", function (event) {
    if (event.key !== themeKey && event.key !== unlockKey && event.key !== null) return;
    try {
      pixelUnlocked = localStorage.getItem(unlockKey) === "true";
      setTheme(localStorage.getItem(themeKey) || "light", false);
    } catch (e) { /* retain this tab's current state */ }
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
    var desktopSearchPlaceholder = headerSearchInput.placeholder;
    try {
      var searchPlaceholders = JSON.parse(
        headerSearchInput.getAttribute("data-search-placeholders") || "[]"
      );
      if (Array.isArray(searchPlaceholders) && searchPlaceholders.length) {
        var randomPlaceholder = Math.floor(Math.random() * searchPlaceholders.length);
        desktopSearchPlaceholder = searchPlaceholders[randomPlaceholder];
      }
    } catch (e) { /* keep the server-rendered fallback */ }
    headerSearchInput.dataset.searchSuggestion = desktopSearchPlaceholder;
    var mobileSearchMedia = window.matchMedia("(max-width: 720px)");
    function updateHeaderSearchPlaceholder() {
      headerSearchInput.placeholder = mobileSearchMedia.matches
        ? headerSearchInput.dataset.mobilePlaceholder : desktopSearchPlaceholder;
    }
    updateHeaderSearchPlaceholder();
    if (mobileSearchMedia.addEventListener) {
      mobileSearchMedia.addEventListener("change", updateHeaderSearchPlaceholder);
    } else if (mobileSearchMedia.addListener) {
      mobileSearchMedia.addListener(updateHeaderSearchPlaceholder);
    }
  }
  if (headerSearchForm && headerSearchInput) {
    headerSearchForm.addEventListener("submit", function (event) {
      if (headerSearchInput.value.trim()) return;
      if (headerSearchInput.dataset.searchSuggestionEnabled !== "true") return;
      var suggestedQuery = queryFromSearchPlaceholder(
        headerSearchInput.dataset.searchSuggestion || headerSearchInput.placeholder
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
    sevBtns.forEach(function (x) {
      x.classList.toggle("active", x === button);
      x.setAttribute("aria-pressed", String(x === button));
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-sev]"), function (row) {
      var matches = v === "all" ||
        (v === "week" ? row.dataset.weeklySerious === "true" : row.dataset.sev === v);
      row.classList.toggle("is-hidden", !matches);
      if (matches) n += 1;
    });
    if (countEl) countEl.textContent = String(n);
    var emptyEl = document.getElementById("inc-empty");
    if (emptyEl) emptyEl.classList.toggle("is-hidden", n > 0);
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
    var heroTouchStart = null;
    var reduceHeroMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var heroTransitionMs = reduceHeroMotion ? 0 : 220;
    var heroRotationMs = Number(heroCarousel && heroCarousel.dataset.rotationMs) || 2500;
    if (window.matchMedia && window.matchMedia("(max-width: 720px)").matches) {
      heroRotationMs = Math.max(heroRotationMs, 10000);
    }

    // Reserve each text row for the tallest candidate at the current width.
    // Measuring a hidden copy keeps the visible story and live region untouched.
    function reserveHeroLayout() {
      if (!heroCarousel || !heroCandidates.length || !heroCarousel.clientWidth) return;
      var probe = heroLink.cloneNode(true);
      probe.className = "hero-story hero-layout-probe";
      probe.setAttribute("aria-hidden", "true");
      probe.setAttribute("inert", "");
      var textFields = [
        ["#hero-image-caption", "image_caption"],
        ["#hero-story-kicker", "kicker"],
        ["#hero-story-title", "title"],
        [".summary-preview--hero .summary-preview__text", "summary"]
      ].map(function (field) {
        return [probe.querySelector(field[0]), field[1]];
      });
      var selectors = ["#hero-image-caption", "#hero-story-kicker",
        "#hero-story-title", ".summary-preview--hero"];
      var originalRows = selectors.map(function (selector) {
        return heroLink.querySelector(selector);
      });
      var probeRows = selectors.map(function (selector) {
        var row = probe.querySelector(selector);
        if (row) row.style.minHeight = "0";
        return row;
      });
      var heights = selectors.map(function () { return 0; });
      probe.removeAttribute("id");
      probe.querySelectorAll("[id], [aria-live]").forEach(function (node) {
        node.removeAttribute("id");
        node.removeAttribute("aria-live");
      });
      // Only text is measured; no duplicate photo request is needed.
      var probeImage = probe.querySelector("img");
      if (probeImage) probeImage.remove();
      heroCarousel.appendChild(probe);
      heroCandidates.forEach(function (story) {
        textFields.forEach(function (field) {
          if (field[0]) field[0].textContent = story[field[1]] || "";
        });
        probeRows.forEach(function (row, index) {
          if (row) heights[index] = Math.max(heights[index],
            Math.ceil(row.getBoundingClientRect().height));
        });
      });
      probe.remove();
      originalRows.forEach(function (row, index) {
        if (row) row.style.minHeight = heights[index] + "px";
      });
    }

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
      reserveHeroLayout();
      window.addEventListener("resize", reserveHeroLayout);
      if (window.ResizeObserver && heroCarousel) {
        var heroLayoutWidth = heroCarousel.clientWidth;
        new ResizeObserver(function () {
          var width = heroCarousel.clientWidth;
          if (width !== heroLayoutWidth) {
            heroLayoutWidth = width;
            reserveHeroLayout();
          }
        }).observe(heroCarousel);
      }
      if (document.fonts) {
        document.fonts.ready.then(reserveHeroLayout);
        document.fonts.addEventListener("loadingdone", reserveHeroLayout);
      }
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
        heroLink.addEventListener("touchstart", function (event) {
          if (event.touches.length !== 1) {
            heroTouchStart = null;
            scheduleHeroRotation();
            return;
          }
          var touch = event.touches[0];
          heroTouchStart = { id: touch.identifier, x: touch.clientX, y: touch.clientY };
          stopHeroTimer();
        }, { passive: true });
        heroLink.addEventListener("touchend", function (event) {
          if (!heroTouchStart) return;
          var start = heroTouchStart;
          heroTouchStart = null;
          var touch = Array.prototype.find.call(event.changedTouches, function (item) {
            return item.identifier === start.id;
          });
          if (!touch) {
            scheduleHeroRotation();
            return;
          }
          var dx = touch.clientX - start.x;
          var dy = touch.clientY - start.y;
          if (Math.abs(dx) >= 45 && Math.abs(dx) > Math.abs(dy) * 1.25) {
            event.preventDefault(); // A swipe must not also open the linked article.
            showHero(heroIndex + (dx < 0 ? 1 : -1), dx < 0 ? "next" : "previous");
          } else {
            scheduleHeroRotation();
          }
        }, { passive: false });
        heroLink.addEventListener("touchcancel", function () {
          heroTouchStart = null;
          scheduleHeroRotation();
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
