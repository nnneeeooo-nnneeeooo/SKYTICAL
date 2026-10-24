"use strict";
const assert = require("node:assert/strict");
const photos = require("../static/radar-photos.js");
const payload = { photos: [{
  thumbnail_large: { src: "https://t.plnspttrs.net/123/photo_280.jpg?original=1" },
  link: "https://www.planespotters.net/photo/123/airframe?utm_source=api",
  photographer: "Test photographer",
}] };

(async () => {
  const normalized = photos.normalize(payload);
  assert.equal(normalized.src, payload.photos[0].thumbnail_large.src);
  assert.equal(normalized.link, payload.photos[0].link);
  assert.equal(photos.normalize({ photos: [] }), null);
  for (const src of ["javascript:alert(1)", "http://t.plnspttrs.net/a.jpg",
    "https://t.plnspttrs.net.evil.test/a.jpg", "https://user@t.plnspttrs.net/a.jpg"]) {
    assert.equal(photos.normalize({ photos: [{ ...payload.photos[0], thumbnail_large: { src } }] }), null);
  }
  assert.equal(photos.normalize({ photos: [{ ...payload.photos[0], photographer: "" }] }), null);
  assert.equal(photos.normalize({ photos: [{ ...payload.photos[0], link: "https://evil.test/photo/123" }] }), null);

  let calls = [];
  global.fetch = async (url, options) => {
    calls.push(url);
    assert.equal(options.credentials, "omit");
    return { ok: true, json: async () => payload };
  };
  const [a, b] = await Promise.all([photos.fetchPhoto("789275"), photos.fetchPhoto("789275")]);
  assert.equal(calls.length, 1, "Concurrent opens must share one request");
  assert.equal(calls[0], "https://api.planespotters.net/pub/photos/hex/789275");
  assert.deepEqual(a, b);
  await photos.fetchPhoto("789275");
  assert.equal(calls.length, 1, "Cached metadata must avoid another request");
  await photos.fetchPhoto("ABC123");
  assert.ok(calls[1].endsWith("/abc123"));
  await photos.fetchPhoto("~abc123");
  assert.equal(calls.length, 2, "Invalid identities must never reach the provider");

  global.fetch = async () => ({ ok: true, json: async () => ({ photos: [] }) });
  assert.equal(await photos.fetchPhoto("123456"), null, "Missing photo must not use a different airframe");
  global.fetch = async () => ({ ok: false, status: 429 });
  await assert.rejects(photos.fetchPhoto("111111"), /429/);
  global.fetch = async () => ({ ok: true, json: async () => payload });
  assert.ok(await photos.fetchPhoto("111111"), "Temporary failures must remain retryable");

  class Element {
    constructor() { this.dataset = {}; this.events = {}; }
    setAttribute() {}
    appendChild(child) { this.child = child; }
    replaceChildren(...children) { this.children = children; }
    addEventListener(event, handler) { this.events[event] = handler; }
  }
  global.document = { createElement: () => new Element() };
  const copy = { photoLoading: "loading", photoMissing: "missing", photoError: "error",
    photoOriginal: "original", photoAircraft: "aircraft" };
  const container = new Element();
  await photos.render(container, "789275", "CX844", copy);
  const [link, credit] = container.children;
  assert.equal(link.href, normalized.link);
  assert.equal(link.child.src, normalized.src);
  assert.equal(link.rel, "noopener");
  assert.ok(credit.textContent.includes("Test photographer"));
  link.child.events.error();
  assert.equal(container.textContent, "error", "Broken image must become a clear status");
  const missing = new Element();
  await photos.render(missing, "123456", "missing", copy);
  assert.equal(missing.textContent, "missing");
  console.log("radar photos: exact identity, cache, URL safety, credit and failure states passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
