/* Highlight a search term (and configured aliases) in article body text. */
(function () {
  "use strict";

  var root = document.querySelector("[data-article-body]");
  if (!root) return;

  var query = "";
  try {
    query = (new URL(window.location.href).searchParams.get("highlight") || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120);
  } catch (error) {
    return;
  }
  if (!query) return;

  function normalize(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLocaleLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function escapePattern(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function queryCandidates() {
    var candidates = [query].concat(query.split(/\s+/));
    return new Set(candidates.map(normalize).filter(Boolean));
  }

  function highlightTerms(groups) {
    var candidates = queryCandidates();
    var terms = new Map();
    [query].concat(query.split(/\s+/)).forEach(function (term) {
      var normalized = normalize(term);
      if (normalized) terms.set(normalized, term);
    });
    groups.forEach(function (group) {
      if (!Array.isArray(group)) return;
      var matchesQuery = group.some(function (alias) {
        return candidates.has(normalize(alias));
      });
      if (!matchesQuery) return;
      group.forEach(function (alias) {
        var normalized = normalize(alias);
        if (normalized) terms.set(normalized, String(alias));
      });
    });
    return Array.from(terms.values()).sort(function (left, right) {
      return right.length - left.length;
    });
  }

  function termPattern(term) {
    var escaped = escapePattern(term);
    if (/^[A-Za-z0-9]/.test(term)) escaped = "(?<![A-Za-z0-9])" + escaped;
    if (/[A-Za-z0-9]$/.test(term)) escaped += "(?![A-Za-z0-9])";
    return escaped;
  }

  function markMatches(terms) {
    if (!terms.length) return [];
    var pattern = new RegExp(terms.map(termPattern).join("|"), "giu");
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    var current;
    while ((current = walker.nextNode())) nodes.push(current);

    var marks = [];
    nodes.forEach(function (node) {
      var text = node.nodeValue || "";
      pattern.lastIndex = 0;
      if (!pattern.test(text)) return;
      pattern.lastIndex = 0;

      var fragment = document.createDocumentFragment();
      var cursor = 0;
      var match;
      while ((match = pattern.exec(text))) {
        if (match.index > cursor) {
          fragment.appendChild(document.createTextNode(text.slice(cursor, match.index)));
        }
        var mark = document.createElement("mark");
        mark.className = "search-hit";
        mark.textContent = match[0];
        fragment.appendChild(mark);
        marks.push(mark);
        cursor = match.index + match[0].length;
      }
      if (cursor < text.length) {
        fragment.appendChild(document.createTextNode(text.slice(cursor)));
      }
      node.parentNode.replaceChild(fragment, node);
    });
    return marks;
  }

  function finish(groups) {
    var marks = markMatches(highlightTerms(groups));
    if (!marks.length) return;
    var pulseStarted = false;
    function startPulse() {
      if (pulseStarted) return;
      pulseStarted = true;
      marks.forEach(function (mark) { mark.classList.add("search-hit-pulse"); });
      window.setTimeout(function () {
        marks.forEach(function (mark) { mark.classList.remove("search-hit-pulse"); });
      }, 3000);
    }

    function revealFirstMark() {
      marks[0].scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto" : "smooth",
        block: "center"
      });
      startPulse();
    }

    var articlePage = root.closest(".article-page") || root;
    var pendingImages = Array.prototype.filter.call(
      articlePage.querySelectorAll("img"),
      function (image) { return !image.complete; }
    );
    if (pendingImages.length) {
      var remaining = pendingImages.length;
      pendingImages.forEach(function (image) {
        function imageSettled() {
          remaining -= 1;
          if (remaining === 0) revealFirstMark();
        }
        image.addEventListener("load", imageSettled, { once: true });
        image.addEventListener("error", imageSettled, { once: true });
      });
    }
    window.setTimeout(revealFirstMark, 700);
  }

  fetch(root.dataset.searchAliasesUrl, { credentials: "same-origin" })
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(function (payload) {
      finish(Array.isArray(payload.groups) ? payload.groups : []);
    })
    .catch(function () {
      finish([]);
    });
})();
