"""Private-session build contracts; no Google account or network required."""
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build  # noqa: E402


def capture_pages(monkeypatch, url):
    pages = []
    monkeypatch.setenv("AVWIRE_MANUAL_TOKEN", "x" * 43)
    monkeypatch.setenv("SKYTICAL_TRAFFIC_APP_URL", url)
    monkeypatch.setattr(build, "render", lambda env, template, path, ctx: pages.append((path, ctx)))
    assert build.render_manual_workbench(None, {}) == 2
    return pages


def test_private_route_and_token_free_app_asset(monkeypatch):
    url = "https://script.google.com/macros/s/test_deployment/exec"
    pages = capture_pages(monkeypatch, url)
    assert pages[1][0] == f"m/{'x' * 43}/index.html"
    assert pages[1][1]["traffic_app_url"] == url
    assert pages[2][0] == "assets/traffic-dashboard-app.html"
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True,
                      undefined=StrictUndefined)
    template = env.get_template("traffic-dashboard.html")
    entry = template.render(**pages[1][1])
    app = template.render(**pages[2][1])
    assert f'content="0;url={url}"' in entry
    assert 'data-traffic-transport="apps-script"' in app
    assert 'https://accounts.google.com/gsi/client' not in app
    assert 'http-equiv="Content-Security-Policy"' not in app  # HtmlService owns iframe/RPC policy
    assert 'noindex,nofollow,noarchive,nosnippet' in app
    assert 'https://skytical.tech/assets/traffic-dashboard.js?v=' in app
    assert f"m/{'x' * 43}" not in app
    assert 'access_token' not in app


@pytest.mark.parametrize("url", [
    "https://evil.test/exec", "http://script.google.com/macros/s/test/exec",
    "https://script.google.com.evil.test/macros/s/test/exec",
    "https://script.google.com/macros/s/test/exec?token=unexpected",
    "https://script.google.com/macros/s/test/exec#fragment", "",
])
def test_untrusted_or_missing_backend_preserves_browser_oauth(monkeypatch, url):
    pages = capture_pages(monkeypatch, url)
    assert pages[1][1]["traffic_app_url"] == ""
    assert pages[2][1]["traffic_app_url"] == ""
