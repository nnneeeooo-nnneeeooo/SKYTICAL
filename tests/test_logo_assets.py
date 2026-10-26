"""Offline checks for SKYTICAL's canonical and generated brand assets."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def main() -> None:
    assert build.main() == 0

    master = ROOT / "docs" / "brand" / "SKYTICAL-master.svg"
    spec_path = ROOT / "docs" / "brand" / "SKYTICAL-LOGO-SPEC.md"
    logo_path = ROOT / "static" / "skytical-logo.svg"
    mark_path = ROOT / "static" / "skytical-mark.svg"
    social_path = ROOT / "static" / "skytical-social.png"
    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "site.css").read_text(encoding="utf-8")
    logo = logo_path.read_text(encoding="utf-8")
    mark = mark_path.read_text(encoding="utf-8")
    spec = spec_path.read_text(encoding="utf-8")

    approved_assets = {
        master: "53ccee38ecb372a446ebd89737070852e0d8876b04af7efdb1709e78d8553621",
        logo_path: "2c273c8ccd32d0e28073f1add47775eee4e096ea08cb5e2616c2d46f00b772f5",
        mark_path: "d076a98cf758ec7d36475e2df95664b6c6e52b7b758df5122b37cf64799f43cd",
        social_path: "03524d99264300ead258e0a585e9b87353ade80d4eba2e3faa02e280c3db9b75",
    }
    for path, approved_hash in approved_assets.items():
        payload = path.read_bytes()
        if path.suffix == ".svg":
            payload = payload.replace(b"\r\n", b"\n")
        assert hashlib.sha256(payload).hexdigest() == approved_hash, path.name
        assert approved_hash in spec
    assert 'viewBox="250 660 1000 220"' in logo
    assert 'viewBox="250 650 250 220"' in mark
    for asset, transform, clipping in (
        (logo, "matrix(0.95, 0, 0, 0.95, 254.925, 630.3)",
         "M 254.925 630.3 L 522.825 630.3 L 522.825 869.7 L 254.925 869.7 Z"),
        (mark, "matrix(0.95, 0, 0, 0.95, 237.925, 645.3)",
         "M 237.925 645.3 L 505.825 645.3 L 505.825 884.7 L 237.925 884.7 Z"),
    ):
        normalized = asset.lower()
        assert 'fill="#f3f2f2"' not in normalized
        assert 'fill="#ffffff"' not in normalized
        assert "data:image/png;base64," in normalized
        assert asset.count(transform) == 2
        assert "matrix(0.75, 0, 0, 0.75, 257.250011, 655.499924)" not in asset
        assert clipping in asset

    # Reposition only the existing wing layers; preserve every letter path,
    # including the Lambda, and the original embedded wing pixels/mask.
    ns = {"svg": "http://www.w3.org/2000/svg"}
    canonical = ET.parse(master).getroot()
    aligned = ET.fromstring(logo)
    for color in ("#48515c", "#75808c"):
        original_groups = [ET.tostring(el) for el in canonical if el.get("fill") == color]
        aligned_groups = [ET.tostring(el) for el in aligned if el.get("fill") == color]
        assert original_groups and original_groups == aligned_groups
    href = "{http://www.w3.org/1999/xlink}href"
    assert [el.get(href) for el in canonical.findall(".//svg:image", ns)] == [
        el.get(href) for el in aligned.findall(".//svg:image", ns)]

    pixels = json.loads((ROOT / "docs/brand/SKYTICAL-8BIT-master.json").read_text(encoding="utf-8"))
    assert pixels["wordmark"] == "SKYTICΛL"
    assert "11111" not in pixels["glyphs"]["Λ"]
    lockup = pixels["lockup"]
    wing_points = [(x, y) for y, row in enumerate(pixels["wing"])
                   for x, cell in enumerate(row) if cell != "."]
    wing_top = min(y for x, y in wing_points) + lockup["wingOrigin"][1]
    red_top = min(y for y, row in enumerate(pixels["wing"]) if "R" in row) + lockup["wingOrigin"][1]
    assert wing_top == red_top == lockup["wordmarkOrigin"][1]

    assert png_dimensions(social_path) == (1200, 630)
    assert home.count(f'/assets/skytical-logo.svg?v={build.ASSET_VERSION}') >= 3
    assert 'data-brand-flight' in home
    assert 'data-brand-sprite' in home
    assert f'/assets/logo-flight.js?v={build.ASSET_VERSION}' in home
    assert (ROOT / "site" / "assets" / "logo-flight.js").is_file()
    assert f'/assets/skytical-mark.svg?v={build.ASSET_VERSION}' in home
    assert f'/assets/skytical-social.png?v={build.ASSET_VERSION}' in home
    assert "/assets/logo-fix.css" not in home
    assert "/assets/skytical-wing.svg" not in home
    assert "skytical-wing-overlay" not in home
    assert "skytical-logo-wrap" not in home
    assert "brightness(0) invert(1)" not in css

    print("test_logo_assets: OK")


if __name__ == "__main__":
    main()
