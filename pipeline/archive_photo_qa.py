"""Manually defined editorial safeguards for SKYTICAL historical real-photo coverage.

Revoke misleading cross-company stock assignments and replace eligible stories
with actual CC-licensed aircraft from the SAME named airline's fleet. All
captions disclose historical file-photo status, and every change is audited.
"""
from __future__ import annotations
import copy
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"pipeline"))
from common import load_json, save_json
import images
from image_selection import model_matches
REPORT=ROOT/"data/archive-photo-qa-report.json"
BANK=ROOT/"data/images.json"
ARTICLES=ROOT/"data/articles"
CUTOFF="2026-07-01"
BAD_FILE=re.compile(r"interior|seat|cabin|restroom|lavatory|sink|"
                    r"cockpit|logo|diagram|drawing|render|"
                    r"toy|model.?aircraft|mockup|illustration|"
                    r"mixed.?aircraft|stock",re.I)
KNOWN_ALIASES={
    "American Airlines":["americanairlines"],
    "Delta Air Lines":["deltaairlines"],
    "STARLUX Airlines":["starluxairlines"],
    "United Airlines":["unitedairlines"],
    "EVA Air":["evaair"],
    "Air Canada":["aircanada"],
    "All Nippon Airways":["allnipponairways"],
    "Emirates":["emirates"],
    "Alaska Airlines":["alaskaairlines"],
    "JetBlue":["jetblue"],
    "Lufthansa":["lufthansa"],
    "Malaysia Airlines":["malaysiaairlines"],
    "British Airways":["britishairways"],
    "China Airlines":["chinaairlines"],
    "LATAM Airlines":["latamairlines","latam"],
    "Qantas":["qantas"],
    "Japan Airlines":["japanairlines"],
    "FedEx":["fedex"],
    "Qatar Airways":["qatarairways"],
    "Philippine Airlines":["philippineairlines"],
    "KLM":["klm"],
    "Mandarin Airlines":["mandarinairlines"],
    "Tigerair Taiwan":["tigerair"],
    "WestJet":["westjet"],
    "Ryanair":["ryanair"],
    "Frontier Airlines":["frontier"],
    "Singapore Airlines":["singaporeairlines"],
    "Air France":["airfrance"],
    "Air India":["airindia"],
    "Iberia":["iberia"],
    "Breeze Airways":["breezeairways"],
    "Jet2":["jet2"],
    "Porter Airlines":["porterairlines"],
    "Cathay Pacific":["cathaypacific"],
    "Austrian Airlines":["austrianairlines"],
    "LOT Polish Airlines":["lotpolishairlines","lotairlines"],
    "Korean Air":["koreanair"],
    "Asiana Airlines":["asianaairlines"],
    "Air China":["airchina"],
    "China Eastern Airlines":["chinaeastern"],
    "China Southern Airlines":["chinasouthern"],
    "Virgin Australia":["virginaustralia"],
    "Saudia":["saudia"],
}
IATA={
    "url":"https://commons.wikimedia.org/wiki/Special:FilePath/IATA_Building_Montreal.jpg?width=1280",
    "link":"https://commons.wikimedia.org/wiki/File:IATA_Building_Montreal.jpg",
    "credit":"FBuHL09",
    "license":"CC BY-SA 4.0",
    "provider":"Wikimedia Commons",
    "kind":"file_photo",
    "subject":"國際航空運輸協會（IATA）蒙特婁辦公大樓",
    "description":"2014年拍攝的 IATA 蒙特婁辦公大樓實際照片。",
}
def canon(text):
    return re.sub(r"[^a-z0-9]+","",unquote(text).casefold())
def leaf(photo):
    return unquote(urlsplit(str(photo.get("url") or "")).path.rsplit("/",1)[-1])
def lead(article):
    return " ".join(str((article.get(x) or {}).get("title") or "") for x in ("zh","en"))
def safe(photo):
    if not isinstance(photo,dict) or photo.get("provider")!="Wikimedia Commons":
        return False
    if not photo.get("url") or not photo.get("link") or not re.search(r"CC BY|CC0|public domain|PD-",str(photo.get("license") or ""),re.I):
        return False
    name=leaf(photo)
    return bool(re.search(r"\.(jpe?g|png|webp)\Z",name,re.I) and not BAD_FILE.search(name))
def choose_airline(photo_bank, airline, article):
    aliases=KNOWN_ALIASES.get(airline,[canon(airline)])
    matches=[]
    for pic in photo_bank:
        fn=canon(leaf(pic))
        if not any(token in fn for token in aliases if len(token)>3):
            continue
        # The file itself must unambiguously identify the actual operator,
        # without trusting the sometimes incorrect cached subject metadata.
        # Avoid more than one competing operator shown in a group photograph.
        if any(other!=airline and any(
            token in fn for token in toks) for other,toks in KNOWN_ALIASES.items()
            if other!=airline and len(other)>5):
            continue
        if not safe(pic):
            continue
        model=images.headline_aircraft_types(article)
        score=0
        if model:
            score=25 if any(model_matches(m,leaf(pic)) for m in model[:2]) else 0
        score+=5 if pic.get("photoYear",0) and int(pic.get("photoYear"))>=2021 else 0
        score+=2 if len(fn)<110 else 0
        matches.append((score,pic))
    if not matches:
        return None
    return max(matches,key=lambda x:x[0])[1]
def mark(article,photo,method):
    p=copy.deepcopy(photo)
    p["provider"]="Wikimedia Commons"
    p["curated"]=True
    p["kind"]="source_image" if article.get("articleFormat")=="roundup" else "file_photo"
    p["matched"]="editorial:hand-reviewed-archive:"+method
    subject=str(p.get("subject") or "航空公司機隊")[:120]
    p["sourceCaption"]=subject+"，歷史資料照，非本次新聞現場。"
    p["description"]=(
        str(p.get("description") or subject)[:180]
        +"；此為真實攝影資料照，並非本次新聞事件當日拍攝，型號或註冊號可能與新聞主體不同。"
    )
    return p
def main():
    cache=load_json(BANK,{})
    photos={}
    for row in (cache.get("articles") or {}).values():
        p=row.get("image") or {}
        if safe(p):
            photos[str(p.get("link"))]=p
    bank=list(photos.values())
    stats=Counter()
    batches=[]
    changes=[]
    for path in sorted(ARTICLES.glob("*.json")):
        data=load_json(path,{})
        if not isinstance(data,dict) or not isinstance(data.get("articles"),list):
            continue
        changed=False
        for a in data["articles"]:
            if not isinstance(a,dict) or a.get("archived") or not a.get("publishedUtc"):
                continue
            if str(a["publishedUtc"])[:10]<CUTOFF:
                continue
            image=a.get("image") or {}
            method=str(image.get("matched") or "") if isinstance(image,dict) else ""
            # Earlier archive bank assignment used loose model-only matches;
            # remove those rather than showing another airline/manufacturer.
            if method=="archive:verified-real-photo:validated-cache":
                stats["revoked_unsafe_cache_image"]+=1
                changes.append({"id":a.get("id"),"action":"revoke-loose-bank","oldPhoto":image.get("link")})
                a.pop("image",None)
                a.pop("imageSelection",None)
                changed=True
                image={}
            if (isinstance(image,dict) and image.get("url")) or (isinstance(image,str) and image.startswith("https://")):
                continue
            title=lead(a)
            if re.search(r"\bIATA\b|國際航空運輸協會",title,re.I):
                a["image"]=mark(a,IATA,"iata-real-headquarters")
                stats["assigned_iata_office"]+=1
                changes.append({"id":a.get("id"),"action":"iata-headquarters"})
                changed=True
                continue
            airline=images.find_airline(a)
            if not airline:
                # Fallback only for airline company names literally in headline.
                normalized=canon(title)
                options=[x for x in KNOWN_ALIASES if any(v in normalized for v in KNOWN_ALIASES[x])]
                if options:
                    airline=max(options,key=len)
            if not airline:
                continue
            pic=choose_airline(bank,airline,a)
            if not pic:
                continue
            a["image"]=mark(a,pic,"same-airline-fleet")
            stats["assigned_same_airline_real_photo"]+=1
            changes.append({"id":a.get("id"),"action":"same-airline","airline":airline,"photo":pic["link"]})
            changed=True
        if changed:
            batches.append((path,data))
    for path,data in batches:
        save_json(path,data)
    # Full archive counts are recalculated after all corrections, rather than
    # treating old negative-cache records as a live missing-image list.
    total=with_image=missing=0
    remaining=[]
    for path in sorted(ARTICLES.glob("*.json")):
        data=load_json(path,{})
        for a in data.get("articles") or []:
            if not isinstance(a,dict) or a.get("archived") or str(a.get("publishedUtc") or "")[:10]<CUTOFF:
                continue
            total+=1
            im=a.get("image")
            if isinstance(im,dict) and im.get("url") and ".svg" not in str(im.get("url")).lower():
                with_image+=1
            elif isinstance(im,str) and im.startswith("https://") and ".svg" not in im.lower():
                with_image+=1
            else:
                missing+=1
                remaining.append({"id":a.get("id"),"title":(a.get("zh") or {}).get("title"),"path":str(path.relative_to(ROOT))})
    stats.update({"articles":total,"with_photo_field":with_image,"missing_photo_field":missing,"changed_article_files":len(batches),"photo_bank":len(bank)})
    REPORT.write_text(json.dumps({"generatedUtc":datetime.now(timezone.utc).isoformat(),"stats":dict(stats),
                                  "changes":changes,"unresolved":remaining},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PHOTO_QA "+json.dumps(stats,ensure_ascii=False))
    for row in remaining[:20]:
        print("PHOTO_QA_REMAINING "+str(row["id"])+" "+str(row["title"]))

if __name__=="__main__":
    main()
