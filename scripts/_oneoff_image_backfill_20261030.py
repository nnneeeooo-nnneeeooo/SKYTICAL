#!/usr/bin/env python3
"""One-time, bounded, source-backed image backfill; remove before merging."""
import concurrent.futures
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import images
from image_selection import image_key

START = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 24, 0, tzinfo=timezone.utc)
OFFICIAL = {
    "mediarenditions.airbus.com": "Airbus",
    "mediaassets.airbus.com": "Airbus",
    "www.airbus.com": "Airbus",
    "www.eurocontrol.int": "EUROCONTROL",
    "images.nasa.gov": "NASA",
    "www.nasa.gov": "NASA",
    "boeing.mediaroom.com": "Boeing",
    "www.faa.gov": "FAA",
}
images.TIMEOUT = (4, 10)
def in_window(a):
    try:
        when = datetime.fromisoformat(str(a.get("publishedUtc") or "").replace("Z", "+00:00"))
        return START <= when.astimezone(timezone.utc) < END
    except (TypeError, ValueError):
        return False

def official_candidate(a):
    for c in a.get("sourceImageCandidates") or []:
        if not isinstance(c, dict):
            continue
        url = str(c.get("url") or "")
        name = OFFICIAL.get((urlsplit(url).hostname or "").lower())
        urls = {s.get("url") for s in a.get("sources") or [] if isinstance(s, dict)}
        if not name or not any(s.get("url") in urls for s in c.get("sources") or [] if isinstance(s, dict)):
            continue
        if not re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)|/resize\?", url, re.I):
            continue
        return {
            "url": url,
            "link": next((s["url"] for s in c["sources"] if s.get("url") in urls), ""),
            "credit": name,
            "license": None,
            "provider": name,
            "kind": "source_image",
            "matched": "editorial:official-source-image",
            "subject": (a.get("en") or {}).get("title") or (a.get("zh") or {}).get("title"),
            "description": "本篇所引官方新聞稿的原始配圖；圖片拍攝時間及是否為事件現場以原發布單位說明為準。",
            "curated": True,
        }
    return None


# A source page image is tied to the story's publisher and is preferable to
# an unrelated aircraft of a similar type. Include URL and original article
# citation so a reader can check the actual image attribution.
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
import html

def eligible_image_url(url):
    low = str(url or "").lower()
    if not low.startswith("https://"):
        return False
    if any(bad in low for bad in (
        "logo", "icon", "site-default", "default-share", "placeholder",
        "no-image", "blank.", "avatar", "pixel", "tracker", "1x1",
        "og-image-default", "social-share", "favicon",
    )):
        return False
    return True

def original_publisher_candidate(a):
    candidates = []
    known = {s.get("url") for s in a.get("sources") or [] if isinstance(s, dict)}
    for candidate in a.get("sourceImageCandidates") or []:
        if not isinstance(candidate, dict):
            continue
        url = str(candidate.get("url") or "")
        linked = next((s.get("url") for s in candidate.get("sources") or []
                       if isinstance(s, dict) and s.get("url") in known), None)
        if not linked or not eligible_image_url(url):
            continue
        hostname = urlsplit(url).hostname or ""
        if not (
            hostname.endswith("aerospaceglobalnews.com")
            or hostname.endswith("simpleflyingimages.com")
            or hostname.endswith("aerotime.aero")
        ):
            continue
        filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).lower()
        if any(x in filename for x in (
            "adobestock", "shutterstock", "gettyimages", "stock-photo", "stock_", "image-placeholder"
        )):
            continue
        # The RSS media URL is attached by the actual cited page, not a
        # keyword search. Keep attribution explicit and avoid calling it the
        # exact incident aircraft when the photo caption is absent.
        candidates.append({
            "url": url,
            "link": linked,
            "credit": "原始報導配圖（攝影及權利資訊請參閱來源頁）",
            "license": None,
            "provider": urlsplit(linked).hostname or "原始報導",
            "kind": "source_image",
            "matched": "editorial:source-article-media",
            "subject": (a.get("en") or {}).get("title") or (a.get("zh") or {}).get("title"),
            "description": "原始新聞來源隨文配圖，並非必然為所述事件現場或同一架航機。",
            "curated": True
        })
    return candidates[0] if candidates else None

def source_og_image(a):
    for source in (a.get("sources") or [])[:2]:
        url = str(source.get("url") or "")
        host = (urlsplit(url).hostname or "").lower()
        if not url.startswith("https://") or url.lower().endswith(".pdf"):
            continue
        if any(x in host for x in ("threads.com", "facebook.com", "instagram.com")):
            continue
        try:
            r = images.requests.get(url, headers=images.HEADERS,
                                    timeout=(4, 8))
            if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
                continue
            soup = BeautifulSoup(r.text[:400000], "html.parser")
            meta = None
            for prop in ("og:image", "twitter:image"):
                meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    break
            if not meta:
                continue
            imageurl = urljoin(r.url, html.unescape(str(meta.get("content") or "")))
            if not eligible_image_url(imageurl):
                continue
            if imageurl.lower().endswith(".svg"):
                continue
            altmeta = soup.find("meta", attrs={"property": "og:image:alt"}) or soup.find("meta", attrs={"name": "twitter:image:alt"})
            alt = (altmeta.get("content") if altmeta else None)
            return {
                "url": imageurl,
                "link": url,
                "credit": ("官方提供" if host.endswith((".gov", ".gov.tw", "airbus.com", "boeing.com", "nasa.gov")) else "原始新聞來源（攝影者詳見原文）"),
                "license": None,
                "provider": host,
                "kind": "source_image",
                "matched": "editorial:original-article-image",
                "subject": (alt or (a.get("en") or {}).get("title") or (a.get("zh") or {}).get("title") or "相關新聞資料照片").strip()[:180],
                "description": "引自本文註明來源的新聞頁面主圖片。是否為事件現場、影像日期及攝影者以來源頁面說明為準。",
                "curated": True
            }
        except Exception:
            continue
    return None

def photo_pool():
    cache = json.loads((ROOT / "data/images.json").read_text(encoding="utf-8"))
    out, seen = [], set()
    for entry in (cache.get("articles") or {}).values():
        i = entry.get("image") if entry.get("status") == "matched" else None
        if not isinstance(i, dict) or i.get("provider") != "Wikimedia Commons":
            continue
        url = i.get("url")
        if not url or url.split("?")[0] in seen or not i.get("license"):
            continue
        seen.add(url.split("?")[0])
        out.append(i)
    return out

POOL = photo_pool()

def commons_pool_candidate(a):
    title = " ".join(str((a.get(lang) or {}).get("title") or "") for lang in ("en", "zh"))
    titlelow = title.lower()
    target = images.find_airline(a)
    model = images.find_aircraft_type(a)
    city = ""
    if re.search(r"松山機場|songshan airport", title, re.I):
        city = "Taipei Songshan Airport"
    elif re.search(r"利雅德|利雅得|king khalid|riyadh", title, re.I):
        city = "King Khalid International Airport"
    elif re.search(r"FAA|美國聯邦航空管理局|空管", title, re.I) and not target and not model:
        city = "Federal Aviation Administration"
    elif re.search(r"無人機|drone|UAS|UAV", title, re.I) and not target and not model:
        city = "Quadcopter"
    elif re.search(r"F-104|Starfighter", title, re.I):
        city = "F-104"
    elif re.search(r"Su-30", title, re.I):
        city = "Su-30"
    elif re.search(r"F-15EX", title, re.I):
        city = "F-15"
    elif re.search(r"MQ-9B", title, re.I):
        city = "MQ-9B"
    elif re.search(r"Gripen|JAS-39", title, re.I):
        city = "Gripen"
    elif re.search(r"F-16", title, re.I):
        city = "F-16"
    else:
        pass
    # Explicit carrier identity: never use photos of an unrelated airline.
    from image_selection import phrase, model_matches
    ranked = []
    for img in POOL:
        phototext = unquote(urlsplit(img.get("url", "")).path).replace("_", " ") + " " + str(img.get("subject") or "")
        score = 0
        if target and (phrase(target, phototext) or phrase(target.split(" Airlines")[0], phototext)):
            score = 90
        if city and phrase(city, phototext):
            score = max(score, 70)
        if not score:
            continue
        # A specifically identified aircraft model requires that same model;
        # a generic image of the airline alone is not sufficient.
        headline_model = model if model and (phrase(model, title) or model.lower().replace("-", "") in titlelow.replace("-", "")) else None
        if headline_model and not model_matches(headline_model, phototext):
            # Same-airport photos can depict the facility rather than the aircraft.
            if not (city and not target):
                continue
        if "interior" in phototext.lower() and not re.search(r"座椅|客艙|cabin|seat", title, re.I):
            continue
        score += min(30, len(str(img.get("subject") or "")))
        ranked.append((score, img))
    if not ranked:
        return None
    result = dict(max(ranked, key=lambda x:x[0])[1])
    result["kind"] = "source_image"
    result["matched"] = "editorial:verified-commons-subject"
    result["description"] = (
        "Wikimedia Commons中與報導之航空公司、機型、機場或機構相符的公開授權資料照片；"
        "並非此次事件現場或同一架航機，實際拍攝主體請見原圖頁。"
    )
    result["curated"] = True
    return result


def resolve(item):
    path, a = item
    id_ = a.get("id")
    try:
        photo = official_candidate(a)
        source_kind = "official"
        if photo is None:
            photo = original_publisher_candidate(a)
            source_kind = "source-rss"
        if photo is None:
            photo = source_og_image(a)
            source_kind = "source-og"
        if photo is None:
            photo = commons_pool_candidate(a)
            source_kind = "commons-existing"
        if photo is None:
            photo = images.resolve_image(a, usage=Counter())
            source_kind = "pipeline"
        if photo and images.existing_image_matches(a, photo):
            return (path, id_, photo, source_kind)
        return (path, id_, None, "no-suitable-source-photo")
    except Exception as err:
        return (path, id_, None, type(err).__name__ + ": " + str(err)[:100])

def main():
    inputs = {}
    tasks = []
    for path in sorted((ROOT / "data/articles").glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        wanted = [a for a in doc.get("articles") or []
                  if isinstance(a, dict) and in_window(a) and a.get("archived") is not True
                  and not (isinstance(a.get("image"), dict) and a["image"].get("url"))]
        if wanted:
            inputs[path] = doc
            tasks.extend((path, a) for a in wanted if a.get("articleFormat") != "roundup")
    print("BACKFILL_TOTAL_MISSING", sum(len([a for a in doc.get("articles") or [] if in_window(a) and not (a.get("image") or {}).get("url")]) for doc in inputs.values()), "TASKS", len(tasks), flush=True)
    outputs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for result in concurrent.futures.as_completed([pool.submit(resolve, x) for x in tasks]):
            outputs.append(result.result())
    successes = {}
    missing = []
    for path, id_, photo, reason in outputs:
        if photo:
            successes[id_] = photo
        else:
            article = next(a for a in inputs[path]["articles"] if a.get("id") == id_)
            missing.append({"id": id_, "title": article.get("zh", {}).get("title"), "reason": reason,
                            "source": (article.get("sources") or [{}])[0].get("url")})
    updated = 0
    for path, doc in inputs.items():
        for a in doc.get("articles") or []:
            if a.get("id") in successes and not (a.get("image") or {}).get("url"):
                a["image"] = successes[a["id"]]
                updated += 1
        if any(a.get("id") in successes for a in doc.get("articles") or []):
            original = path.read_text(encoding="utf-8")
            compact = original.lstrip().startswith('{"articles"')
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=None if compact else 2) + "\n", encoding="utf-8")
    report = {"updated": updated, "remaining": missing, "countRemaining": len(missing),
              "roundupSkipped": len(tasks) < sum(len([a for a in doc.get("articles") or [] if in_window(a) and not (a.get("image") or {}).get("url")]) for doc in inputs.values())}
    (ROOT / "scripts/_oneoff_image_backfill_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("BACKFILL_ATTACHED", updated, "REMAINING", len(missing), flush=True)
    for a in missing:
        print("MISSING", a["id"], a["title"], a["reason"], flush=True)
    return 0


def finish_verified_editorial():
    from datetime import datetime
    def commons(file, author, license, subject, notes):
        from urllib.parse import quote
        return {
            "url": "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(file, safe="") + "?width=1280",
            "link": "https://commons.wikimedia.org/wiki/File:" + quote(file.replace(" ", "_"), safe="()_,.-"),
            "credit": author + "／Wikimedia Commons",
            "license": license,
            "provider": "Wikimedia Commons",
            "kind": "source_image",
            "matched": "editorial:manual-verified-commons",
            "subject": subject,
            "description": notes,
            "curated": True
        }
    def official(url, link, author, subject, notes):
        return {"url":url,"link":link,"credit":author,"license":None,"provider":author,
                "kind":"source_image","matched":"editorial:manual-official-or-credited",
                "subject":subject,"description":notes,"curated":True}
    airport=commons("Taiwan Taoyuan Airport Terminal 2 May 2025.jpg","4300streetcar","CC BY 4.0",
                    "桃園國際機場第二航廈","桃園機場2025年資料照片；非燃油附加費公布現場，適用國籍航空國際航線新聞。")
    easa=commons("EASA Headquarters - EASA Direktion.jpg","Wikimedia Commons原作者（詳原圖頁）","CC BY-SA 4.0",
                 "歐盟航空安全局總部","EASA總部建築資料照片，非新法規發布活動。")
    riyadh=commons("King Khalid International Airport.JPG","Vanquish0","CC BY-SA 4.0",
                   "利雅德哈立德國王國際機場","事前拍攝之機場資料照，並非2026年10月襲擊或航班取消現場。")
    southwest=commons("Boeing 737-700 of Southwest Airlines preparing to Takeoff KCMH 1.jpg","Sixflashphoto","CC BY-SA 4.0",
                     "西南航空Boeing 737-700","西南航空737-700同公司資料照；非ChatGPT外掛使用介面。")
    flydubai=commons("FlyDubai 737-800 A6-FDB.jpg","Wikimedia Commons原作者（詳原圖頁）",None,
                    "flydubai Boeing 737-800","flydubai 737-800同公司資料照，非涉事FZ1073班機。")
    military=commons("Shenyang J-16D.jpg","中華民國國防部","作者允許標示來源使用",
                    "中國人民解放軍J-16D戰機","中華民國國防部曾公布的共軍戰機資料照，非本次偵測航跡影像。")
    drone=commons("Quadcopter Drone in flight.jpg","Project Kei","CC BY-SA 4.0",
                  "四軸無人機","無人機類型示意資料照，非此次獲補助廠商的實際研發機種。")
    lufthansa=commons("Lufthansa Airbus A320neo.jpg","Paul Schmid","CC BY-SA 4.0",
                      "德國漢莎航空Airbus A320neo","漢莎機隊實機資料照，非2027年日本航線首航影像。")
    alaska=commons("Boeing 737 MAX 9 - Alaska Airlines - N823AK.jpg","Oleg Yunakov","CC BY-SA 4.0",
                   "阿拉斯加航空Boeing 737 MAX 9","阿拉斯加航空實機資料照，非Breeze聯營訂位介面。")
    airbaltic=commons("YL-ABD at AMS 20261006.jpg","VynedJ",None,
                     "airBaltic空中巴士A220-300 YL-ABD","2026年10月6日攝於阿姆斯特丹的airBaltic實機資料照；非裁員現場。")
    patches={
      "a-20261001-1529-taiwan-caa-international-fuel-surcharges":airport,
      "a-taiwan-caa-fuel-surcharge-increase-20261001":airport,
      "a-20261010-1359-easa-publishes-easy-access-rules-for-cs":easa,
      "a-epic-e1000ax-autoland-faa-certification-20260930":official(
         "https://www.aerotime.aero/images/2026/10/Recently-Saved-1-of-1-28.jpeg",
         "https://www.aerotime.aero/articles/epic-e1000-ax-garmin-autoland-faa-certification",
         "AeroTime（影像作者詳原文）","Epic Aircraft E1000 AX",
         "E1000 AX客機同型資料照片，非Garmin Autoland認證發布會。"),
      "a-manual-recovery-southwest-chatgpt-plugin-20261009":southwest,
      "a-us-king-air-philippine-coast-guard-20260930":official(
         "https://www.scramble.nl/images/news/2026/february/Philippines_Textron_Beechcraft_King_Air_credit_Textron.jpg",
         "https://www.scramble.nl/military-news/new-beechcraft-king-air-aircraft-for-philippine-coast-guard",
         "Textron Aviation／Scramble","Beechcraft King Air",
         "Textron提供的King Air系列航空器資料照，非交付現場。"),
      "a-tap-final-privatization-bids-20260930":commons(
         "Airbus A330-941N (c-n 1819, CS-TUA) 2026-04-08 Andre Gerwing Collection ID 028231.jpg",
         "André Gerwing","CC BY-SA 4.0","TAP Air Portugal A330-900neo CS-TUA",
         "2026年4月拍攝的TAP實機資料照，非民營化談判現場。"),
      "a-taic-air-new-zealand-q300-timaru-final-report-20261001":commons(
         "Air NZ Q300 NZ-NEM at PMR (24443249755).jpg",
         "Wikimedia Commons原作者（詳原圖頁）",None,"Air New Zealand Q300 ZK-NEM",
         "所涉航機ZK-NEM的歷史照片，非2023年低於安全高度事件現場。"),
      # Corrections: reject cross-topic social-site default images and
      # unlicensed stock imagery when a relevant official/Commons image exists.
      "a-20260930-1937-eurocontrol-and-easa-launch-avenir-envir":easa,
      "a-20261009-1301-nearly-300-riyadh-flights-cancelled-or-d":riyadh,
      "a-20261010-1851-houthis-suspected-of-missile-strike-on-r":riyadh,
      "a-manual-recovery-airbaltic-workforce-plan-20261009":airbaltic,
      "a-manual-recovery-taiwan-mnd-oct9-aircraft-20261009":military,
      "a-manual-recovery-taiwan-drone-rd-grants-20261009":drone,
      "a-manual-recovery-lufthansa-japan-summer2027-20261009":lufthansa,
      "a-manual-recovery-alaska-breeze-ticket-test-20261009":alaska,
      "a-manual-recovery-flydubai-investigation-target-20261009":flydubai
    }
    encountered=set(); modified=0; non_archived=[]
    for p in (ROOT/"data/articles").glob("*.json"):
        data=json.loads(p.read_text(encoding="utf-8"))
        dirty=False
        for article in data.get("articles") or []:
            if not isinstance(article,dict) or not in_window(article) or article.get("archived") is True:
                continue
            art_id=article.get("id")
            if art_id in patches:
                article["image"]=patches[art_id]
                encountered.add(art_id)
                modified += 1
                dirty=True
            non_archived.append(article)
        if dirty:
            raw=p.read_text(encoding="utf-8")
            p.write_text(json.dumps(data,ensure_ascii=False,
                                   indent=None if raw.lstrip().startswith('{"articles"') else 2)+"\n",
                         encoding="utf-8")
    missing=[{"id":a.get("id"),"title":(a.get("zh") or {}).get("title")}
             for a in non_archived if not (a.get("image") or {}).get("url")]
    report_path=ROOT/"scripts/_oneoff_image_backfill_report.json"
    report=json.loads(report_path.read_text(encoding="utf-8"))
    report.update({
       "finalizedCurated":modified,"expectedCurated":len(patches),
       "missingExpectedIds":sorted(set(patches)-encountered),
       "finalArticleCount":len(non_archived),
       "finalImages":sum(bool((a.get("image") or {}).get("url")) for a in non_archived),
       "countRemaining":len(missing),"remaining":missing
    })
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FINAL_MANUAL",modified,"OF",len(patches),"PUBLISHED_ARTICLES",len(non_archived),
          "IMAGES",report["finalImages"],"MISSING",len(missing),"NOT_FOUND",report["missingExpectedIds"],flush=True)
    return 0 if not missing and len(encountered)==len(patches) else 2


def verify_new_image_links():
    import concurrent.futures
    from collections import Counter
    import requests
    images_by_url = {}
    suspicious=[]
    flagged=("pic_fb.jpg","company-share.jpg","adobestock","shutterstock_","hqdefault.jpg","generic-social","default-share")
    for path in (ROOT/"data/articles").glob("*.json"):
        doc=json.loads(path.read_text(encoding="utf-8"))
        for a in doc.get("articles") or []:
            if not isinstance(a,dict) or not in_window(a) or a.get("archived") is True:
                continue
            img=a.get("image") or {}
            url=str(img.get("url") or "")
            if any(marker in url.lower() for marker in flagged):
                suspicious.append({"id":a.get("id"),"url":url})
            if str(img.get("matched") or "").startswith("editorial:"):
                if url:
                    images_by_url.setdefault(url,[]).append(a.get("id"))
    def probe(job):
        url, ids=job
        try:
            response=requests.get(url,headers={
                "User-Agent":"Mozilla/5.0 (compatible; SKYTICAL/1.0; news-image-qa)",
                "Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },timeout=(4,11),stream=True,allow_redirects=True)
            status=response.status_code
            ct=response.headers.get("Content-Type","").split(";")[0].strip().lower()
            final=response.url
            response.close()
            return {"status":status,"contentType":ct,"url":url,"resolved":final[:220],"ids":ids}
        except Exception as e:
            return {"status":0,"contentType":"","url":url,"ids":ids,
                    "reason":type(e).__name__ + ":" + str(e)[:100]}
    checks=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for i,out in enumerate(pool.map(probe,images_by_url.items()),1):
            checks.append(out)
            if i%30==0: print("IMAGE_CHECK_PROGRESS",i,"/",len(images_by_url),flush=True)
    bad=[x for x in checks if 400<=x["status"]<500 and x["status"] not in (403,429)
         or 200<=x["status"]<300 and x["contentType"] not in ("image/jpeg","image/png","image/webp","image/gif","image/avif","image/svg+xml")]
    forbidden=[x for x in checks if x["status"] in (403,429)]
    other=[x for x in checks if x["status"]==0 or x["status"]>=500]
    report_path=ROOT/"scripts/_oneoff_image_backfill_report.json"
    report=json.loads(report_path.read_text(encoding="utf-8"))
    report["linkQA"]={"checked":len(checks),"ok":len(checks)-len(bad)-len(forbidden)-len(other),
        "broken":bad, "blocked":forbidden,"unconfirmed":other,"suspicious":suspicious}
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("IMAGE_LINK_QA",json.dumps({
        "tested":len(checks),"broken":len(bad),"blocked":len(forbidden),
        "unconfirmed":len(other),"suspicious":len(suspicious),
        "examplesBroken":bad[:12],"examplesBlocked":forbidden[:4],"suspiciousImg":suspicious[:15],
    },ensure_ascii=False),flush=True)
    return 0

if __name__ == "__main__":
    result=main()
    if result == 0:
        result=finish_verified_editorial()
    if result == 0:
        result=verify_new_image_links()
    sys.exit(result)
