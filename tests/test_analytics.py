"""Regression checks for optional GA4 and Facebook campaign links."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build  # noqa: E402

def main():
    with patch.dict(os.environ, {}, clear=True):
        assert build.ga4_measurement_id() == "G-J45CLL0ZVY"
    with patch.dict(os.environ, {"SKYTICAL_GA4_MEASUREMENT_ID": "G-ABC1234567"}):
        assert build.ga4_measurement_id() == "G-ABC1234567"
        ctx = build.base_ctx("zh", "home", "", title="Test",
                             description="Test", ticker=[], build={})
        assert ctx["ga4_measurement_id"] == "G-ABC1234567"
    for bad in ("", "G-INVALID<script>", "UA-123-1", "G-TOO_LONG_AAAAAAAAAAAAA"):
        with patch.dict(os.environ, {"SKYTICAL_GA4_MEASUREMENT_ID": bad}):
            assert build.ga4_measurement_id() == ""
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "{% if ga4_measurement_id %}" in base
    assert "allow_ad_personalization_signals: false" in base
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for param in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
        assert 'url.searchParams.set("' + param + '"' in app
    assert 'data-facebook-promo-copy' in (ROOT / "templates" / "article.html").read_text(encoding="utf-8")
    for path in ("hourly.yml", "manual-article-deploy.yml", "briefing.yml"):
        assert "SKYTICAL_GA4_MEASUREMENT_ID" in (
            ROOT / ".github" / "workflows" / path).read_text(encoding="utf-8")
    print("test_analytics: OK")

if __name__ == "__main__":
    main()
