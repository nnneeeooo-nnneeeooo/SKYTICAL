"""Offline assertions for the GA4 owner dashboard (no Google credentials needed)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    build = (ROOT / "pipeline" / "build.py").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "traffic-dashboard.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "traffic-dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "traffic-dashboard.css").read_text(encoding="utf-8")
    assert 'render(env, "traffic-dashboard.html", f"m/{token}/index.html"' in build
    assert 'render(env, "manual.html", f"m/{token}/draft/index.html"' in build
    assert 'return 2' in build[build.index("def render_manual_workbench"):build.index("# ── rendering")]
    assert '<meta name="robots" content="noindex,nofollow,noarchive,nosnippet">' in template
    assert '<meta name="referrer" content="no-referrer">' in template
    assert "frame-ancestors 'none'" in template
    assert "https://accounts.google.com/gsi/client" in template
    assert "https://analyticsdata.googleapis.com" in template
    assert "traffic-dashboard.css" in template and "traffic-dashboard.js" in template
    assert 'type="password"' not in template  # no stored cloud credentials
    assert "G-J45CLL0ZVY" not in template  # analytics collection tag isn't data access
    assert "analytics.readonly" in js
    assert "initTokenClient" in js
    assert "runReport" in js
    for label in ("activeUsers", "sessions", "screenPageViews",
                  "engagementRate", "sessionSource", "pagePath"):
        assert label in js
    assert "REFRESH_INTERVAL = 10 * 60 * 1000" in js
    assert "localStorage.setItem(key, value)" in js
    assert "accessToken =" in js
    assert "localStorage.setItem(CLIENT_KEY" not in js or "accessToken" not in js.split("save(CLIENT_KEY")[1].split(";")[0]
    assert 'cache: "no-store"' in js
    assert "textContent" in js
    assert "innerHTML" not in js
    assert "kpi-facebook" in template and "kpi-facebook" in js
    assert "max-width:600px" in css
    print("test_traffic_dashboard: OK")


if __name__ == "__main__":
    main()
