(function () {
  "use strict";
  var cjk = "\\u2e80-\\u9fff\\uf900-\\ufaff\\uff01-\\uff60\\u{20000}-\\u{323af}";
  var spaces = new RegExp("(?<=[" + cjk + "]) +| +(?=[" + cjk + "])", "gu");
  var blocks = new Set("HTML HEAD BODY ADDRESS ARTICLE ASIDE BLOCKQUOTE BR BUTTON DD DETAILS DIALOG DIV DL DT FIELDSET FIGCAPTION FIGURE FOOTER FORM H1 H2 H3 H4 H5 H6 HEADER HR LI MAIN NAV OL OPTION P SECTION SUMMARY TABLE TBODY TD TH THEAD TR UL".split(" "));
  var skip = "script,style,pre,code,textarea,[contenteditable]:not([contenteditable=false])";
  var attrs = ["alt", "title", "placeholder", "aria-label", "aria-description"];

  function compact(text) { return text.replace(spaces, ""); }

  function normalize(root) {
    var run = [];
    function flush() {
      var text = run.map(function (node) { return node.data; }).join("");
      var removed = new Set();
      text.replace(spaces, function (match, offset) {
        for (var i = 0; i < match.length; i++) removed.add(offset + i);
        return "";
      });
      var offset = 0;
      if (removed.size) run.forEach(function (node) {
        var original = node.data;
        // String offsets and regex indices both use UTF-16 code units.
        var clean = original.split("").filter(function (_, index) {
          return !removed.has(offset + index);
        }).join("");
        offset += original.length;
        if (clean !== original) node.data = clean;
      });
      run = [];
    }
    function visit(node) {
      if (node.nodeType === 3) { run.push(node); return; }
      if (node.nodeType !== 1) return;
      if (node.matches(skip)) { flush(); return; }
      var block = blocks.has(node.tagName);
      if (block) flush();
      attrs.forEach(function (name) {
        if (!node.hasAttribute(name)) return;
        var original = node.getAttribute(name), clean = compact(original);
        if (clean !== original) node.setAttribute(name, clean);
      });
      Array.from(node.childNodes).forEach(visit);
      if (block) flush();
    }
    visit(root);
    flush();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { compact: compact, normalize: normalize };
  }
  if (typeof document === "undefined") return;
  normalize(document.documentElement);
  var pending = new Set(), scheduled = false;
  new MutationObserver(function (records) {
    records.forEach(function (record) {
      var node = record.target.nodeType === 1 ? record.target : record.target.parentElement;
      if (!node || node.closest(skip)) return;
      while (node.parentElement && !blocks.has(node.tagName)) node = node.parentElement;
      pending.add(node);
    });
    if (scheduled || !pending.size) return;
    scheduled = true;
    queueMicrotask(function () {
      scheduled = false;
      var roots = Array.from(pending);
      pending.clear();
      roots.forEach(function (root) {
        if (root.isConnected && !roots.some(function (other) {
          return other !== root && other.contains(root);
        })) normalize(root);
      });
    });
  }).observe(document.documentElement, {
    childList: true, characterData: true, subtree: true,
    attributes: true, attributeFilter: attrs
  });
}());
