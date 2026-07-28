# AVWIRE pipeline data contracts

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
      "url": "https://www.faa.gov/...",    // original link (Google News links resolved when possible)
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
    "lastFetchUtc": "2026-07-26T05:02Z",  // last SUCCESSFUL fetch (persisted across runs)
    "ok": true
  }
]
```

## data/pending.json  (written by dedupe.py, read + consumed by write.py)

Only stories that are NEW this run (not in data/seen.json). Cross-source
coverage of one event is merged into a single group.

```jsonc
{
  "generatedUtc": "2026-07-26T05:03Z",
  "groups": [
    {
      "id": "g-20260726-0503-1",
      "primarySource": "Reuters",          // display name of best source in group
      "items": [ /* raw items as above, each with extra "source" (display name) and "sourceKey" */ ]
    }
  ]
}
```

## data/seen.json  (written by write.py ONLY, read by dedupe.py)

Dedupe memory. `urls` maps normalized URL -> ISO date first consumed.
write.py records published stories, manual-review stories and final editorial
rejects. Provider failures and `deferred_thin` stories remain unseen and are
re-emitted by dedupe.py on the next run. Entries older than 21 days are
pruned by write.py.

```jsonc
{ "urls": {"https://www.faa.gov/newsroom/x": "2026-07-26T05:03Z"},
  "titles": [["faa statement denver 737", "2026-07-26T05:03Z"]] }
```

## data/deferred.json  (written by write.py)

Bounded retry ledger for a source that currently has only a headline, or for
a concise source rejected solely because it cannot support full length.
Entries have stable URL/title-derived keys and the status `deferred_thin`.
They are not added to `seen.json`; the source may be retried for 24 hours so a
later excerpt, full text or verified companion source can make it publishable.
After 24 hours the group is consumed as a final reject, preventing an
indefinite hourly loop.

```jsonc
{
  "version": 1,
  "items": {
    "<stable-key>": {
      "status": "deferred_thin",
      "firstDeferredUtc": "2026-07-28T01:00Z",
      "lastDeferredUtc": "2026-07-28T02:00Z",
      "retryUntilUtc": "2026-07-29T01:00Z",
      "materialFingerprint": "<sha256>",
      "reason": "current source lacks enough quotable summary/full text"
    }
  }
}
```

An unchanged `materialFingerprint` suppresses repeated model calls. A changed
summary, full text, companion source or selected archive context changes the
fingerprint and permits a new drafting attempt within the retry window.

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
      "articleFormat": "full",             // full | brief
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

## data/review.json  (written AND consumed by write.py; hand-edited by a human)

Human-review queue. Drafts whose editorial status is "manual_review" (all
aviation safety events, plus other high-risk topics) are parked here instead
of publishing. A human sets `"approve": true` on GitHub; the next write.py
run publishes that entry exactly as drafted and removes it. Entries expire
unreviewed after 14 days; the queue keeps at most 40 rows, newest first.

```jsonc
[
  {
    "id": "g-20260726-0503-1",        // pending-group id
    "queuedUtc": "2026-07-27T09:03Z",
    "approve": false,                  // flip to true to publish next run
    "writer": "gemini:gemini-2.5-flash",
    "decisionReason": "航空安全事件，調查進行中",
    "riskFlags": ["accident_or_serious_incident"],
    "facts": [ {"factId": "F1", "claim": "...", "sourceQuote": "...",
                "sourceUrl": "https://...", "evidenceScope": "source",
                "archiveEventId": null, "archiveContext": false} ],
    "draft": { /* full DRAFT_SCHEMA object */ },
    "group": { /* pending group snapshot (sources for the article) */ }
  }
]
```

Queued groups are recorded in seen.json immediately (they must not re-emit
from dedupe while awaiting review).

`DRAFT_SCHEMA.status` accepts `publish`, `publish_brief`, `manual_review` and
`reject`. Published article files do not persist the editorial status; they
persist `articleFormat` (`full` or `brief`) so old readers remain compatible.
Old article facts without the new evidence metadata remain readable. For
archive retrieval, an old fact is eligible only when it already has
`sourceUrl` or its article has exactly one unambiguous source.

Review entries created from rare-aircraft events additionally carry a
`"flight"` object (eventId / airport / crossCheck / rarityScore /
bootstrap); their `"group"` is a pseudo-group whose items are the ADS-B
attribution links, so approval publishes with proper source credits.

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
                  prompts/rare-aircraft-news-zh.txt and ALWAYS forces
                  status=manual_review into data/review.json.

## data/flashes.json  (written by write.py, read by build.py)

Most recent first, max 10 kept:

```jsonc
[ {"timeUtc": "2026-07-26T05:47Z", "hot": true, "zh": "...", "en": "...",
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

All fields optional; build.py renders "—" for missing numbers and hides
sections whose arrays are missing/empty:

```jsonc
{
  "updatedUtc": "2026-07-26T05:47Z",
  "flightsTracked": 18742,
  "delayRate": 22.4,
  "seriousThisWeek": 3,        // write.py derives from incidents.json
  "notams": 1208
}
```

## site/  (written by build.py)

```
site/
├─ index.html                  zh home        /
├─ en/index.html               en home        /en/
├─ news/<id>/index.html        zh article     /news/<id>/
├─ en/news/<id>/index.html     en article
├─ incidents/index.html        + en/incidents/
├─ sources/index.html          + en/sources/
├─ about/index.html            + en/about/
├─ assets/modernist.css        copied from static/
├─ assets/site.css
├─ assets/app.js
├─ 404.html
└─ .nojekyll
```

All internal links are prefixed with `common.BASE_PATH` (default `/avwire`).

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

## data/images.json + article "image"  (written by images.py)

images.py (after write.py) may set article.image =
{url, link, credit, license, provider,
 kind airframe_photo|file_photo, matched} — an external embed from
Planespotters.net (same airframe, by registration) or Wikimedia Commons
(free-licensed file photo), never a claimed event photo. images.json
caches per-article match/none results. build.normalize_image() is the
only reader; templates always show kind + credit + license + backlink.

## data/usage.json  (written by usage.py, read by build.py)

Cumulative LLM API spend: per-model-label {calls, inputTokens,
outputTokens, unknownCalls} + rolling 120-day daily series. Providers
capture usage from each API response; write.py/briefing.py flush once
per run via usage.record_providers(). build.py renders it on a PRIVATE
dashboard at site/u/<AVWIRE_USAGE_TOKEN>/ (noindex, linked from
nowhere) only when that secret is set. Reference list prices live in
config/model_prices.json - theoretical value only; free-tier spend is 0.
