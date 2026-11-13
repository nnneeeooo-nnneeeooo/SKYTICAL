"""Rebuild the optically aligned classic lockup from the canonical master.

SVG generation needs only Python. --social additionally uses Node.js + Sharp;
--sharp-module can point to an existing Sharp package without installing it.
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[2]
WING_TRANSFORM = "matrix(0.95, 0, 0, 0.95, 254.925, 630.3)"
WING_CLIP = "M 254.925 630.3 L 522.825 630.3 L 522.825 869.7 L 254.925 869.7 Z"


def png_pixels(payload: bytes) -> tuple[int, int, int, bytes]:
    """Decode the master's non-interlaced, 8-bit PNGs without resampling."""
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    position, compressed = 8, bytearray()
    while position < len(payload):
        size = struct.unpack(">I", payload[position:position + 4])[0]
        kind = payload[position + 4:position + 8]
        data = payload[position + 8:position + 8 + size]
        if kind == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            assert (depth, compression, filtering, interlace) == (8, 0, 0, 0)
            channels = {0: 1, 2: 3, 6: 4}[color]
        elif kind == b"IDAT":
            compressed.extend(data)
        position += size + 12
    raw = zlib.decompress(compressed)
    stride = width * channels
    assert len(raw) == (stride + 1) * height
    previous, pixels = bytearray(stride), bytearray()
    for y in range(height):
        offset = y * (stride + 1)
        method, row = raw[offset], bytearray(raw[offset + 1:offset + 1 + stride])
        assert method in range(5)
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            above = previous[x]
            corner = previous[x - channels] if x >= channels else 0
            prediction = left + above - corner
            distances = (abs(prediction - left), abs(prediction - above), abs(prediction - corner))
            paeth = (left, above, corner)[distances.index(min(distances))]
            row[x] = (row[x] + (0, left, above, (left + above) // 2, paeth)[method]) & 255
        pixels.extend(row)
        previous = row
    return width, height, channels, bytes(pixels)


def flatten_wing(source: str) -> str:
    """Bake the original grayscale mask into alpha; keep every RGB pixel."""
    root = ET.fromstring(source)
    images = root.findall('.//{http://www.w3.org/2000/svg}image')
    assert len(images) == 2
    decoded = [png_pixels(base64.b64decode(image.get('{http://www.w3.org/1999/xlink}href').split(',')[1])) for image in images]
    (width, height, channels, mask), (rw, rh, rc, rgb) = decoded
    assert (width, height, channels, rw, rh, rc) == (282, 252, 1, 282, 252, 3)
    rgba = b''.join(rgb[i * 3:i * 3 + 3] + bytes([alpha]) for i, alpha in enumerate(mask))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    scanlines = b''.join(b'\0' + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(scanlines, 9)) + chunk(b'IEND', b''))
    for tag in ('mask', 'filter', 'clipPath'):
        source = re.sub(r'<' + tag + r'\b[^>]*>.*?</' + tag + '>', '', source, flags=re.S)
    source = re.sub(r'\s+(?:mask|clip-path)="url\(#[^"]+\)"', '', source)
    source, count = re.subn(r'data:image/png;base64,[A-Za-z0-9+/=]+',
                           'data:image/png;base64,' + base64.b64encode(png).decode(), source)
    assert count == 1
    return source


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
    return flatten_wing(source)


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
