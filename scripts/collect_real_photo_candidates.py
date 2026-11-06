"""Temporary Wikimedia Commons photo discovery for manually reviewed backfill."""
from __future__ import annotations
import concurrent.futures
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"pipeline"))
import images
from common import ROOT
images.TIMEOUT=(4,9)
AUDIT=ROOT/"data/photo-gap-audit.json"
OUT=ROOT/"data/photo-commons-candidates.json"

def norm(s):
    return re.sub(r"\s+"," ",str(s or "")).strip()

def query_for(a, gap):
    title = " ".join(str((a.get(lang) or {}).get("title") or "") for lang in ("en","zh"))
    airline = images.find_airline(a)
    model = images.find_aircraft_type(a)
    airport = images.find_airport(a)
    org = images.find_org(a)
    options=[]
    if airline:
        options.append((f"{airline} airplane",airline,"airline"))
    if model:
        m=norm(model)
        options.append((f"{m} aircraft",re.sub(r"^(?:Airbus|Boeing|Embraer|Cessna) ","",m,flags=re.I),"model"))
    if airport:
        q,tokens,subject=airport
        options.append((str(q),str(tokens[0]) if tokens else str(q),"airport"))
    if org:
        q,tokens,subject=org
        options.append((str(q),str(tokens[0]) if tokens else str(q),"org"))
    # Use the named institution or manufacturer when no carrier/model was found.
    if not options:
        entities=a.get("entities") or {}
        for key in ("organizations","manufacturers","operators"):
            vals=entities.get(key) or []
            for value in vals[:3]:
                val=norm(value)
                if len(val)<4 or not re.search("[A-Za-z]",val):
                    continue
                if val.casefold() in title.casefold() or not options:
                    options.append((val,val,"organization"))
                    break
            if options:
                break
    return options[:2]

def run_query(item):
    query,token,kind=item
    try:
        photo=images.lookup_commons(
            query,[token],subject=None,require_all=True,
            min_year=2010,prefer_landscape=True,
            reject_title_re=images._BAD_TITLE_RE,
        )
    except Exception as e:
        return {"query":query,"token":token,"kind":kind,"error":type(e).__name__}
    if photo:
        return {"query":query,"token":token,"kind":kind,"photo":photo}
    return {"query":query,"token":token,"kind":kind,"photo":None}

def main():
    report=json.loads(AUDIT.read_text(encoding="utf-8"))
    choices={}
    qset={}
    for gap in report["gaps"]:
        path=ROOT/gap["path"]
        data=json.loads(path.read_text(encoding="utf-8"))
        a=next((x for x in data.get("articles",[]) if x.get("id")==gap["id"]),None)
        if a is None:
            continue
        options=query_for(a,gap)
        choices[gap["id"]]=options
        for q in options:
            qset.setdefault(q,q)
    queries=list(qset)
    found={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futures={ex.submit(run_query,q):q for q in queries}
        for f in concurrent.futures.as_completed(futures):
            q=futures[f]
            try:
                result=f.result()
            except Exception as exc:
                result={"query":q[0],"error":type(exc).__name__}
            found[q]=result
    items=[]
    for gap in report["gaps"]:
        suggestions=[found[q] for q in choices.get(gap["id"],[]) if q in found]
        items.append({"id":gap["id"],"title":gap["enTitle"],"queries":suggestions})
    payload={"articles":len(items),"uniqueQueries":len(queries),
             "queryPhotos":sum(bool(x.get("photo")) for x in found.values()),
             "covered":sum(any(bool(x.get("photo")) for x in p["queries"]) for p in items),
             "items":items}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("COMMONS_DISCOVERY_SUMMARY "+json.dumps({k:v for k,v in payload.items() if k!="items"}))
if __name__=="__main__":
    main()
