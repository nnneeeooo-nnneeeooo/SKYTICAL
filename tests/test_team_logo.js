/* A page entry, including a history restore, must replay the founder mark. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/team-logo.js"), "utf8");

function setup(theme = "light", prefersReducedMotion = false, initiallyVisible = true) {
  const classes = new Set();
  const timers = new Map();
  const listeners = {};
  let nextTimer = 0;
  let observer;
  const image = { complete: true, naturalWidth: 250 };
  const trigger = {
    offsetWidth: 88,
    getBoundingClientRect() {
      return initiallyVisible
        ? { top: 718, bottom: 800, left: 24, right: 107 }
        : { top: 900, bottom: 982, left: 24, right: 107 };
    },
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    addEventListener(name, handler) { listeners[name] = handler; },
    querySelector() { return image; },
  };
  class IntersectionObserver {
    constructor(callback) { this.callback = callback; observer = this; }
    observe() {}
    disconnect() {}
  }
  const window = {
    IntersectionObserver,
    innerWidth: 390,
    innerHeight: 844,
    matchMedia() { return { matches: prefersReducedMotion }; },
    addEventListener(name, handler) { listeners[name] = handler; },
    setTimeout(handler) { const id = ++nextTimer; timers.set(id, handler); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const document = {
    documentElement: { dataset: { theme } },
    querySelector() { return trigger; },
  };
  vm.runInNewContext(source, { window, document, IntersectionObserver });
  return {
    classes, listeners,
    enter(persisted = false) {
      listeners.pageshow({ persisted });
      const first = [...timers.keys()][0];
      const handler = timers.get(first);
      timers.delete(first);
      handler();
    },
    reveal() { observer.callback([{ isIntersecting: true }]); },
    finish() {
      for (const handler of timers.values()) handler();
      timers.clear();
    },
  };
}

const ui = setup();
ui.enter();
assert.equal(ui.classes.has("is-playing"), true, "visible mobile logo plays on entry");
ui.finish();
assert.equal(ui.classes.has("is-playing"), false, "animation settles");
ui.enter(true);
assert.equal(ui.classes.has("is-playing"), true, "history restore replays");
ui.finish();
ui.enter();
assert.equal(ui.classes.has("is-playing"), true, "reload replays");

const belowFold = setup("light", false, false);
belowFold.enter();
assert.equal(belowFold.classes.has("is-playing"), false, "offscreen logo waits");
belowFold.reveal();
assert.equal(belowFold.classes.has("is-playing"), true, "scrolling to logo plays");

for (const restricted of [setup("8bit"), setup("light", true)]) {
  restricted.enter();
  assert.equal(restricted.classes.has("is-playing"), false);
}

console.log("test_team_logo: OK");
