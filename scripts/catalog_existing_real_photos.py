"""Temporary catalog of existing real photographs used by SKYTICAL articles."""
import json
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
items={}
count=0
for path in sorted((ROOT/"data/articles").glob("*.json")):
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        continue
    for a in obj.get("articles",[]) if isinstance(obj,dict) else []:
        if not isinstance(a,dict) or a.get("archived") is True:
            continue
        im=a.get("image")
        if not isinstance(im,dict) or not im.get("url"):
            continue
        url=str(im.get("url") or "")
        if ".svg" in url.lower() or im.get("kind")=="illustration" or "skytical-editorial-20261105" in url:
            continue
        # No logos, infographics, rendered/AI-created assets.
        subject=str(im.get("subject") or "")
        bad=("illustration","rendering","logo","diagram","mockup","model kit","ai-generated")
        if any(s in (url+" "+subject).lower() for s in bad):
            continue
        count+=1
        key=str(im.get("link") or url)
        if key in items:
            items[key]["used"]+=1
            continue
        img={k:im.get(k) for k in ("url","link","credit","license","provider","kind","subject","description","photoYear") if im.get(k) is not None}
        items[key]={"image":img,"sourceId":a.get("id"),"sourceTitle":(a.get("en") or {}).get("title"),"used":1}
out={"articlePhotoCount":count,"uniquePhotos":len(items),"items":list(items.values())}
path=ROOT/"data/photo-real-catalog.json"
path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("PHOTO_CATALOG_SUMMARY",json.dumps({k:v for k,v in out.items() if k!="items"}))
