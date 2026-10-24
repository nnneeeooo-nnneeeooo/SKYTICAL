"use strict";
const assert = require("assert");
const spacing = require("../static/text-spacing.js");
for (const [source, expected] of [
  ["中 文 航 空", "中文航空"],
  ["SKYTICAL 是 AI 航空新聞", "SKYTICAL是AI航空新聞"],
  ["New York 的 Boeing 787 航機", "New York的Boeing 787航機"],
  ["Latest News and Air France", "Latest News and Air France"],
  ["中文 123 航班（ TPE ）", "中文123航班（TPE）"],
  ["中文\u00a0English", "中文\u00a0English"],
  ["𠀀 English", "𠀀English"]
]) assert.strictEqual(spacing.compact(source), expected);
console.log("test_text_spacing_client: OK");
