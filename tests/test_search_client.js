"use strict";

const assert = require("assert");
const search = require("../static/search.js");

const codes = {
  iata: { DE: "CFG", CI: "CAL", IT: "TTW" },
  icao: { CFG: "CFG", CAL: "CAL", TTW: "TTW", ASV: "ASV" },
  labels: {
    CFG: { iata: "DE", icao: "CFG", zh: "德國神鷹航空", en: "Condor" },
    CAL: { iata: "CI", icao: "CAL", zh: "中華航空", en: "China Airlines" },
    TTW: { iata: "IT", icao: "TTW", zh: "台灣虎航", en: "Tigerair Taiwan" },
    ASV: { iata: "", icao: "ASV", zh: "Astravia", en: "Astravia" }
  }
};

function parsed(query) {
  return search.parseAirlineCodeQuery(query, codes);
}

assert.deepStrictEqual(
  { key: parsed("DE").key, type: parsed("DE").type, remainder: parsed("DE").remainder },
  { key: "CFG", type: "IATA", remainder: "" }
);
assert.strictEqual(parsed("de").key, "CFG");
assert.strictEqual(parsed("CFG").key, "CFG");
assert.strictEqual(parsed("CFG").type, "ICAO");
assert.strictEqual(parsed("iata:de").key, "CFG");
assert.strictEqual(parsed("icao:cfg").key, "CFG");
assert.strictEqual(parsed("airline:DE A320").remainder, "A320");
assert.strictEqual(parsed("DE A320").key, "CFG");
assert.strictEqual(parsed("DE A320").remainder, "A320");
assert.strictEqual(parsed("de A320"), null);
assert.strictEqual(parsed("9S"), null);
assert.strictEqual(parsed("ZZ"), null);
assert.strictEqual(parsed("ASV").type, "ICAO");

const beyond = search.normalize("Etihad launches Beyond Borders cabins");
assert.strictEqual(search.termMatches(beyond, "de"), false);
assert.strictEqual(search.termMatches(search.normalize("DE A320"), "de"), true);
assert.strictEqual(search.termMatches(search.normalize("waiting for passengers"), "it"), false);
assert.strictEqual(search.termMatches(search.normalize("IT flight 216"), "it"), true);
assert.strictEqual(search.termMatches(beyond, "beyond"), true);

const articles = [
  {
    id: "exact", title: { zh: "華航新航線", en: "New routes" },
    summary: { en: "China Airlines expands" }, airlines: ["CAL"],
    published: "2026-10-01", url: { en: "/en/news/exact/" }
  },
  {
    id: "recent", title: { en: "New routes announced" },
    summary: { en: "Condor expands" }, airlines: ["CFG"],
    published: "2026-10-15", url: { en: "/en/news/recent/" }
  },
  {
    id: "older", title: { en: "New routes announced" },
    summary: { en: "Condor expands" }, airlines: ["CFG"],
    published: "2026-10-14", url: { en: "/en/news/older/" }
  },
  { id: "unrelated", title: { en: "Airport terminal" }, search: "航廈" }
];
const originalArticles = JSON.stringify(articles);
function find(query, lang = "en", items = articles) {
  return search.searchRecords(items, query, codes, lang);
}
function ids(outcome) {
  return outcome.matches.map(row => row.record.id);
}

// Exact titles beat newer partial matches; ties retain newest-first ordering.
assert.deepStrictEqual(ids(find("New routes")), ["exact", "recent", "older"]);
assert.deepStrictEqual(ids(find("華航", "zh")), ["exact"]);
assert.deepStrictEqual(ids(find("航廈")), ["unrelated"]);
assert.deepStrictEqual(ids(find("CI")), ["exact"]);
assert.deepStrictEqual(ids(find("DE")), ["recent", "older"]);
assert.strictEqual(find("CI", "zh").highlightQuery, "中華航空");
assert.strictEqual(find("CI").highlightQuery, "China Airlines");
assert.strictEqual(find("DE new routes").highlightQuery, "new routes");
assert.deepStrictEqual(ids(find("DE new routes")), ["recent", "older"]);
assert.deepStrictEqual(ids(find("DE airport")), []);
assert.deepStrictEqual(ids(find("ZZ")), []);
// Three-term fallback runs only if strict matching finds nothing.
assert.deepStrictEqual(ids(find("new routes missing")), ["recent", "older", "exact"]);
assert.deepStrictEqual(ids(find("routes missing")), []);
assert.deepStrictEqual(ids(find("new routes announced")), ["recent", "older"]);
assert.strictEqual(find("  華航  ", "zh").highlightQuery, "華航");
for (const query of ["", "   ", "!!!", "。？！", "✈️"]) {
  assert.deepStrictEqual(ids(find(query)), []);
}
assert.deepStrictEqual(ids(find("routes", "en", [])), []);
assert.strictEqual(JSON.stringify(articles), originalArticles);

// Exercise the browser entry point: punctuation must never load/render all news.
const vm = require("vm");
const fs = require("fs");
const source = fs.readFileSync(require.resolve("../static/search.js"), "utf8");
for (const query of ["!!!", "。？！", "✈️", "  ---  "]) {
  const input = { value: "", addEventListener() {} };
  const status = { textContent: "" };
  let cleared = false;
  const nodes = {
    "news-search-app": { dataset: { emptyTemplate: 'No results: {query}' } },
    "news-search-form": { addEventListener() {} },
    "news-search-input": input,
    "news-search-status": status,
    "news-search-results": { replaceChildren() { cleared = true; } }
  };
  vm.runInNewContext(source, {
    document: { getElementById(id) { return nodes[id]; } },
    window: {
      location: { href: "https://example.com/search/?q=" + encodeURIComponent(query) },
      history: { replaceState() {} }
    },
    URL,
    fetch() { throw new Error("Punctuation search must not fetch the index"); }
  });
  assert.strictEqual(status.textContent, "No results: " + query.trim());
  assert.strictEqual(cleared, true);
}

console.log("test_search_client: OK");
