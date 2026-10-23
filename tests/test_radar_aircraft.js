"use strict";
const assert = require("node:assert/strict");
const aircraft = require("../static/radar-aircraft.js");

// A known heavy must not look like a commuter turboprop or a light aircraft.
assert.ok(aircraft.profile("A388").size > aircraft.profile("B77W").size);
assert.ok(aircraft.profile("B77W").size > aircraft.profile("A20N").size);
assert.ok(aircraft.profile("A20N").size > aircraft.profile("AT76").size);
assert.ok(aircraft.profile("AT76").size > aircraft.profile("C172").size);
assert.equal(aircraft.profile(" b748 ").shape, "quad");
assert.equal(aircraft.profile("E190").kind, "regional");
assert.equal(aircraft.profile("DHC6").shape, "prop");
assert.equal(aircraft.profile("A139").shape, "helicopter");
assert.notEqual(aircraft.svg("AT76"), aircraft.svg("B77W"));
assert.notEqual(aircraft.svg("B748"), aircraft.svg("A320"));
for (const value of ["", null, undefined, "UNKNOWN", "A999", '<img src=x onerror=alert(1)>']) {
  assert.equal(aircraft.profile(value).kind, "unknown");
  assert.ok(!aircraft.svg(value).includes("<img"));
  assert.ok(aircraft.svg(value).includes('aria-hidden="true"'));
}
console.log("radar aircraft: relative sizes, silhouettes and unknown-type safety passed");
