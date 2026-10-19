"""Rebuild the optically aligned classic lockup from the canonical master.

SVG generation needs only Python. --social additionally uses Node.js + Sharp;
--sharp-module can point to an existing Sharp package without installing it.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WING_TRANSFORM = "matrix(0.95, 0, 0, 0.95, 254.925, 614.3)"
WING_CLIP = "M 254.925 614.3 L 522.825 614.3 L 522.825 853.7 L 254.925 853.7 Z"


def logo_svg() -> str:
    source = (ROOT / "docs/brand/SKYTICAL-master.svg").read_text(encoding="utf-8")
    header = ('<svg xmlns="http://www.w3.org/2000/svg" '
              'xmlns:xlink="http://www.w3.org/1999/xlink" width="1000" '
              'height="220" viewBox="250 660 1000 220" '
              'preserveAspectRatio="xMidYMid meet" role="img" '
              'aria-label="SKYTICΛL — SKYLINE TO AVIATION NEWS">')
    source = re.sub(r"<svg\b[^>]*>", lambda _: header, source, count=1)
    source, removed = re.subn(r'<rect\b[^>]*fill="#(?:ffffff|f3f2f2)"[^>]*/>', "", source)
    assert removed == 2, "Canonical background layers changed"
    previous = "matrix(0.75, 0, 0, 0.75, 257.250011, 655.499924)"
    assert source.count(previous) == 2, "Canonical wing layers changed"
    source = source.replace(previous, WING_TRANSFORM)
    source, clipped = re.subn(
        r'(<clipPath id="d61c719e8b"><path d=")[^"]+(" clip-rule="nonzero"/>)',
        lambda match: match[1] + WING_CLIP + match[2], source)
    assert clipped == 1, "Canonical wing clipping path changed"
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--social", action="store_true")
    parser.add_argument("--sharp-module", default="sharp")
    args = parser.parse_args()
    logo = ROOT / "static/skytical-logo.svg"
    logo.write_text(logo_svg(), encoding="utf-8", newline="\n")
    print(f"Generated {logo.relative_to(ROOT)}")
    if args.social:
        script = """
const sharp = require(process.argv[1]);
(async () => {
  const logo = await sharp(process.argv[2]).png().toBuffer();
  await sharp({create:{width:1200,height:630,channels:3,background:'#F3F2F2'}})
    .composite([{input:logo,left:100,top:205}]).png().toFile(process.argv[3]);
})().catch(e => { console.error(e.message); process.exitCode = 1; });
"""
        social = ROOT / "static/skytical-social.png"
        subprocess.run(["node", "-e", script, args.sharp_module,
                        str(logo), str(social)], check=True)
        print(f"Generated {social.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
