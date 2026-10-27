/* Verify the header logo's hover journey without a browser dependency. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/logo-flight.js"), "utf8");

function setup(width, reducedMotion = false, theme = "light") {
  let now = 0;
  let next = null;
  function element(rect = {}) {
    const listeners = {};
    const attributes = {};
    const classes = new Set();
    const style = {
      setProperty(name, value) { this[name] = value; },
      removeProperty(name) { delete this[name]; },
    };
    return {
      listeners, attributes, style,
      classList: {
        add(...names) { names.forEach(name => classes.add(name)); },
        remove(...names) { names.forEach(name => classes.delete(name)); },
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
        contains(name) { return classes.has(name); },
      },
      addEventListener(name, handler) { listeners[name] = handler; },
      setAttribute(name, value) { attributes[name] = value; },
      removeAttribute(name) { delete attributes[name]; },
      getBoundingClientRect() { return rect; },
    };
  }
  const brandWidth = Math.min(320, width - 36);
  const brandHeight = brandWidth * .22;
  const shell = element({ left: 0, top: 0, right: width, bottom: 86, width, height: 86 });
  const link = element({ left: 18, top: 8, right: 18 + brandWidth,
    bottom: 8 + brandHeight, width: brandWidth, height: brandHeight });
  const sprite = element({ left: 18, top: 8, right: 18 + brandWidth / 4,
    bottom: 8 + brandHeight, width: brandWidth / 4, height: brandHeight });
  const trailSvg = element();
  const trail = element();
  link.querySelector = () => sprite;
  sprite.querySelector = () => ({ complete: true, naturalWidth: 1000 });
  link.closest = () => shell;
  shell.querySelector = () => trailSvg;
  trailSvg.querySelector = () => trail;
  const root = { dataset: { theme } };
  const document = {
    documentElement: root, hidden: false, listeners: {},
    querySelector: () => link,
    addEventListener(name, handler) { this.listeners[name] = handler; },
  };
  const reduced = { matches: reducedMotion, addEventListener() {} };
  const window = {
    matchMedia: () => reduced,
    performance: { now: () => now },
    requestAnimationFrame(handler) { next = handler; return 1; },
    cancelAnimationFrame() { next = null; },
    listeners: {},
    addEventListener(name, handler) { this.listeners[name] = handler; },
  };
  vm.runInNewContext(source, { document, window, MutationObserver: class {
    observe() {}
  } });
  return {
    link, sprite, trail, root, window, document,
    hover(pointerType = "mouse") { link.listeners.pointerenter({ pointerType }); },
    tick(time) {
      now = time;
      assert.ok(next, "animation ended before " + time);
      next(time);
      const match = (sprite.style.transform || "").match(
        /translate\(([-\d.]+)px, ([-\d.]+)px\) rotate\(([-\d.]+)deg\) scale\(([-\d.]+)\)/
      );
      return match && { x: +match[1], y: +match[2], angle: +match[3], size: +match[4] };
    },
  };
}

for (const width of [320, 736, 1200]) {
  const ui = setup(width);
  ui.hover("touch");
  assert.equal(ui.link.classList.contains("is-flying"), false);
  ui.hover();
  assert.equal(ui.link.classList.contains("is-flying"), true);
  const tiny = ui.tick(430);
  assert.ok(Math.abs(tiny.size - .42) < .002);
  const top = ui.tick(1850);
  const orbit = ui.tick(2350);
  assert.ok(Math.abs(top.x - orbit.x) > 10, "upper corner must have a visible loop");
  ui.tick(4600);
  const lower = ui.tick(4788);
  const lowerOrbit = ui.tick(4975);
  assert.ok(Math.abs(lower.x - lowerOrbit.x) > 5, "lower corner must have a visible loop");
  ui.tick(6600);
  const nearHome = ui.tick(7349);
  assert.ok(Math.abs(nearHome.x) < .1 && Math.abs(nearHome.y) < .1);
  assert.ok(Math.abs(nearHome.size - 1) < .003, "landing must reach original size smoothly");
  ui.tick(7350);
  assert.equal(ui.link.classList.contains("is-flying"), false);
  assert.equal(ui.sprite.style.transform, "");
  assert.equal(ui.trail.attributes.d, "");
}

for (const [reducedMotion, theme] of [[true, "light"], [false, "8bit"]]) {
  const ui = setup(736, reducedMotion, theme);
  ui.hover();
  assert.equal(ui.link.classList.contains("is-flying"), false);
}

console.log("test_logo_flight: OK");
