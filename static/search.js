/* SKYTICAL static full-text news search. The build expands configured aliases
   into each record, so official names and common short names are equivalent.
   Model filters follow public credits, including DeepSeek V4.1 Flash. */
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

  function localized(record, field, lang) {
    var value = record[field] || {};
    var fallbackLang = lang === "zh" ? "en" : "zh";
    return value[lang] || value[fallbackLang] || "";
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
      (record.models || []).join(" "),
    ].join(" "));
  }

  function scoreRecord(record, criteria, minimumMatches) {
    var haystack = recordSearchText(record);
    var matchedTerms = criteria.terms.filter(function (term) {
      return termMatches(haystack, term);
    });
    if (matchedTerms.length < minimumMatches) {
      return -1;
    }
    var title = normalize(localized(record, "title", criteria.lang));
    var summary = normalize(localized(record, "summary", criteria.lang));
    var score = 1;
    if (criteria.normalizedQuery && title === criteria.normalizedQuery) score += 200;
    else if (criteria.normalizedQuery && title.indexOf(criteria.normalizedQuery) !== -1) score += 100;
    matchedTerms.forEach(function (term) {
      if (termMatches(title, term)) score += 20;
      if (termMatches(summary, term)) score += 6;
    });
    return score;
  }

  function matchingRecords(records, criteria, minimumMatches) {
    return records.map(function (record) {
      var airlines = Array.isArray(record.airlines) ? record.airlines : [];
      if (criteria.model && (record.models || []).indexOf(criteria.model) === -1) {
        return { record: record, score: -1 };
      }
      if (criteria.airlineKey && airlines.indexOf(criteria.airlineKey) === -1) {
        return { record: record, score: -1 };
      }
      return {
        record: record,
        score: scoreRecord(record, criteria, minimumMatches)
      };
    }).filter(function (row) {
      return row.score >= 0;
    });
  }

  function parseModelQuery(records, query) {
    // Only public credits enter this index. Match versions as a whole and
    // accept spaces, hyphens or compact spelling without exposing internal IDs.
    var labels = Array.from(new Set(records.flatMap(function (record) {
      return Array.isArray(record.models) ? record.models : [];
    }))).sort(function (a, b) { return b.length - a.length; });
    for (var label of labels) {
      var parts = label.normalize("NFKC").match(/[\p{L}\p{N}]+/gu) || [];
      var pattern = parts.map(function (part) {
        return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      }).join("[\\s.-]*");
      var match = new RegExp("^" + pattern + "(?![\\p{L}\\p{N}]|\\.\\d)", "iu").exec(query);
      if (match) return { model: label, remainder: query.slice(match[0].length).trim() };
    }
    return null;
  }

  function searchRecords(records, query, airlineCodes, lang) {
    query = String(query || "").trim();
    lang = lang === "en" ? "en" : "zh";
    if (!normalize(query)) {
      return { matches: [], airlineQuery: null, highlightQuery: "" };
    }

    var airlineQuery = parseAirlineCodeQuery(query, airlineCodes);
    var textQuery = airlineQuery ? airlineQuery.remainder : query;
    var modelQuery = parseModelQuery(records, textQuery.normalize("NFKC"));
    if (modelQuery) textQuery = modelQuery.remainder;
    var normalizedQuery = normalize(textQuery);
    var terms = normalizedQuery.split(/\s+/).filter(Boolean);
    var criteria = {
      normalizedQuery: normalizedQuery,
      terms: terms,
      airlineKey: airlineQuery ? airlineQuery.key : "",
      model: modelQuery ? modelQuery.model : "",
      lang: lang
    };
    var matches = matchingRecords(records, criteria, terms.length);
    if (!matches.length && terms.length >= 3 && !modelQuery &&
        !/^gpt[\s-]*\d/i.test(textQuery)) {
      /* Daily suggestions may paraphrase one phrase from the source title.
         Keep normal searches strict, then allow one unmatched term only when
         the strict pass produced nothing. */
      matches = matchingRecords(records, criteria, terms.length - 1);
    }
    matches.sort(function (left, right) {
      if (right.score !== left.score) return right.score - left.score;
      return String(right.record.published || "").localeCompare(
        String(left.record.published || ""));
    });

    var highlightQuery = airlineQuery ? (
      airlineQuery.remainder || localized(airlineQuery, "label", lang)
    ) : query;
    return {
      matches: matches,
      airlineQuery: airlineQuery,
      highlightQuery: highlightQuery
    };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      normalize: normalize,
      termMatches: termMatches,
      parseAirlineCodeQuery: parseAirlineCodeQuery,
      searchRecords: searchRecords
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
    var categoryLabel = localized(record, "category", lang);
    var tagClass = formatLabel ? "tag-neutral" : "tag-outline";
    if (formatLabel) categoryLabel += " · " + formatLabel;
    meta.appendChild(textNode("span", "tag " + tagClass, categoryLabel));
    meta.appendChild(textNode("time", "text-muted", record.date || ""));
    card.appendChild(meta);

    var url = recordUrl(record, highlightQuery);
    var link = document.createElement("a");
    link.className = "search-result-link";
    link.href = url;
    link.appendChild(textNode("h2", "", localized(record, "title", lang)));
    card.appendChild(link);

    var summary = localized(record, "summary", lang);
    if (summary) card.appendChild(textNode("p", "text-muted", summary));

    var footer = document.createElement("div");
    footer.className = "search-result-footer";
    footer.appendChild(textNode("span", "text-muted", record.source || ""));
    var more = document.createElement("a");
    more.href = url;
    more.textContent = root.dataset.readMore;
    footer.appendChild(more);
    card.appendChild(footer);
    return card;
  }

  function runSearch() {
    var query = input.value.trim();
    updateQueryUrl(query);
    results.replaceChildren();

    if (!query) {
      status.textContent = root.dataset.prompt;
      return;
    }

    if (!normalize(query)) {
      status.textContent = searchStatus(query, null, 0);
      return;
    }

    if (!ready) {
      status.textContent = root.dataset.loading;
      loadIndex().then(runSearch).catch(showLoadError);
      return;
    }

    var outcome = searchRecords(records, query, airlineCodes, lang);
    var matches = outcome.matches;
    var highlightQuery = outcome.highlightQuery;
    status.textContent = searchStatus(query, outcome.airlineQuery, matches.length);
    if (!matches.length) return;

    var fragment = document.createDocumentFragment();
    matches.forEach(function (row) {
      fragment.appendChild(resultCard(row.record, highlightQuery));
    });
    results.appendChild(fragment);
  }

  function searchStatus(query, airlineQuery, count) {
    if (airlineQuery) {
      var template = count ? root.dataset.airlineCodeCountTemplate :
        root.dataset.airlineCodeEmptyTemplate;
      return airlineStatus(template, airlineQuery, count);
    }
    return count ? root.dataset.countTemplate.replace("{count}", String(count)) :
      root.dataset.emptyTemplate.replace("{query}", query);
  }

  function airlineStatus(template, airlineQuery, count) {
    var label = localized(airlineQuery, "label", lang) || airlineQuery.key;
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
    // Revalidate cached indexes when airline mappings or public credits change.
    loading = fetch(root.dataset.indexUrl, { credentials: "same-origin", cache: "no-cache" })
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
