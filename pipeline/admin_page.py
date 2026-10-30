"""Capability-URL admin shell; authentication can replace the browser adapter later."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from public_article import public_article_id


def override_path(article_id: str) -> str:
    return "editorial-overrides/" + hashlib.sha256(article_id.encode()).hexdigest() + ".json"


def editorial_article(article, data_dir: Path):
    """An independent editorial record survives an already-running bot commit."""
    if not isinstance(article, dict) or not isinstance(article.get("id"), str):
        return article
    path = data_dir / override_path(article["id"])
    if not path.is_file():
        return article
    edited = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(edited, dict) or edited.get("id") != article["id"]:
        raise ValueError("editorial override does not match its article")
    return edited


def render_admin_page(env, site_dir: Path, articles_dir: Path, base: str) -> int:
    key = os.environ.get("ADMIN_KEY", "").strip()
    # Do not emit the raw secret into HTML, filenames, logs or discovery files.
    if len(key) < 32:
        return 0
    slug = hashlib.sha256(key.encode("utf-8")).hexdigest()
    folder = site_dir / "admin" / slug
    folder.mkdir(parents=True, exist_ok=True)
    index = {}
    for path in sorted(articles_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for article in payload.get("articles", []):
            article_id = article.get("id")
            if isinstance(article_id, str) and article_id:
                index[public_article_id(article_id)] = {
                    "id": article_id, "path": f"data/articles/{path.name}",
                    "overridePath": "data/" + override_path(article_id),
                }
    (folder / "articles.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (folder / "index.html").write_text(
        env.get_template("admin.html").render(base=base), encoding="utf-8")
    entry = site_dir / "admin" / "index.html"
    entry.write_text(env.get_template("admin-entry.html").render(base=base),
                     encoding="utf-8")
    return 2
