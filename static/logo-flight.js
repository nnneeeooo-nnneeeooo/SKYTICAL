/* A single, user-triggered flight for the approved classic wing mark. */
(function () {
  "use strict";

  var link = document.querySelector("[data-brand-flight]");
  if (!link || !window.matchMedia || !window.requestAnimationFrame) return;

  var sprite = link.querySelector("[data-brand-sprite]");
  var spriteImage = sprite && sprite.querySelector("img");
  var shell = link.closest(".brand-shell");
  var trailSvg = shell && shell.querySelector("[data-brand-flight-trail]");
  var trail = trailSvg && trailSvg.querySelector("path");
  if (!spriteImage || !trail) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var frame = 0;
  var runId = 0;
  var playing = false;
  var duration = 7350;
  var clamp = function (value) { return Math.min(1, Math.max(0, value)); };
  var ease = function (value) {
    var t = clamp(value);
    return t * t * (3 - 2 * t);
  };
  var lerp = function (a, b, t) { return a + (b - a) * t; };
  var cubic = function (a, b, c, d, t) {
    var q = 1 - t;
    return q*q*q*a + 3*q*q*t*b + 3*q*t*t*c + t*t*t*d;
  };

  function stop() {
    runId++;
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    playing = false;
    link.classList.remove("is-flying");
    sprite.classList.remove("is-peeking", "is-landing");
    sprite.removeAttribute("data-gaze");
    sprite.style.transform = "";
    sprite.style.removeProperty("--brand-effects-opacity");
    trailSvg.style.opacity = "";
    trail.setAttribute("d", "");
  }

  function play() {
    if (playing || reduced.matches || document.documentElement.dataset.theme === "8bit" ||
        !spriteImage.complete || !spriteImage.naturalWidth) return;
    stop();

    var shellBox = shell.getBoundingClientRect();
    var linkBox = link.getBoundingClientRect();
    var spriteBox = sprite.getBoundingClientRect();
    if (!linkBox.width || !spriteBox.width) return;

    var scale = linkBox.width / 320;
    var rightEdge = Math.min(shellBox.right, shellBox.left + 760);
    var topRightX = rightEdge - linkBox.left - spriteBox.width * .71 - 18;
    var topRightY = shellBox.top + Math.max(20 * scale, 16) - linkBox.top - spriteBox.height / 2;
    var topControlY = Math.min(-40 * scale, topRightY - 18 * scale);
    var lowerLeftX = Math.min(89 * scale, shellBox.width * .2);
    var lowerLeftY = linkBox.height + 33 * scale - spriteBox.height / 2;
    var centerX = linkBox.left - shellBox.left + spriteBox.width / 2;
    var centerY = linkBox.top - shellBox.top + spriteBox.height / 2;
    var points = [];
    var id = runId;
    var started = window.performance.now();

    trailSvg.setAttribute("viewBox", "0 0 " + shellBox.width + " " + shellBox.height);
    link.classList.add("is-flying");
    playing = true;

    function poseAt(ms) {
      var x, y, angle, size, peeking = false, gaze = "", landing = false, effects = 1;
      var u, turn;
      if (ms < 430) {
        u = ease(ms / 430);
        x = 9 * scale * u + Math.sin(u * Math.PI * 2) * 3 * scale;
        y = -18 * scale * u - Math.sin(u * Math.PI) * 8 * scale;
        angle = -22 * u;
        size = lerp(1, .42, u);
      } else if (ms < 1850) {
        u = ease((ms - 430) / 1420);
        x = cubic(9*scale, topRightX*.15, topRightX*.65, topRightX, u);
        y = cubic(-18*scale, topControlY, topRightY + 38*scale, topRightY, u);
        y += Math.sin(u * Math.PI * 4) * 9 * scale * Math.sin(u * Math.PI);
        angle = lerp(-22, 14, u) + Math.sin(u * Math.PI * 3) * 17;
        size = .42 + Math.sin(u * Math.PI * 2) * .025;
      } else if (ms < 2850) {
        u = ease((ms - 1850) / 1000);
        turn = u * Math.PI * 2;
        x = topRightX + 23 * scale * (Math.cos(turn) - 1);
        y = topRightY + 15 * scale * Math.sin(turn);
        angle = 14 + 360 * u;
        size = .42;
        gaze = u < .5 ? "right" : "left";
      } else if (ms < 3250) {
        u = (ms - 2850) / 400;
        var float = Math.sin(Math.PI * u);
        x = topRightX + Math.sin(u * Math.PI * 2) * float * 3 * scale;
        y = topRightY - float * 3 * scale;
        angle = 374 + Math.sin(u * Math.PI * 2) * float * 10;
        size = .42;
        peeking = true;
        gaze = u < .52 ? "right" : "left";
      } else if (ms < 4600) {
        u = ease((ms - 3250) / 1350);
        x = cubic(topRightX, topRightX + 16*scale, lowerLeftX + 170*scale, lowerLeftX, u);
        y = cubic(topRightY, topRightY + 103*scale, lowerLeftY - 43*scale, lowerLeftY, u);
        x += Math.sin(u * Math.PI * 3) * 9 * scale * Math.sin(u * Math.PI);
        angle = lerp(374, 546, u) + Math.sin(u * Math.PI * 2) * 12;
        size = .42;
      } else if (ms < 5350) {
        u = ease((ms - 4600) / 750);
        turn = u * Math.PI * 2;
        x = lowerLeftX + 16 * scale * Math.sin(2 * turn);
        y = lowerLeftY + 10 * scale * Math.sin(turn);
        angle = 546 + Math.sin(turn) * 28;
        size = .42;
        peeking = true;
        gaze = u < .5 ? "left" : "right";
      } else if (ms < 6600) {
        u = ease((ms - 5350) / 1250);
        x = cubic(lowerLeftX, lowerLeftX + 150*scale, -42*scale, 12*scale, u);
        y = cubic(lowerLeftY, lowerLeftY + 24*scale, -70*scale, -9*scale, u);
        y += Math.sin(u * Math.PI * 3) * 7 * scale * Math.sin(u * Math.PI);
        angle = lerp(546, 720, u);
        size = .42 + .30 * ease((u - .45) / .55);
      } else {
        var q = clamp((ms - 6600) / 750);
        u = ease(q);
        x = 12 * scale * (1 - u);
        y = -9 * scale * (1 - u);
        angle = 720 + Math.sin(q * Math.PI) * (1 - u) * 3;
        size = .72 + .28 * u + .022 * Math.sin(q * Math.PI) * u;
        effects = 1 - ease((q - .30) / .70);
        landing = true;
      }
      return { x: x, y: y, angle: angle, size: size, peeking: peeking,
        gaze: gaze, landing: landing, effects: effects };
    }

    function draw(now) {
      if (id !== runId) return;
      var ms = Math.min(duration, now - started);
      var pose = poseAt(ms);
      sprite.style.transform = "translate(" + pose.x.toFixed(2) + "px, " +
        pose.y.toFixed(2) + "px) rotate(" + pose.angle.toFixed(2) +
        "deg) scale(" + pose.size.toFixed(3) + ")";
      sprite.classList.toggle("is-peeking", pose.peeking);
      sprite.classList.toggle("is-landing", pose.landing);
      sprite.style.setProperty("--brand-effects-opacity", pose.effects.toFixed(3));
      trailSvg.style.opacity = pose.effects.toFixed(3);
      if (pose.gaze) sprite.setAttribute("data-gaze", pose.gaze);
      else sprite.removeAttribute("data-gaze");

      if (!pose.peeking) {
        points.push([centerX + pose.x, centerY + pose.y]);
        if (points.length > 30) points.shift();
      } else if (points.length > 1) points.shift();
      trail.setAttribute("d", points.length > 1
        ? "M " + points.map(function (point) {
          return point[0].toFixed(1) + " " + point[1].toFixed(1);
        }).join(" L ")
        : "");
      if (ms < duration) frame = window.requestAnimationFrame(draw);
      else stop();
    }

    frame = window.requestAnimationFrame(draw);
  }

  link.addEventListener("pointerenter", function (event) {
    if (event.pointerType === "mouse" || event.pointerType === "pen") play();
  });
  window.addEventListener("resize", stop);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
  });
  if (reduced.addEventListener) reduced.addEventListener("change", function () {
    if (reduced.matches) stop();
  });
  new MutationObserver(function () {
    if (document.documentElement.dataset.theme === "8bit") stop();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})();
