"""Offline checks for SKYTICAL's canonical and generated brand assets."""
from __future__ import annotations

import hashlib
import struct
import sys
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
    logo_path = ROOT / "static" / "skytical-logo.svg"
    mark_path = ROOT / "static" / "skytical-mark.svg"
    social_path = ROOT / "static" / "skytical-social.png"
    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "site.css").read_text(encoding="utf-8")
    logo = logo_path.read_text(encoding="utf-8")
    mark = mark_path.read_text(encoding="utf-8")

    assert hashlib.sha256(master.read_bytes()).hexdigest() == (
        "53ccee38ecb372a446ebd89737070852e0d8876b04af7efdb1709e78d8553621"
    )
    assert hashlib.sha256(logo_path.read_bytes()).hexdigest() == (
        "9f273f64694d424df681b21d7450d332d363912bdb51b2c93b2e5e34c2e44f2f"
    )
    assert hashlib.sha256(mark_path.read_bytes()).hexdigest() == (
        "50ec6a6d663a1f4385d1f62ca546e0b6bdf815520b0bc3bd72cc5e1a255022e4"
    )
    assert hashlib.sha256(social_path.read_bytes()).hexdigest() == (
        "b5903b8496c802725fcdfe6072631a138c8c375a438ec1d92606c5e41f7076a5"
    )
    assert 'viewBox="250 660 1000 220"' in logo
    assert 'viewBox="250 650 250 220"' in mark
    for asset in (logo, mark):
        normalized = asset.lower()
        assert 'fill="#f3f2f2"' not in normalized
        assert 'fill="#ffffff"' not in normalized
        assert "data:image/png;base64," in normalized
        assert asset.count(
            'matrix(0.95, 0, 0, 0.95, 237.925, 645.3)'
        ) == 2
        assert "matrix(0.75, 0, 0, 0.75, 257.250011, 655.499924)" not in asset
        assert (
            "M 237.925 645.3 L 505.825 645.3 L 505.825 884.7 "
            "L 237.925 884.7 Z"
        ) in asset

    assert png_dimensions(social_path) == (1200, 630)
    assert f'/assets/skytical-logo.svg?v={build.ASSET_VERSION}' in home
    assert f'/assets/skytical-mark.svg?v={build.ASSET_VERSION}' in home
    assert f'/assets/skytical-social.png?v={build.ASSET_VERSION}' in home
    assert "brightness(0) invert(1)" not in css

    print("test_logo_assets: OK")


if __name__ == "__main__":
    main()
