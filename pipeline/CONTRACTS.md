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
      "cat": "safety",                     // safety | reg | biz | ops
      "primarySource": "Reuters",
      "image": null,                       // og:image URL or null
      "zh": {"title": "...", "summary": "<=80字", "body": ["段落1", "段落2"]},
      "en": {"title": "...", "summary": "...", "body": ["para1", "para2"]},
      "sources": [{"name": "FAA — Statement", "url": "https://..."}]  // >=1, REQUIRED
    }
  ]
}
```

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
