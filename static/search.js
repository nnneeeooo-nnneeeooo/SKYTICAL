/* SKYTICAL static full-text news search. The build expands configured aliases
   into each record, so official names and common short names are equivalent. */
(function () {
  "use strict";

  function normalize(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLocaleLowerCase()
      .replace(/[^\p{L}\p{N}_]+/gu, " ")
      .trim();
  }

  function termMatches(haystack, term) {
    if (/^[a-z0-9]{1,3}$/.test(term)) {
      return haystack.split(/\s+/).indexOf(term) !== -1;
    }
    return haystack.indexOf(term) !== -1;
  }

  function parseAirlineCodeQuery(query, codeIndex) {
    var raw = String(query || "").trim();
    var explicit = /^(iata|icao|airline)\s*:\s*([A-Za-z0-9]{2,3})(?:\s+(.+))?$/i.exec(raw);
    var automatic = explicit ? null : /^([A-Za-z0-9]{2,3})$/.exec(raw);
    var combined = explicit || automatic ? null : /^([A-Z0-9]{2,3})\s+(.+)$/.exec(raw);
    var requestedType = explicit ? explicit[1].toLowerCase() : "airline";
    var code = String(
      explicit ? explicit[2] : automatic ? automatic[1] : combined ? combined[1] : ""
    ).toUpperCase();
    var remainder = String(
      explicit ? explicit[3] || "" : combined ? combined[2] || "" : ""
    ).trim();
    if (!code) return null;

    var source = codeIndex && typeof codeIndex === "object" ? codeIndex : {};
    var iata = source.iata && typeof source.iata === "object" ? source.iata : {};
    var icao = source.icao && typeof source.icao === "object" ? source.icao : {};
    var labels = source.labels && typeof source.labels === "object" ? source.labels : {};
    var key = "";
    var type = "";
    if (requestedType === "iata") {
      key = iata[code] || "";
      type = "IATA";
    } else if (requestedType === "icao") {
      key = icao[code] || "";
      type = "ICAO";
    } else if (iata[code]) {
      key = iata[code];
      type = "IATA";
    } else if (icao[code]) {
      key = icao[code];
      type = "ICAO";
    }
    if (!key || !labels[key] || typeof labels[key] !== "object") return null;
    return { key: key, code: code, type: type, remainder: remainder, label: labels[key] };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      normalize: normalize,
      termMatches: termMatches,
      parseAirlineCodeQuery: parseAirlineCodeQuery
    };
  }

  var root = typeof document === "undefined" ? null :
    document.getElementById("news-search-app");
  if (!root) return;

  var form = document.getElementById("news-search-form");
  var input = document.getElementById("news-search-input");
  var status = document.getElementById("news-search-status");
  var results = document.getElementById("news-search-results");
  var lang = root.dataset.lang === "en" ? "en" : "zh";
  var otherLang = lang === "zh" ? "en" : "zh";
  var records = [];
  var airlineCodes = { iata: {}, icao: {}, labels: {} };
  var ready = false;
  var loading = null;
  var debounceTimer = 0;

  function localized(record, field) {
    var value = record[field] || {};
    return value[lang] || value[otherLang] || "";
  }

  function localizedValues(record, field) {
    var value = record[field] || {};
    if (typeof value === "string") return [value];
    return [value.zh || "", value.en || ""];
  }

  function recordSearchText(record) {
    return normalize([
      record.id,
      record.source,
      record.date,
      record.published,
      localizedValues(record, "title").join(" "),
      localizedValues(record, "summary").join(" "),
      localizedValues(record, "category").join(" "),
      record.search,
    ].join(" "));
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
    var formatLabel = record.articleFormat === "brief"
      ? root.dataset.briefLabel
      : (record.articleFormat === "roundup" ? root.dataset.roundupLabel : "");
    meta.appendChild(textNode("span", "tag " + (formatLabel ? "tag-neutral" : "tag-outline"), localized(record, "category") + (formatLabel ? " · " + formatLabel : "")));
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

  function scoreRecord(record, normalizedQuery, terms, minimumMatches) {
    var haystack = recordSearchText(record);
    var matchedTerms = terms.filter(function (term) {
      return termMatches(haystack, term);
    });
    if (matchedTerms.length < minimumMatches) {
      return -1;
    }
    var title = normalize(localized(record, "title"));
    var summary = normalize(localized(record, "summary"));
    var score = 1;
    if (normalizedQuery && title === normalizedQuery) score += 200;
    else if (normalizedQuery && title.indexOf(normalizedQuery) !== -1) score += 100;
    matchedTerms.forEach(function (term) {
      if (termMatches(title, term)) score += 20;
      if (termMatches(summary, term)) score += 6;
    });
    return score;
  }

  function matchingRecords(normalizedQuery, terms, minimumMatches, airlineKey) {
    return records.map(function (record) {
      var airlines = Array.isArray(record.airlines) ? record.airlines : [];
      if (airlineKey && airlines.indexOf(airlineKey) === -1) {
        return { record: record, score: -1 };
      }
      return {
        record: record,
        score: scoreRecord(record, normalizedQuery, terms, minimumMatches)
      };
    }).filter(function (row) {
      return row.score >= 0;
    });
  }

  function runSearch() {
    var query = input.value.trim();
    updateQueryUrl(query);
    results.replaceChildren();

    if (!query) {
      status.textContent = root.dataset.prompt;
      return;
    }

    if (!ready) {
      status.textContent = root.dataset.loading;
      loadIndex().then(runSearch).catch(showLoadError);
      return;
    }

    var airlineQuery = parseAirlineCodeQuery(query, airlineCodes);
    var textQuery = airlineQuery ? airlineQuery.remainder : query;
    var normalizedQuery = normalize(textQuery);
    var terms = normalizedQuery.split(/\s+/).filter(Boolean);
    var airlineKey = airlineQuery ? airlineQuery.key : "";
    var matches = matchingRecords(
      normalizedQuery, terms, terms.length, airlineKey);
    if (!matches.length && terms.length >= 3) {
      /* Daily suggestions may paraphrase one phrase from the source title.
         Keep normal searches strict, then allow one unmatched term only when
         the strict pass produced nothing. */
      matches = matchingRecords(
        normalizedQuery, terms, terms.length - 1, airlineKey);
    }
    matches.sort(function (left, right) {
      if (right.score !== left.score) return right.score - left.score;
      return String(right.record.published || "").localeCompare(String(left.record.published || ""));
    });

    if (!matches.length) {
      if (airlineQuery) {
        status.textContent = airlineStatus(
          root.dataset.airlineCodeEmptyTemplate, airlineQuery, 0);
      } else {
        status.textContent = root.dataset.emptyTemplate.replace("{query}", query);
      }
      return;
    }
    status.textContent = airlineQuery ? airlineStatus(
      root.dataset.airlineCodeCountTemplate, airlineQuery, matches.length) :
      root.dataset.countTemplate.replace("{count}", String(matches.length));
    var highlightQuery = airlineQuery ? (
      airlineQuery.remainder || airlineQuery.label[lang] ||
      airlineQuery.label[otherLang] || "") : query;
    var fragment = document.createDocumentFragment();
    matches.forEach(function (row) {
      fragment.appendChild(resultCard(row.record, highlightQuery));
    });
    results.appendChild(fragment);
  }

  function airlineStatus(template, airlineQuery, count) {
    var label = airlineQuery.label[lang] ||
      airlineQuery.label[otherLang] || airlineQuery.key;
    return String(template || "")
      .replace("{code}", airlineQuery.code)
      .replace("{type}", airlineQuery.type)
      .replace("{airline}", label)
      .replace("{count}", String(count));
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

  function showLoadError() {
    ready = false;
    loading = null;
    results.replaceChildren();
    status.textContent = root.dataset.error;
  }

  function loadIndex() {
    if (ready) return Promise.resolve();
    if (loading) return loading;
    loading = fetch(root.dataset.indexUrl, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        records = Array.isArray(payload.items) ? payload.items : [];
        airlineCodes = payload.airlineCodes &&
          typeof payload.airlineCodes === "object" ? payload.airlineCodes :
          { iata: {}, icao: {}, labels: {} };
        ready = true;
      })
      .catch(function (error) {
        showLoadError();
        throw error;
      });
    return loading;
  }

  if (input.value.trim()) runSearch();
  else status.textContent = root.dataset.prompt;
})();
