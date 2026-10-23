"use strict";

// Exercise the shipped bootstrap + theme controller together, including a new
// document after reload. No browser packages or application test hooks needed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.join(__dirname, "..");
const base = fs.readFileSync(path.join(root, "templates/base.html"), "utf8");
const bootstrap = base.match(/<script>(try\{var u=localStorage[\s\S]*?)<\/script>/)[1];
const app = fs.readFileSync(path.join(root, "static/app.js"), "utf8");
const controller = app.slice(app.indexOf("  /* — theme seg:"), app.indexOf("  /* — global header search:"));

function launch(storage = {}, blocked = false, lang = "zh-Hant-TW") {
  function element(dataset = {}) {
    return {
      dataset, hidden: false, attributes: {}, events: {}, textContent: "",
      classList: { add() {}, toggle() {} },
      addEventListener(type, handler) { this.events[type] = handler; },
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name]; }
    };
  }
  const html = element(); html.lang = lang;
  const buttons = ["light", "dark", "8bit"].map(theme => element({ setTheme: theme }));
  const unlock = element(), close = element(), refresh = element(), copy = element();
  const dialog = element();
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; };
  dialog.querySelector = () => copy;
  const favicon = element({ pixelHref: "/pixel-mark.svg" });
  favicon.attributes.href = "/classic-mark.svg";
  let reloads = 0;
  const window = { events: {}, location: { reload() { reloads++; } },
    addEventListener(type, handler) { this.events[type] = handler; } };
  const selectors = { "[data-unlock-8bit]": unlock, ".pixel-dialog": dialog,
    "[data-pixel-close]": close, "[data-pixel-refresh]": refresh, 'link[rel="icon"]': favicon };
  const context = vm.createContext({
    document: { documentElement: html, querySelectorAll: () => buttons,
      querySelector: selector => selectors[selector] },
    localStorage: {
      getItem(key) { if (blocked) throw Error("blocked"); return storage[key] || null; },
      setItem(key, value) { if (blocked) throw Error("blocked"); storage[key] = value; }
    }, window
  });
  vm.runInContext(bootstrap, context);
  vm.runInContext(controller, context);
  return { html, buttons, unlock, close, refresh, dialog, copy, favicon, window,
    reloads: () => reloads,
    choose(theme) { buttons.find(b => b.dataset.setTheme === theme).events.click(); } };
}

const storage = {};
let page = launch(storage);
assert.equal(page.buttons[2].hidden, true);
page.choose("dark");
assert.equal(storage["avwire-theme"], "dark");
page.unlock.events.click();
assert.equal(page.dialog.open, true);
assert.equal(storage["skytical-8bit-unlocked"], "true");
assert.equal(page.buttons[2].hidden, true, "Reveal only after reload");
assert.equal(storage["avwire-theme"], "dark", "Opening the dialog preserves the current choice");
page.refresh.events.click();
assert.equal(page.reloads(), 1);
assert.equal(storage["avwire-theme"], "8bit", "Refresh persists the pixel theme before navigation");
page = launch(storage);
assert.equal(page.buttons[2].hidden, false);
assert.equal(page.html.dataset.theme, "8bit", "Refresh directly applies the unlocked theme");
assert.equal(page.buttons[2].attributes["aria-pressed"], "true");
assert.equal(page.favicon.attributes.href, "/pixel-mark.svg");
page = launch(storage, false, "en");
assert.equal(page.html.dataset.theme, "8bit", "Persist across reload and language navigation");
page.choose("light");
assert.equal(page.favicon.attributes.href, "/classic-mark.svg");

const laterStorage = { "avwire-theme": "dark" };
const later = launch(laterStorage);
later.unlock.events.click();
later.close.events.click();
assert.equal(laterStorage["avwire-theme"], "dark", "Later preserves the selected theme");
assert.equal(later.reloads(), 0);
assert.equal(launch(laterStorage).html.dataset.theme, "dark");

for (const bad of ["8bit", "unknown"]) {
  const locked = launch({ "avwire-theme": bad });
  assert.notEqual(locked.html.dataset.theme, bad, "Reject locked or invalid stored themes");
  locked.choose("8bit");
  assert.equal(locked.html.dataset.theme, "light");
}

const noStorage = launch({}, true);
noStorage.unlock.events.click();
assert.equal(noStorage.buttons[2].hidden, false);
assert.equal(noStorage.refresh.hidden, true, "Do not offer a reload that would discard the unlock");
noStorage.choose("8bit");
assert.equal(noStorage.html.dataset.theme, "8bit");
noStorage.close.events.click();
assert.equal(noStorage.dialog.open, false);

storage["skytical-8bit-unlocked"] = "true";
storage["avwire-theme"] = "8bit";
page.window.events.storage({ key: "avwire-theme" });
assert.equal(page.html.dataset.theme, "8bit");
delete storage["skytical-8bit-unlocked"];
page.window.events.storage({ key: "skytical-8bit-unlocked" });
assert.equal(page.html.dataset.theme, "light");
assert.equal(page.buttons[2].hidden, true);
assert.equal(storage["avwire-theme"], "8bit", "Cross-tab sync does not write back");

console.log("PASS pixel theme: unlock/reload, persistence, language navigation, invalid values, storage failure, cross-tab sync, favicon and pressed state");
