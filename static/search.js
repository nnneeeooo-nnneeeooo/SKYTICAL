/* AVWIRE static full-text news search. The build expands configured aliases
   into each record, so official names and common short names are equivalent. */
(function () {
  "use strict";

  var root = document.getElementById("news-search-app");
  if (!root) return;

  var form = document.getElementById("news-search-form");
  var input = document.getElementById("news-search-input");
  var status = document.getElementById("news-search-status");
  var results = document.getElementById("news-search-results");
  var lang = root.dataset.lang === "en" ? "en" : "zh";
  var otherLang = lang === "zh" ? "en" : "zh";
  var records = [];
  var ready = false;
  var debounceTimer = 0;

  function normalize(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLocaleLowerCase()
      .replace(/[^\p{L}\p{N}_]+/gu, " ")
      .trim();
  }

  function localized(record, field) {
    var value = record[field] || {};
    return value[lang] || value[otherLang] || "";
  }

  function recordUrl(record, highlightQuery) {
    var urls = record.url || {};
    var rawUrl = urls[lang] || urls[otherLang] || "#";
    if (!highlightQuery || rawUrl === "#") return rawUrl;
    try {
      var url = new URL(rawUrl, window.location.href);
      url.searchParams.set("highlight", highlightQuery);
      return url.pathname + url.search + url.hash;
    } catch (error) {
      return rawUrl;
    }
  }

  function updateQueryUrl(query) {
    try {
      var url = new URL(window.location.href);
      if (query) url.searchParams.set("q", query);
      else url.searchParams.delete("q");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch (error) {
      /* Searching still works if history manipulation is unavailable. */
    }
  }

  function textNode(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  function resultCard(record, highlightQuery) {
    var card = document.createElement("article");
    card.className = "search-result";

    var meta = document.createElement("div");
    meta.className = "search-result-meta";
    meta.appendChild(textNode("span", "tag " + (record.articleFormat === "brief" ? "tag-neutral" : "tag-outline"), localized(record, "category") + (record.articleFormat === "brief" ? " · " + root.dataset.briefLabel : "")));
    meta.appendChild(textNode("time", "text-muted", record.date || ""));
    card.appendChild(meta);

    var link = document.createElement("a");
    link.className = "search-result-link";
    link.href = recordUrl(record, highlightQuery);
    link.appendChild(textNode("h2", "", localized(record, "title")));
    card.appendChild(link);

    var summary = localized(record, "summary");
    if (summary) card.appendChild(textNode("p", "text-muted", summary));

    var footer = document.createElement("div");
    footer.className = "search-result-footer";
    footer.appendChild(textNode("span", "text-muted", record.source || ""));
    var more = document.createElement("a");
    more.href = recordUrl(record, highlightQuery);
    more.textContent = root.dataset.readMore;
    footer.appendChild(more);
    card.appendChild(footer);
    return card;
  }

  function scoreRecord(record, normalizedQuery, terms) {
    var haystack = String(record.search || "");
    if (!terms.every(function (term) { return haystack.indexOf(term) !== -1; })) {
      return -1;
    }
    var title = normalize(localized(record, "title"));
    var summary = normalize(localized(record, "summary"));
    var score = 1;
    if (title === normalizedQuery) score += 200;
    else if (title.indexOf(normalizedQuery) !== -1) score += 100;
    terms.forEach(function (term) {
      if (title.indexOf(term) !== -1) score += 20;
      if (summary.indexOf(term) !== -1) score += 6;
    });
    return score;
  }

  function runSearch() {
    var query = input.value.trim();
    updateQueryUrl(query);
    results.replaceChildren();

    if (!ready) {
      status.textContent = root.dataset.loading;
      return;
    }
    if (!query) {
      status.textContent = root.dataset.prompt;
      return;
    }

    var normalizedQuery = normalize(query);
    var terms = normalizedQuery.split(/\s+/).filter(Boolean);
    var matches = records.map(function (record) {
      return { record: record, score: scoreRecord(record, normalizedQuery, terms) };
    }).filter(function (row) {
      return row.score >= 0;
    }).sort(function (left, right) {
      if (right.score !== left.score) return right.score - left.score;
      return String(right.record.published || "").localeCompare(String(left.record.published || ""));
    });

    if (!matches.length) {
      status.textContent = root.dataset.emptyTemplate.replace("{query}", query);
      return;
    }
    status.textContent = root.dataset.countTemplate.replace("{count}", String(matches.length));
    var fragment = document.createDocumentFragment();
    matches.forEach(function (row) {
      fragment.appendChild(resultCard(row.record, query));
    });
    results.appendChild(fragment);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    window.clearTimeout(debounceTimer);
    runSearch();
  });
  input.addEventListener("input", function () {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(runSearch, 120);
  });
  try {
    input.value = new URL(window.location.href).searchParams.get("q") || "";
  } catch (error) {
    input.value = "";
  }
  fetch(root.dataset.indexUrl, { credentials: "same-origin" })
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(function (payload) {
      records = Array.isArray(payload.items) ? payload.items : [];
      ready = true;
      runSearch();
    })
    .catch(function () {
      ready = false;
      results.replaceChildren();
      status.textContent = root.dataset.error;
    });
})();
