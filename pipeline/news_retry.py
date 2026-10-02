"""Persistent, source-keyed news retry budgets across hourly runs.

No prompts, generated copy or exception text are persisted. Exhausted rows
are the failure register; a genuinely new source URL reopens a story.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from common import DATA_DIR, iso_minute, load_json, norm_url, parse_iso, save_json

MAX_RETRIES_PER_RUN = 2
RETRY_HOURS = (2, 6, 24)
RETENTION_DAYS = 30


def source_urls(group):
    return sorted({norm_url(str(item["url"]))
                   for item in group.get("items", [])
                   if isinstance(item, dict) and item.get("url")})


class RetryLedger:
    def __init__(self, now):
        self.now = now
        self.path = DATA_DIR / "news-retry.json"
        payload = load_json(self.path, {})
        rows = payload.get("stories", {}) if isinstance(payload, dict) else {}
        self.rows = {}
        for key, row in rows.items() if isinstance(rows, dict) else []:
            if not isinstance(row, dict) or not isinstance(row.get("sourceUrls"), list):
                continue
            try:
                updated = parse_iso(str(row.get("updatedUtc")))
                for field in ("contentFailures", "serviceFailures"):
                    if not isinstance(row.get(field), int) or row[field] < 0:
                        raise ValueError("invalid failure counter")
                if row.get("nextRetryUtc"):
                    parse_iso(str(row["nextRetryUtc"]))
            except (ValueError, TypeError):
                continue
            if updated >= now - timedelta(days=RETENTION_DAYS):
                self.rows[key] = row

    def save(self):
        save_json(self.path, {"schemaVersion": 1, "stories": self.rows})

    def state(self, group):
        urls = set(source_urls(group))
        matches = [(key, row) for key, row in self.rows.items()
                   if urls.intersection(row["sourceUrls"])]
        if not matches:
            return None, None
        # Joining previously separate groups cannot bypass either retry cap.
        key, row = max(matches, key=lambda entry: (
            entry[1].get("status") == "exhausted", entry[1]["contentFailures"]))
        known = set().union(*(set(r["sourceUrls"]) for _, r in matches))
        if urls - known:
            history = list(row.get("history") or [])[-4:]
            history.append({k: row.get(k) for k in (
                "status", "contentFailures", "serviceFailures", "updatedUtc")})
            row = {"sourceUrls": sorted(known | urls), "contentFailures": 0,
                   "serviceFailures": 0, "status": "ready", "history": history,
                   "updatedUtc": iso_minute(self.now), "nextRetryUtc": None}
            for old_key, _ in matches:
                self.rows.pop(old_key, None)
            self.rows[key] = row
        return key, row

    def plan(self, groups, limit):
        fresh, retries, deferred = [], [], []
        for group in groups:
            _, row = self.state(group)
            if row is None or not (row["contentFailures"] or row["serviceFailures"]):
                fresh.append(group)
            elif row.get("status") == "exhausted" or (
                    row.get("nextRetryUtc") and
                    parse_iso(row["nextRetryUtc"]) > self.now):
                deferred.append(group)
            else:
                retries.append(group)
        retry_count = min(MAX_RETRIES_PER_RUN, len(retries), limit)
        chosen = fresh[:limit - retry_count] + retries[:retry_count]
        # Fill unused capacity with fresh news, never extra old retries.
        deferred += fresh[limit - retry_count:] + retries[retry_count:]
        return chosen, deferred

    def exhausted(self, group):
        _, row = self.state(group)
        return bool(row and row.get("status") == "exhausted")

    def failure(self, group, *, content):
        key, row = self.state(group)
        urls = source_urls(group)
        if not urls:
            return  # a title alone is not a stable retry identity
        if row is None:
            key = hashlib.sha256(urls[0].encode()).hexdigest()[:24]
            row = {"sourceUrls": urls, "contentFailures": 0,
                   "serviceFailures": 0, "history": []}
        row["sourceUrls"] = sorted(set(row["sourceUrls"]) | set(urls))
        field = "contentFailures" if content else "serviceFailures"
        row[field] += 1
        row["updatedUtc"] = iso_minute(self.now)
        row["failureClass"] = "content_validation" if content else "provider_failure"
        row["status"] = "exhausted" if row["contentFailures"] > len(RETRY_HOURS) else "waiting"
        row["nextRetryUtc"] = (None if row["status"] == "exhausted" else
            iso_minute(self.now + timedelta(hours=RETRY_HOURS[min(row[field] - 1, 2)])))
        row["title"] = str((group.get("items") or [{}])[0].get("title") or "")[:300]
        self.rows[key] = row

    def complete(self, group):
        urls = set(source_urls(group))
        for key, row in list(self.rows.items()):
            if urls.intersection(row["sourceUrls"]):
                self.rows.pop(key)
