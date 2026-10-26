/* A brief radar-like flourish for the founder's wing mark. */
(function () {
  "use strict";

  var trigger = document.querySelector("[data-team-logo-play]");
  if (!trigger || !window.matchMedia) return;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var timer = 0;

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

  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      if (!entries.some(function (entry) { return entry.isIntersecting; })) return;
      observer.disconnect();
      window.setTimeout(function () { play(false); }, 350);
    }, { threshold: .6 });
    observer.observe(trigger);
  }
})();
