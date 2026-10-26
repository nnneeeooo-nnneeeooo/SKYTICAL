/* A brief radar-like flourish for the founder's wing mark. */
(function () {
  "use strict";

  var trigger = document.querySelector("[data-team-logo-play]");
  if (!trigger || !window.matchMedia) return;
  var image = trigger.querySelector("img");
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var timer = 0;
  var entryTimer = 0;
  var observer = null;

  function play(restart) {
    if (reduced.matches || document.documentElement.dataset.theme === "8bit") return;
    if (trigger.classList.contains("is-playing")) {
      if (!restart) return;
      trigger.classList.remove("is-playing");
      void trigger.offsetWidth;
    }
    trigger.classList.add("is-playing");
    window.clearTimeout(timer);
    timer = window.setTimeout(function () {
      trigger.classList.remove("is-playing");
    }, 2400);
  }

  trigger.addEventListener("pointerenter", function (event) {
    if (event.pointerType === "mouse" || event.pointerType === "pen") play(false);
  });
  trigger.addEventListener("click", function () { play(true); });

  function startOnEntry(event) {
    if (!image || !image.complete || !image.naturalWidth) {
      if (image) image.addEventListener("load", function () { startOnEntry(event); }, { once: true });
      return;
    }
    if (observer) observer.disconnect();
    window.clearTimeout(entryTimer);
    entryTimer = window.setTimeout(function () {
      var box = trigger.getBoundingClientRect();
      var inView = box.bottom > 0 && box.right > 0 &&
        box.top < window.innerHeight && box.left < window.innerWidth;
      if (inView) { play(Boolean(event.persisted)); return; }
      if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver(function (entries) {
          if (!entries.some(function (entry) { return entry.isIntersecting; })) return;
          observer.disconnect();
          play(Boolean(event.persisted));
        }, { threshold: .6 });
        observer.observe(trigger);
      } else {
        play(Boolean(event.persisted));
      }
    }, 350);
  }

  window.addEventListener("pageshow", startOnEntry);
})();
