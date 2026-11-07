"""Conservative manually curated photographic recovery of remaining SKYTICAL news.

No synthetic illustrations or generic images. Wikimedia media metadata is
verified live; the photographed subject is stated honestly as a file photo.
"""
from __future__ import annotations

import html
import json
import re
import time
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"pipeline"))
from common import load_json,save_json
from image_selection import model_matches

ARTICLES=ROOT/"data/articles"
OUTPUT=ROOT/"data/archive-targeted-photo-report.json"
PREVIOUS=ROOT/"data/archive-photo-qa-report.json"
API="https://commons.wikimedia.org/w/api.php"
HEADERS={"User-Agent":"SKYTICAL-archive-photo-curator/1.0 (editorial attribution; skytical.tech)"}
TIMEOUT=13
START=time.monotonic()
MAX_SECONDS=405
TAG=re.compile(r"<[^>]+>")
BAD=re.compile(r"illustrat|drawn|drawing|render|model(?:s)?[_. -]?kit|simulation|graphic|diagram|sketch|CGI|generated|logo|map\b|cartoon|chart|aircraft_cabin|cockpit_mockup",re.I)
GOOD_LICENSE=re.compile(r"CC BY|CC0|public domain|PD-",re.I)

# Hand-identified real-world subjects. Every file is checked with Commons API
# before application; a non-existent file or unusable license is never accepted.
CATEGORIES=[
 (r"(?:總統府|Presidential Office|總統.*無人機)",["View of Presidential Office Building, Taiwan.jpg","TaipeiROCPresidentialOfficeBuilding.jpg"],"台灣總統府建築"),
 (r"(?:高鐵|High Speed Rail|N700ST|台鐵|Taiwan Railway|南迴線|枋山|枋野|TRA\s)",["2008-07-17 Taiwan High Speed 700T train at Zuoying Station.jpg","On a Taiwan High Speed 700T train.jpg"],"台灣鐵路列車（歷史資料照片，不是 N700ST）"),
 (r"(?:General Dynamics|通用動力|Gulfstream|商務航空|business aviation|私人噴射機)",["Gulfstream G700.jpg","Cessna Citation CJ3.jpg"],"商務噴射機實際照片"),
 (r"(?:Citation CJ3|賽斯納獎狀|Strasser|business jet|private jets)",["Cessna Citation CJ3.jpg"],"賽斯納獎狀 CJ3 商務機"),
 (r"(?:Lockheed Martin|洛克希德|F-35|F35A|SPEEA|波音.*工會|Boeing.*contract|波音.*財報|波音.*談判|Boeing.*earnings|波音.*員工|波音.*成本|Spirit AeroSystems)",["Boeing Everett Plant.jpg","Boeing Everett 01.jpg"],"波音飛機生產廠房"),
 (r"(?:A350.*production|Airbus.*buyback|空中巴士.*財報|空巴.*財報|空中巴士.*庫藏股|Airbus.*results)",["Airbus A350-941 on the assembly line in Toulouse.jpg"],"空中巴士飛機生產線"),
 (r"(?:C919|中國商飛|COMAC)",["China Eastern Airlines Comac C919 (B-65A0) on final approach towards SHA.jpg"],"中國東方航空 C919（非高原型試驗機）"),
 (r"(?:東航.*A320|China Eastern.*A320|B-8228)",["(SGP-Singapore) China Eastern Airlines Airbus A320-251N B-325R @ WSSS 2026-09-03.jpg"],"中國東方航空 A320 系列（非新聞指定註冊號）"),
 (r"(?:NH90|特種作戰型直升機)",["Spanish Air Force NH90 in Airbus Helicopters.jpg"],"NH90 直升機"),
 (r"(?:Joby|eVTOL|垂直起降機|先進空中交通|垂直起降機場)",["Joby Aviation S4 experimental eVTOL aircraft at Edwards AFB.jpg"],"Joby Aviation S4 電動垂直起降試驗機（其他公司新聞不適用）"),
 (r"(?:漢光|國軍.*戰機|空軍戰機.*臺灣|空軍戰機.*台灣|F-16V|F16V|志航基地)",["ROCAF F-16.jpg"],"中華民國空軍 F-16 實機"),
 (r"(?:777X|777-9|MAX 10|737 MAX 10)",["Boeing Everett Factory - 777X fuselages.jpg","737 MAX 10 Roll Out (Nov 2019) - 001.jpg"],"波音客機實際生產與展示照片"),
]
# Generic associations are only allowed when the headline unambiguously names
# the subject. Never show a competitor's aircraft for a specific airline story.
FILTER_OTHER_COMPANY=re.compile(r"airlines|airways|航空|aviation",re.I)
ALLOWED_GENERIC=[
 (r"(?:勞斯萊斯|Rolls[- ]Royce|Trent)",["Rolls-Royce Trent 1000.jpg"],"勞斯萊斯 Trent 引擎"),
 (r"(?:GE Aerospace|通用電氣航太|GE.*引擎)",["General Electric GEnx engine.jpg"],"通用電氣航空引擎"),
 (r"(?:Embraer|巴西航空工業)",["Embraer E195-E2.jpg"],"巴西航空工業 E195-E2 機型"),
 (r"(?:KAAN|土耳其.*戰機)",["TAI TF Kaan.jpg"],"土耳其 KAAN 戰機"),
 (r"(?:Eurocontrol|EUROCONTROL)",["EUROCONTROL Headquarters Brussels.jpg"],"歐洲航管組織建築"),
 (r"(?:樟宜機場|Changi Airport|SIN.*機場)",["Singapore Changi Airport Terminal 3.jpg"],"新加坡樟宜機場航廈"),
 (r"(?:曼徹斯特機場|Manchester Airport)",["Manchester Airport Terminal 2.jpg"],"英國曼徹斯特機場航廈"),
]
def title(a):
    return " / ".join(str((a.get(lang) or {}).get("title") or "") for lang in ("zh","en"))
def cleanse(s):
    return html.unescape(TAG.sub(" ",str(s or ""))).strip()[:100]
def photo_of(name):
    if time.monotonic()-START>MAX_SECONDS:
        return None
    try:
        r=requests.get(API,params={"action":"query","format":"json","titles":"File:"+name,
             "prop":"imageinfo","iiprop":"url|size|extmetadata","iiurlwidth":1280},headers=HEADERS,timeout=TIMEOUT)
        r.raise_for_status()
        pages=(r.json().get("query") or {}).get("pages") or {}
        for obj in pages.values():
            if obj.get("missing") is not None:
                continue
            filename=str(obj.get("title") or name)
            if BAD.search(filename) or not re.search(r"\.(?:jpg|jpeg|png|webp)$",filename,re.I):
                continue
            for info in obj.get("imageinfo") or []:
                if int(info.get("width") or 0)<500 or int(info.get("height") or 0)<300:
                    continue
                m=info.get("extmetadata") or {}
                license_=cleanse((m.get("LicenseShortName") or {}).get("value"))
                if not GOOD_LICENSE.search(license_):
                    continue
                url=str(info.get("thumburl") or info.get("url") or "")
                if not url.startswith("https://"):
                    continue
                return {"url":url,
                        "link":str(info.get("descriptionshorturl") or info.get("descriptionurl") or
                              ("https://commons.wikimedia.org/wiki/"+quote(filename.replace(" ","_")))),
                        "credit":cleanse((m.get("Artist") or {}).get("value")) or "Wikimedia Commons 作者，詳見照片來源頁",
                        "license":license_,"provider":"Wikimedia Commons","kind":"file_photo",
                        "raw_title":filename}
    except (requests.RequestException,TypeError,ValueError):
        pass
    return None

def select(a, candidates):
    head=title(a)
    # Do not present a different air carrier's aircraft as a photo of the one
    # named in a headline. Specific same-company registry claims need exact
    # evidence; unresolved claims remain unresolved.
    if re.search(r"(Air Canada|Malaysia Airlines|LATAM|American Airlines|Delta Air Lines|"
                 r"STARLUX|United Airlines|EVA Air|Alaska Airlines|British Airways|"
                 r"China Airlines|KLM|Qantas|Thai Airways|JetBlue|WestJet|ANA|全日空|"
                 r"華航|星宇|長榮航|達美|美航|加拿大航空|馬航|日航|國泰)",head,re.I):
        return None
    for pattern, filenames, subject in candidates:
        if not re.search(pattern,head,re.I):
            continue
        # Joby real aircraft may ONLY be used for Joby stories.
        if "eVTOL" in pattern and not re.search(r"Joby",head,re.I):
            continue
        for filename in filenames:
            yield filename,subject,pattern

def main():
    backlog=load_json(PREVIOUS,{})
    items=backlog.get("unresolved") or []
    report={"generatedUtc":datetime.now(timezone.utc).isoformat(),
            "policy":"Actual credited CC-licensed photography only. Historical image captions; unknown never guessed.",
            "stats":{},"assigned":[],"unresolved":[]}
    checked={}
    by_path={}
    changed=set()
    stats=Counter()
    for issue in items:
        path=ROOT/issue.get("path","")
        if not path.is_file():
            continue
        data=by_path.get(path)
        if data is None:
            data=load_json(path,{})
            by_path[path]=data
        a=next((x for x in data.get("articles") or [] if x.get("id")==issue.get("id")),None)
        if a is None:
            continue
        if a.get("image"):
            stats["already_resolved"]+=1
            continue
        found=False
        for filename,subject,pattern in select(a,CATEGORIES+ALLOWED_GENERIC):
            if filename not in checked:
                checked[filename]=photo_of(filename)
            p=checked[filename]
            if p is None:
                continue
            im={k:v for k,v in p.items() if k!="raw_title"}
            im.update({"curated":True,"matched":"editorial:actual-photograph",
                       "subject":subject,"description":subject+"；已查證為真實攝影資料照，並非新聞當日現場或必然為所述特定機號。",
                       "sourceCaption":subject+"（歷史資料照，非此新聞的事件現場）"})
            a["image"]=im
            changed.add(path)
            report["assigned"].append({"id":a["id"],"imageSource":im["link"],"subject":subject})
            stats["new_photo"]+=1
            found=True
            break
        if not found:
            report["unresolved"].append({"id":a["id"],"title":issue.get("title"),"path":issue.get("path")})
            stats["unresolved"]+=1
    for path in changed:
        save_json(path,by_path[path])
    stats["files_changed"]=len(changed)
    stats["commons_files_verified"]=sum(1 for v in checked.values() if v)
    stats["commons_files_unavailable"]=sum(1 for v in checked.values() if v is None)
    stats["prior_unresolved"]=len(items)
    report["stats"]=dict(stats)
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("TARGETED_PHOTO_RESULT "+json.dumps(stats,ensure_ascii=False))
    for row in report["unresolved"][:20]:
        print("UNRESOLVED "+str(row["id"])+" "+str(row["title"]))

if __name__=="__main__":
    main()
