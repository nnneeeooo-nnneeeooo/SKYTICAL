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
  ["𠀀 English", "𠀀English"],
  ["完成試飛。G400於2024年首飛。", "完成試飛。 G400於2024年首飛。"],
  ["第一句。 第二句。  第三句。", "第一句。 第二句。 第三句。"],
  ["已起飛！下一班呢？仍在準備。", "已起飛！ 下一班呢？ 仍在準備。"],
  ["他說：「已完成。」下一步試飛。", "他說：「已完成。」 下一步試飛。"],
  ["真的！？下一句。（附註。）後續。", "真的！？ 下一句。 （附註。） 後續。"],
  ["第一句。\n第二段。", "第一句。\n第二段。"],
  ["English sentence. Another with 0.89 and U.S. aviation.", "English sentence. Another with 0.89 and U.S. aviation."],
  ["𠀀完成。𠀀 下一句。", "𠀀完成。 𠀀下一句。"]
]) {
  assert.strictEqual(spacing.compact(source), expected);
  assert.strictEqual(spacing.compact(expected), expected);
}

// Exercise the actual DOM path, including text split by inline elements.
function element(tagName, childNodes) {
  return { nodeType: 1, tagName, childNodes,
    matches() { return tagName === "CODE"; }, hasAttribute() { return false; } };
}
function text(data) { return { nodeType: 3, data }; }
const first = text("完成試飛。"), next = text("G400"), tail = text(" 於2024年首飛。 下一句。");
const second = text("第二段。"), skipped = text("中文 AI。下一句。");
const root = element("DIV", [element("P", [first, element("STRONG", [next]), tail]),
  element("P", [second]), element("CODE", [skipped])]);
spacing.normalize(root);
assert.strictEqual(first.data + next.data + tail.data, "完成試飛。 G400於2024年首飛。 下一句。");
assert.strictEqual(second.data, "第二段。");
assert.strictEqual(skipped.data, "中文 AI。下一句。");
spacing.normalize(root);
assert.strictEqual(first.data + next.data + tail.data, "完成試飛。 G400於2024年首飛。 下一句。");
console.log("test_text_spacing_client: OK");
