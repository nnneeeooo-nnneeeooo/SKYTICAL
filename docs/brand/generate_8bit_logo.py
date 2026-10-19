"""Regenerate the optional 8-bit brand assets using Python's standard library.

The reviewed pixel grid is derived from SKYTICAL-master.svg's embedded wing.
No fonts, image libraries, network access or SVG renderer are required.
"""
from __future__ import annotations

import binascii
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[2]
MASTER = Path(__file__).with_name("SKYTICAL-8BIT-master.json")


def wing_rects(master: dict, x: int = 0, y: int = 0) -> list[tuple]:
    rects = []
    for row_number, row in enumerate(master["wing"]):
        start = 0
        while start < len(row):
            token = row[start]
            end = start + 1
            while end < len(row) and row[end] == token:
                end += 1
            if token != ".":
                rects.append((x + start, y + row_number, end - start, 1,
                              master["palette"][token]))
            start = end
    return rects


def text_rects(master: dict, text: str, x: int, y: int,
               scale: int, color: str) -> list[tuple]:
    rects = []
    for letter in text:
        for row_number, row in enumerate(master["glyphs"][letter]):
            for column, bit in enumerate(row):
                if bit == "1":
                    rects.append((x + column * scale, y + row_number * scale,
                                  scale, scale, color))
        x += (len(master["glyphs"][letter][0]) + 1) * scale
    return rects


def svg(width: int, height: int, rects: list[tuple], title: str) -> str:
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"',
             f'     viewBox="0 0 {width} {height}" shape-rendering="crispEdges"',
             '     role="img" aria-labelledby="title">',
             f'  <title id="title">{title}</title>',
             '  <desc>Optional pixel-art derivative of the SKYTICAL master; red, orange and gold swept wing. Transparent background. No external fonts.</desc>']
    for x, y, w, h, color in rects:
        lines.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>')
    return "\n".join(lines + ["</svg>", ""])


def png(width: int, height: int, rects: list[tuple], scale: int = 4) -> bytes:
    """Encode an integer-scaled, transparent RGBA PNG without resampling."""
    width, height = width * scale, height * scale
    pixels = bytearray(width * height * 4)
    for x, y, w, h, color in rects:
        rgba = bytes.fromhex(color.lstrip("#")) + b"\xff"
        scan = rgba * (w * scale)
        for line in range(y * scale, (y + h) * scale):
            offset = (line * width + x * scale) * 4
            pixels[offset:offset + len(scan)] = scan
    raw = b"".join(b"\x00" + pixels[y * width * 4:(y + 1) * width * 4]
                   for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def generated_assets() -> dict[str, bytes]:
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    layout = master["lockup"]
    variants = {
        "skytical-mark-8bit": (44, 32, wing_rects(master), "SKYTICAL — 8-bit swept-wing mark"),
    }
    for suffix, ink, secondary in (("", "#48515C", "#75808C"),
                                   ("-dark", "#F1EDD7", "#ADC4DE")):
        rects = (wing_rects(master, *layout["wingOrigin"])
                 + text_rects(master, master["wordmark"], *layout["wordmarkOrigin"], 3, ink)
                 + text_rects(master, master["tagline"], *layout["taglineOrigin"], 1, secondary))
        variants["skytical-logo-8bit" + suffix] = (
            *layout["canvas"], rects, "SKYTICΛL — SKYLINE TO AVIATION NEWS — 8-bit")
    files = {}
    for name, (width, height, rects, title) in variants.items():
        files[name + ".svg"] = svg(width, height, rects, title).encode("utf-8")
        files[name + ".png"] = png(width, height, rects)
    return files


def main() -> None:
    for name, payload in generated_assets().items():
        target = ROOT / "static" / name
        target.write_bytes(payload)
        print(f"Generated {target.relative_to(ROOT)} ({len(payload)} bytes)")


if __name__ == "__main__":
    main()
