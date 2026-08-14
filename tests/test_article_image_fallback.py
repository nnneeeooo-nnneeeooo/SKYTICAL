from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_article_template_always_has_a_visual_fallback():
    template = (ROOT / "templates" / "article.html").read_text(encoding="utf-8")

    assert "{% if a.image %}" in template
    assert "{% else %}" in template
    assert 'data-image-fallback="true"' in template
    assert "/assets/skytical-social.png" in template
    assert "暫無可驗證的事件或資料照片" in template
    assert "No verified event or file photo is available yet" in template
