# SKYTICAL pipeline data contracts

Every stage reads/writes JSON under `data/`. All timestamps are UTC in the
form `2026-07-26T05:47Z` (see `common.iso_minute`). All files are written with
`common.save_json` (UTF-8, 2-space indent, trailing newline).

Stage order (each is a standalone script, run from repo root):

```
python pipeline/fetch.py    # sources -> data/raw/*.json + data/sources.json
python pipeline/dedupe.py   # data/raw -> data/pending.json (new/updated story groups)
python pipeline/write.py    # data/pending.json -> data/articles/*.json, flashes.json,
                            #                      incidents.json, data/seen.json
python pipeline/build.py    # data/* -> site/ (static HTML)
```

A stage must NEVER crash the pipeline because one input is missing or one
source failed: degrade gracefully, log to stdout, exit 0. Non-zero exit is
reserved for programming errors.

`config/changelog.json` is a checked-in, bilingual history of meaningful
site changes. It is curated from the GitHub `main` history and deliberately
omits automated `hourly update`, briefing and flight-state data commits.
Every historical row carries a full 40-character commit SHA; build.py derives
the public GitHub URL from that validated SHA rather than accepting arbitrary
links from the file. The one current changelog-page row may use `null` until
it has a stable historical commit.

## data/raw/<source_key>.json  (written by fetch.py, read by dedupe.py)

```jsonc
{
  "source": "faa",                  // key into common.SOURCES
  "fetchedUtc": "2026-07-26T05:02Z",
  "ok": true,                       // false when the fetch failed
  "error": null,                    // string when ok=false
  // On failure fetch.py CARRIES the previous snapshot's items (and stats)
  // forward, so ok=false files may still hold usable items; dedupe.py reads
  // them regardless of ok (staleness is bounded by its 48h age filter).
  // For items without a source-provided date, publishedUtc keeps the stamp
  // from the FIRST fetch that saw the URL (stable across refetches).
  "items": [
    {
      "title": "FAA Statement on ...",     // plain text, no HTML
      "url": "https://www.faa.gov/...",    // direct original link (unresolved Google News links are dropped)
      "publishedUtc": "2026-07-26T04:41Z", // best-effort; fetchedUtc when unknown
      "summary": "First ~500 chars of plain-text summary/description",
      "image": null                        // og:image / enclosure URL when cheaply available
    }
  ]
}
```

## data/sources.json  (written by fetch.py, read by build.py)

Array, one entry per key in `common.SOURCES`, in registry order:

```jsonc
[
  {
    "key": "faa",
    "name": "FAA",
    "kind": "official",           // official | industry | media | data
    "fmt": "RSS",
    "url": "https://www.faa.gov",
    "cover": {"zh": "...", "en": "..."},
    "public": true,                      // false = editorial input only; hidden from public source-status UI
    "lastFetchUtc": "2026-07-26T05:02Z",  // last SUCCESSFUL fetch (persisted across runs)
    "ok": true
  }
]
```

Aircraft/engine manufacturer feeds are maintained in
`config/manufacturer_sources.json` and merged into `common.SOURCES` at
startup.  Their official social-account URLs are metadata only and are never
fetched or passed to the model as evidence.  A hidden (`public=false`) feed
still produces `data/raw/<key>.json` and can supply a story group to
`write.py`; only its source-status row is suppressed.

## data/pending.json  (written by dedupe.py, read + consumed by write.py)

Only stories that are NEW this run (not in data/seen.json). Cross-source
coverage of one event is merged into a single `event` group. Separate,
title-backed The Aviation Herald occurrence notices may be collected into an
explicit `safety_roundup` group; its items remain independent events and must
never be presented as one occurrence.

```jsonc
{
  "generatedUtc": "2026-07-26T05:03Z",
  "groups": [
    {
      "id": "g-20260726-0503-1",
      "groupKind": "event",               // event | safety_roundup
      "independentEvents": false,          // true only for safety_roundup
      "primarySource": "Reuters",          // display name of best source in group
      "items": [ /* raw items as above, each with extra "source" (display name) and "sourceKey" */ ]
    }
  ]
}
```

## data/seen.json  (written by write.py ONLY, read by dedupe.py)

Dedupe memory. `urls` maps normalized URL -> ISO date first seen. Only
write.py updates this file, and only for groups it actually published — so if
write.py is skipped (no API key) or fails on a group, the story remains
"unseen" and is re-emitted by dedupe.py on the next run. Entries older than
21 days are pruned by write.py.

```jsonc
{ "urls": {"https://www.faa.gov/newsroom/x": "2026-07-26T05:03Z"},
  "titles": [["faa statement denver 737", "2026-07-26T05:03Z"]] }
```

## data/articles/<UTC-hour>.json  e.g. data/articles/2026-07-26T05.json
(written by write.py, read by build.py; one batch file per pipeline hour,
absent when nothing new that hour)

```jsonc
{
  "articles": [
    {
      "id": "a-20260726-0547-denver737",   // a-YYYYMMDD-HHMM-<slug>
      "publishedUtc": "2026-07-26T05:47Z",
      "cat": "safety",                     // safety | reg | biz | ops | mil
      "primarySource": "Reuters",
      "articleFormat": "full",             // full | brief | roundup
      "image": null,                       // og:image URL or null
      "archived": false,                   // OPTIONAL true = retained in data,
                                            // excluded from every public page
      "archivedUtc": "2026-07-27T08:56Z", // OPTIONAL audit timestamp
      "archiveReason": "...",              // OPTIONAL audit reason
      "zh": {"title": "...", "summary": "...", "body": ["至少4段；合計>=500實質字元"]},
      "en": {"title": "...", "summary": "...", "body": ["at least 4 paragraphs; >=250 words"]},
      "sources": [{"name": "FAA — Statement", "url": "https://..."}],  // >=1, REQUIRED
      "sourcePublishedUtc": "2026-07-23T04:00Z", // OPTIONAL newest source-provided
                                            // publish time (never an inferred
                                            // stamp); the site displays this,
                                            // publishedUtc orders the archive
      "writer": "gemini:gemini-2.5-flash",  // OPTIONAL provenance "provider:model";
                                            // absent on pre-multi-provider articles
      "facts": [                            // OPTIONAL machine-verified evidence:
        {"factId": "F1", "claim": "...",    // each quote + URL is code-verified
         "sourceQuote": "...",
         "sourceUrl": "https://...",
         "evidenceScope": "source",         // source | archive
         "archiveEventId": null,
         "archiveContext": false}
      ],
      "archiveContext": {                   // OPTIONAL; only when archive facts used
        "archive_context_version": 1,
        "context_id": "deterministic-audit-id",
        "selected_events": [ /* max 3; facts only, no archive full text */ ]
      },
      "riskFlags": ["investigation"],       // OPTIONAL editorial risk flags
                                            // (subset of write.RISK_FLAGS; non-empty
                                            // only on human-approved articles)
      "eventStatus": "under_investigation", // OPTIONAL write.EVENT_STATUSES value
      "entities": {"airlines": ["..."]}     // OPTIONAL source-grounded entities
                                            // (subset of write.ENTITY_KEYS arrays)
    }
  ]
}
```

## data/review.json and data/review-archive.json

The former human-review mechanism is retired. `data/review.json` is read only
as a one-time migration source: rows no older than 14 days are re-checked by
the current deterministic source, quote, binding, glossary and fabrication
gates. Passing rows publish; failing or expired rows do not. Every row and its
`retirementResult`, reason and optional article ID is preserved in
`data/review-archive.json`, then `data/review.json` is cleared.

`DRAFT_SCHEMA.status` accepts `publish`, `publish_brief` and `reject`.
`manual_review` remains parser-compatible only for the one-time legacy
migration. Published article files do not persist the editorial status; they
persist `articleFormat` (`full`, `brief` or `roundup`) so old readers remain
compatible. A roundup must label itself as a collection of independent events,
use one numbered paragraph per source item, expand known ICAO aircraft type
codes on first mention, add configured country context to unfamiliar locations,
and avoid implying a causal or operational link. It
uses the neutral site fallback instead of selecting one event's image and does
not create a single `data/incidents.json` row for the whole collection.
Old article facts without the new evidence metadata remain readable. For
archive retrieval, an old fact is eligible only when it already has
`sourceUrl` or its article has exactly one unambiguous source.

## data/flightwatch/  (written by flightwatch.py; queue.json consumed by write.py)

Rare-aircraft monitor state, committed only when changed:

- `state.json`    per-aircraft/airport tracks, pruned to 60 min - NO
                  sensitive aircraft are ever tracked, positions are
                  rounded and never published
- `history.json`  arrival statistics for rarity scoring (operator/type/
                  registration windows; firstRunUtc drives bootstrap mode)
- `events.json`   event registry keyed by stable id
                  fw-sha256(hex|airport|arrival|date)[:16] - the duplicate
                  gate across 5-minute reruns
- `queue.json`    confirmed rare-arrival candidates awaiting the hourly
                  news stage; entries hold identities/times/counts ONLY
                  (never live coordinates). write.py drafts them with
                  prompts/rare-aircraft-news-zh.txt and publishes only after
                  deterministic source and evidence checks pass.

## data/flashes.json  (written by write.py, read by build.py)

Most recent first, max 10 kept:

```jsonc
[ {"timeUtc": "2026-07-26T05:47Z", "hot": true, "pinned": true,
   "zh": "...", "en": "...",
   "articleId": "a-20260726-0547-denver737"} ]
```

## data/incidents.json  (written by write.py, read by build.py)

Most recent first, max 60 kept. Only safety-category events that describe an
actual occurrence (ICAO Annex 13):

```jsonc
[
  {
    "date": "2026-07-26",
    "sev": "ser",                          // acc | ser | inc
    "aircraft": "B737-8",
    "operator": "United",                  // or {"zh": "...", "en": "..."}
    "phase": {"zh": "降落", "en": "Landing"},
    "location": {"zh": "丹佛", "en": "Denver"},
    "desc": {"zh": "...", "en": "..."},
    "status": "open",                      // open | closed | prelim
    "sources": ["FAA", "NTSB"],
    "articleId": "a-20260726-0547-denver737"   // may be null
  }
]
```

## data/stats.json  (written by write.py — optional FlightAware AeroAPI part; read by build.py)

The site-derived fields are always written. FlightAware values are optional;
`flightAwareStatus` distinguishes an unconfigured source from a temporary
failure instead of presenting either as a real zero:

```jsonc
{
  "updatedUtc": "2026-07-26T05:47Z",
  "seriousThisWeek": 3,        // write.py derives from incidents.json
  "flightAwareStatus": "ok",  // ok | unconfigured | unavailable
  "flightAwareUpdatedUtc": "2026-07-26T05:46Z",
  "delaysWorldwide": 4201,
  "cancellationsWorldwide": 318
}
```

The FlightAware disruption endpoint does not provide a denominator for a
worldwide delay rate or an active-NOTAM total. Neither value may be inferred
from this response.

## site/  (written by build.py)

```
site/
├─ index.html                  zh home        /
├─ en/index.html               en home        /en/
├─ news/index.html             zh news index  /news/
├─ en/news/index.html          en news index  /en/news/
├─ news/<id>/index.html        zh article     /news/<id>/
├─ en/news/<id>/index.html     en article
├─ feed.xml                    zh RSS feed    /feed.xml
├─ en/feed.xml                 en RSS feed    /en/feed.xml
├─ incidents/index.html        + en/incidents/
├─ sources/index.html          + en/sources/
├─ about/index.html            + en/about/
├─ changelog/index.html        + en/changelog/
├─ assets/modernist.css        copied from static/
├─ assets/site.css
├─ assets/app.js
├─ 404.html
└─ .nojekyll
```

All internal links are prefixed with `common.BASE_PATH` (empty by default for
the `https://skytical.tech` custom-domain root).
Every page rendered through `base.html` includes a language-correct footer
button linking to its changelog page.

## data/briefings/  (written by briefing.py, read by build.py)

```
data/briefings/
├─ index.json            {"briefings": [{briefing_id, date, edition,
│                          status published|partial|failed, cutoff_time,
│                          generated_at, item_count}]}
├─ <date>-<edition>.json one briefing per edition (schema in briefing.py:
│                          fixed half-open Asia/Taipei window, sections,
│                          checked_sources, warnings, generation_mode)
└─ event_index.json      cross-edition dedup: {"events": {event_id:
                           {fingerprint, urls, fact_keys, updates, ...}}}
```

Briefings select only from data/articles/ (already verified/published);
failed runs never modify briefing files and never downgrade a
published/partial index row. build.py renders /briefings/ and
/briefings/<id>/ for published|partial only.
Briefing item source links must be direct original `http(s)` URLs; unsafe
schemes and Google News aggregator links are discovery-only and are dropped
before persistence or reader-facing rendering.

## data/images.json + article "image"  (written by images.py)

images.py (after write.py) may set article.image =
{url, link, credit, license, provider,
 kind airframe_photo|file_photo, matched} — an external embed from
Planespotters.net (same airframe, by registration) or Wikimedia Commons
(free-licensed file photo), never a claimed event photo. images.json
caches per-article match/none results. build.normalize_image() is the
only reader; templates always show kind + credit + license + backlink.
The resolver revalidates only the current seven-day article window, prefers
the headline's verified primary carrier, gives airport-operation headlines
priority over generic aircraft matches, and rejects logos, diagrams, interiors,
civic buildings, wreckage and other deterministic false matches. If no
confident replacement exists, the article keeps the neutral site fallback.

`pipeline/image_qa.py` also maintains `data/image-qa.json`, a seven-day
maintainer queue of current image provenance for manual visual inspection.
Its `status` may be kept as `pending`, `approved` or `rejected` by the
maintainer; the queue is not copied to `site/`.

## News scope and search index

Broad feeds require both a keyword hit and a transport subject in the
headline. A carrier mentioned only in a summary cannot make an unrelated
headline enter the editorial queue. During a build, stored articles with a
headline outside the same subject gate are omitted from public pages and
orphaned ticker entries are omitted as well; source JSON remains preserved.

`site/search-index.json` keeps titles, summaries and display metadata in their
structured fields and stores body/source text plus matched aliases in its
search field. The search page loads the index only when a query is made, so
visiting the page without searching does not download the full index.

## data/search-prompts.json  (written by search_prompts.py, read by build.py)

One daily set of six bilingual search-box suggestions. `targetDateTpe` prevents
more than one generation per Taipei calendar day; `generationMode` is `llm`
only after every suggestion passes article-ID, length, safety, uniqueness and
title-anchor validation. `sourceArticleIds` records the published articles used.
When no provider is available or model output is invalid, deterministic prompts
are built from those article titles instead. No model reasoning is stored.

## data/usage.json  (written by usage.py, read by build.py)

Cumulative LLM API spend: per-model-label {calls, inputTokens,
outputTokens, unknownCalls} + rolling 120-day daily series. Providers
capture usage from each API response; write.py/briefing.py flush once
per run via usage.record_providers(). build.py renders it on a PRIVATE
dashboard at site/u/<AVWIRE_USAGE_TOKEN>/ (noindex, linked from
nowhere) only when that secret is set. Reference list prices live in
config/model_prices.json - theoretical value only; free-tier spend is 0.

`recentRuns` contains sanitized per-work execution diagnostics for hourly
articles, flightwatch events and optional model-assisted briefings. Each row
may contain provider attempts, stable failure classes, fallback order, actual
HTTP/JSON-repair call counts and precisely measured stage durations. It never
contains prompts, source/fulltext bodies, article bodies, headers, keys,
tokens or private dashboard URLs. `usage.record_run()` prunes rows older than
30 days (inclusive boundary) and caps the collection at 1,000 newest rows;
the private renderer validates and applies the same 30-day filter again.
The existing `daily` series remains independent at 120 days.
`nonApiReference` contains purpose-separated official API comparison rates
for work completed through ChatGPT Work/Codex rather than the site's API
pipeline. These rows never contribute calls, tokens, or dollars to the API
ledger totals.
`gptFamilyReference` contains the official standard API text-token rates for
the GPT-5 family. It is a read-only comparison catalogue on the same private
dashboard and likewise never contributes to the usage ledger or totals.

## config/codex_usage.json  (manually refreshed task snapshot)

Checked-in token totals exported from Codex task usage metadata for SKYTICAL
website development. It contains no conversation content, local paths, task
identifiers, credentials or private dashboard URL. `build.py` validates each
row, matches it to `gptFamilyReference`, and calculates a separate theoretical
API-equivalent cost. Cached input is a subset of input and reasoning output is
a subset of output, so neither is counted twice. This snapshot is displayed on
the private dashboard but never merged into `data/usage.json` or its totals.
