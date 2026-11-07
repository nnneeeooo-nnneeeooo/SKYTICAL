"""One-off audit and conservative, real-photo recovery for SKYTICAL's full archive.

Only uses existing inspected photo metadata or verified real Commons photographs.
Never invent photos, use logos/illustrations, or claim historical photos show a news event.
Unmatched news remains explicitly listed for human review.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from common import load_json, save_json
import images
from image_selection import rejection_reason, prepare_image

ARTICLES = ROOT / "data/articles"
REPORT = ROOT / "data/archive-photo-backfill-report.json"
CUTOFF = "2026-07-01"
BAD_PHOTO = re.compile(
    r"illustrat|render|concept|graphic|diagram|drawing|sketch|mock.?up|"
    r"design|artwork|poster|logo|insignia|emblem|flag|map|infographic|"
    r"AI.?generat|generated.?image|screenshot|simulation|composite|"
    r"digitally.?creat|artist.?impress|CGI|symbol|model.?kit",
    re.I,
)
GOOD_EXT = re.compile(r"\.(?:jpe?g|png|webp)(?:\?|$)", re.I)
DISPLAY_BAN = re.compile(r"generated|stockphoto|shutterstock|istock|alamy|depositphotos", re.I)

# Previously reviewed Commons originals: genuine photographs, not synthetic art.
# Each subject is explicitly restricted to the article's named organization,
# operator, aircraft or military type, and disclosed as a historical file photo.
KNOWN = {
    "taiwan-mnd": {
        "url": "https://commons.wikimedia.org/wiki/Special:FilePath/PLAAF_J-16_2024-11-30.jpg?width=1280",
        "link": "https://commons.wikimedia.org/wiki/File:PLAAF_J-16_2024-11-30.jpg",
        "credit": "Japan Ministry of Defense / JASDF",
        "license": "CC BY 4.0 (Government of Japan Standard Terms of Use 2.0)",
        "subject": "中國人民解放軍空軍 J-16 戰機",
        "description": "日本航空自衛隊於2024年拍攝的 J-16 實機照片；非本次新聞事件現場。",
        "kind": "file_photo",
    },
    "faa": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/80/Federal_Aviation_Administration_headquarters_and_sign.jpg/1280px-Federal_Aviation_Administration_headquarters_and_sign.jpg",
        "link": "https://commons.wikimedia.org/w/index.php?curid=56695857",
        "credit": "Runner1928",
        "license": "CC BY-SA 4.0",
        "subject": "美國聯邦航空總署 FAA 總部",
        "description": "美國 FAA 總部真實建築資料照，非本次事件現場。",
        "kind": "file_photo",
    },
    "easa": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/EASA_Headquarters_-_EASA_Direktion.jpg/1280px-EASA_Headquarters_-_EASA_Direktion.jpg",
        "link": "https://commons.wikimedia.org/w/index.php?curid=49320120",
        "credit": "Wikimedia Commons (see file page)",
        "license": "CC BY-SA 4.0",
        "subject": "歐盟航空安全局 EASA 總部",
        "description": "EASA 總部真實建築資料照，非本次事件現場。",
        "kind": "file_photo",
    },
}
# Explicit and disjoint lead-subject gates to avoid finding a coincidental
# keyword buried in an unrelated article about a different operator.
MND_RE = re.compile(r"共機|共艦|台海|臺海|解放軍|擾台|擾臺|"
                    r"\bPLA\b|PLAAF|Chinese military aircraft|Taiwan Strait|"
                    r"Chinese warships|中國軍機", re.I)
FAA_RE = re.compile(r"\bFAA\b|Federal Aviation Administration|美國聯邦航空總署", re.I)
EASA_RE = re.compile(r"\bEASA\b|European Union Aviation Safety Agency|歐盟航空安全局", re.I)

def headline(article):
    return " ".join(str((article.get(k) or {}).get("title") or "") for k in ("zh", "en"))

def usable_existing(article):
    raw = article.get("image")
    if isinstance(raw, dict) and raw.get("url"):
        # Do not overwrite prior human curation, even when the selection filter
        # cannot fully evaluate its free-form attribution.
        if raw.get("curated") is True or raw.get("provider") == "manual":
            return True
    try:
        return bool(prepare_image(article, raw) and not rejection_reason(article, raw))
    except Exception:
        return False

def is_photo(photo):
    if not isinstance(photo, dict) or not photo.get("url") or not photo.get("link"):
        return False
    url = photo["url"]
    if ".svg" in url.lower() or ".svg" in str(photo.get("link")).lower():
        return False
    if not GOOD_EXT.search(urlparse(url).path):
        return False
    if photo.get("kind") in ("illustration",):
        return False
    title = " ".join(str(photo.get(k) or "") for k in ("subject", "description", "sourceCaption"))
    if BAD_PHOTO.search(title) or DISPLAY_BAN.search(url):
        return False
    provider = str(photo.get("provider") or "")
    # Reused syndicated editorial images without a reuse license are omitted.
    if provider != "Wikimedia Commons":
        return False
    lic = str(photo.get("license") or "")
    if not re.search(r"CC BY|CC0|public domain|PD-", lic, re.I):
        return False
    return True

def approved_image(article, candidate, reason, *, curated=True):
    pic = copy.deepcopy(candidate)
    pic["provider"] = str(pic.get("provider") or "Wikimedia Commons")
    pic["kind"] = "source_image" if article.get("articleFormat") == "roundup" else "file_photo"
    pic["matched"] = "archive:verified-real-photo:" + reason
    pic["curated"] = curated
    pic["description"] = (
        str(pic.get("description") or pic.get("subject") or "航空新聞資料照")[:220]
        + "（歷史資料照片，並非此篇新聞事件當日拍攝。）"
    )
    pic["sourceCaption"] = (
        str(pic.get("subject") or "相關實體") + "真實照片；非該事件現場。")
    return pic

def manual_known(article):
    t = headline(article)
    op = " ".join(str(v) for v in (article.get("entities") or {}).get("organizations") or [])
    # Military image only if military subject is actually front and center.
    if MND_RE.search(t) and re.search(r"台|臺|Taiwan|PLA|Chinese|共機|共艦|擾", t, re.I):
        return KNOWN["taiwan-mnd"], "taiwan-mnd"
    if FAA_RE.search(t):
        return KNOWN["faa"], "faa-headquarters"
    if EASA_RE.search(t):
        return KNOWN["easa"], "easa-headquarters"
    return None, None

def safe_cache_photo(article, cached):
    if not is_photo(cached):
        return False
    # Never allow a branded aircraft of the wrong carrier, registration or role.
    try:
        return rejection_reason(article, cached) is None
    except Exception:
        return False

def bank_rank(article, photo):
    title = headline(article)
    imgtext = " ".join(str(photo.get(k) or "") for k in ("subject", "description", "matched"))
    carrier = images.find_airline(article)
    model = images.find_aircraft_type(article)
    airport = images.find_airport(article)
    org = images.find_org(article)
    if carrier:
        aliases = images._airline_aliases(carrier)
        if not any(a and len(a) >= 4 and re.search(r"(?<![A-Za-z0-9])"+re.escape(a)+r"(?![A-Za-z0-9])",imgtext,re.I) for a in aliases):
            return None
        if model and not images.model_matches(model, imgtext):
            return None
        return 100 + (20 if model else 0)
    if model:
        if not images.model_matches(model, imgtext):
            return None
        if re.search(r"air force|空軍|軍|軍方|military",title,re.I) and not re.search(r"air force|空軍|military|army|navy",imgtext,re.I):
            return None
        return 75
    if airport:
        query,tokens,subject = airport
        if not all(x.lower() in imgtext.lower() for x in tokens if x and len(x)>=4):
            return None
        return 70
    if org:
        query,tokens,subject = org
        if not any(x.lower() in imgtext.lower() for x in tokens if x and len(x)>=4):
            return None
        return 55
    return None

def main():
    rows = []
    batches = []
    photo_bank = []
    stats = Counter()
    for path in sorted(ARTICLES.glob("*.json")):
        data = load_json(path, {})
        if not isinstance(data, dict):
            continue
        aa = data.get("articles")
        if not isinstance(aa, list):
            continue
        batches.append((path,data))
        for a in aa:
            if not isinstance(a,dict) or a.get("archived") is True:
                continue
            if not isinstance(a.get("id"),str) or not a.get("publishedUtc"):
                continue
            if str(a.get("publishedUtc"))[:10] < CUTOFF:
                continue
            rows.append((path,a))
            stats["articles"] += 1
            if usable_existing(a):
                stats["already_photographed"] += 1
                if is_photo(a.get("image")):
                    photo_bank.append(a["image"])
            else:
                stats["initially_unillustrated"] += 1
    cache = load_json(ROOT/"data/images.json", {})
    for ent in (cache.get("articles") or {}).values():
        if ent.get("status")=="matched" and is_photo(ent.get("image")):
            photo_bank.append(ent["image"])
    # Dedupe all previously reviewed, actual CC-licensed photos.
    uniq={}
    for photo in photo_bank:
        uniq.setdefault(str(photo["link"]).split("?")[0],photo)
    bank=list(uniq.values())
    stats["curated_bank_photo_count"]=len(bank)
    changed_paths=set()
    done=[]
    pending=[]
    start=time.monotonic()
    for path,article in rows:
        if usable_existing(article):
            continue
        art_id=article["id"]
        known, known_key=manual_known(article)
        if known:
            p=copy.deepcopy(known)
            p["provider"]="Wikimedia Commons"
            article["image"]=approved_image(article,p,known_key)
            changed_paths.add(path)
            done.append({"id":art_id,"method":known_key,"photo":p["link"]})
            stats["assigned_known"]+=1
            continue
        scored=[]
        for photo in bank:
            rank=bank_rank(article,photo)
            if rank is None:
                continue
            if safe_cache_photo(article,photo):
                scored.append((rank,photo))
        if scored:
            _,photo=max(scored,key=lambda x:x[0])
            article["image"]=approved_image(article,photo,"validated-cache")
            changed_paths.add(path)
            done.append({"id":art_id,"method":"verified-bank","photo":photo["link"]})
            stats["assigned_bank"]+=1
            continue
        pending.append((path,article))
    # Query Commons only if relevant subject is known and search evidence matches.
    # Limit network duration and don't issue speculative general aviation searches.
    searched={}
    for path,article in pending:
        art_id=article["id"]
        if time.monotonic()-start > 720:
            stats["network_time_budget_reached"]+=1
            break
        carrier=images.find_airline(article)
        model=images.find_aircraft_type(article)
        airport=images.find_airport(article)
        org=images.find_org(article)
        query=None
        tokens=[]
        kw={}
        if carrier and model:
            query=f"{carrier} {model}"
            tokens=[carrier]
            kw={"required_model":model,"require_all":True,"prefer_landscape":True}
        elif carrier:
            query=f"{carrier} aircraft"
            tokens=[carrier]
            kw={"require_all":True,"prefer_landscape":True}
        elif model:
            query=f"{model} aircraft"
            kw={"required_model":model,"prefer_landscape":True}
        elif airport:
            query,tokens,_=airport
            kw={"require_all":True,"prefer_landscape":True}
        elif org:
            query,tokens,_=org
            kw={"prefer_landscape":True}
        if not query:
            continue
        cachekey=(query,tuple(tokens),tuple(sorted(kw.items())))
        if cachekey not in searched:
            try:
                photo=images.lookup_commons(query,tokens,**kw)
                searched[cachekey]=photo if is_photo(photo) else None
            except Exception:
                searched[cachekey]=None
            time.sleep(0.10)
        photo=searched[cachekey]
        if photo and safe_cache_photo(article,photo):
            article["image"]=approved_image(article,photo,"commons-verified")
            changed_paths.add(path)
            done.append({"id":art_id,"method":"commons","photo":photo["link"]})
            stats["assigned_commons"]+=1
    unresolved=[]
    for path,article in rows:
        if usable_existing(article):
            continue
        unresolved.append({
            "id":article["id"],
            "title":str((article.get("zh") or {}).get("title") or "")[:180],
            "file":str(path.relative_to(ROOT)),
            "publishedUtc":article.get("publishedUtc"),
            "airline":images.find_airline(article),
            "aircraft":images.find_aircraft_type(article),
            "organization":images.find_org(article)[0] if images.find_org(article) else None,
        })
    stats["unresolved"]=len(unresolved)
    stats["assigned_total"]=len(done)
    stats["changed_json_files"]=len(changed_paths)
    report={
        "generatedUtc":datetime.now(timezone.utc).isoformat(),
        "criteria":"Only real photographs with verified original-source metadata. No generated, diagrammatic, or speculative images.",
        "stats":dict(stats),
        "changes":done,
        "unresolved":unresolved,
    }
    for path,data in batches:
        if path in changed_paths:
            save_json(path,data)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ARCHIVE_PHOTO_AUDIT "+json.dumps(stats,ensure_ascii=False))
    for row in unresolved[:25]:
        print("PHOTO_UNRESOLVED "+row["id"]+" "+row["title"])

if __name__=="__main__":
    main()
