"""Display-only Chinese spacing; preserve source records and HTML syntax."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

CJK = r"\u2e80-\u9fff\uf900-\ufaff\uff01-\uff60\U00020000-\U000323af"
SPACES = re.compile(rf"(?<=[{CJK}]) +| +(?=[{CJK}])")
BLOCKS = set("html head body address article aside blockquote br button dd details dialog div dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol option p section summary table tbody td th thead tr ul".split())
SKIP = {"script", "style", "pre", "code", "textarea"}
TEXT_ATTRS = {"alt", "title", "placeholder", "aria-label", "aria-description"}
META_TEXT = {"description", "og:title", "og:description", "og:image:alt",
             "twitter:title", "twitter:description", "twitter:image:alt"}
ATTR = re.compile(r'''([\w:-]+)(\s*=\s*)(["'])(.*?)\3''', re.DOTALL)


def compact_text(text: str) -> str:
    return SPACES.sub("", text)


class _DisplaySpacing(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [m.end() for m in re.finditer("\n", source)]
        self.edits = []
        self.run = []
        self.skipped = []

    def source_offset(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def flush(self):
        text = "".join(value for _, _, value in self.run)
        removed = set()
        for match in SPACES.finditer(text):
            removed.update(range(match.start(), match.end()))
        cursor = 0
        if removed:
            for start, raw, value in self.run:
                cleaned = "".join(c for i, c in enumerate(value)
                                  if cursor + i not in removed)
                if cleaned != value:
                    # Entities are individual tokens; untouched ones stay verbatim.
                    self.edits.append((start, start + len(raw), cleaned))
                cursor += len(value)
        self.run.clear()

    def handle_starttag(self, tag, attrs):
        if tag in BLOCKS or tag in SKIP:
            self.flush()
        if self.skipped:
            if tag in SKIP:
                self.skipped.append(tag)
            return
        raw = self.get_starttag_text()
        values = dict(attrs)
        meta_text = tag == "meta" and (
            values.get("name") or values.get("property")) in META_TEXT

        def replace(match):
            name, equals, quote, value = match.groups()
            if name.lower() not in TEXT_ATTRS and not (
                    meta_text and name.lower() == "content"):
                return match.group(0)
            decoded = html.unescape(value)
            cleaned = compact_text(decoded)
            if cleaned == decoded:
                return match.group(0)
            return name + equals + quote + html.escape(cleaned, quote=True) + quote

        cleaned = ATTR.sub(replace, raw)
        if cleaned != raw:
            start = self.source_offset()
            self.edits.append((start, start + len(raw), cleaned))
        if tag in SKIP:
            self.skipped.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in SKIP and self.skipped:
            self.skipped.pop()

    def handle_endtag(self, tag):
        if self.skipped:
            if tag == self.skipped[-1]:
                self.skipped.pop()
            return
        if tag in BLOCKS or tag in SKIP:
            self.flush()

    def handle_data(self, data):
        if not self.skipped:
            self.run.append((self.source_offset(), data, data))

    def handle_entityref(self, name):
        if not self.skipped:
            raw = "&" + name + ";"
            self.run.append((self.source_offset(), raw, html.unescape(raw)))

    def handle_charref(self, name):
        self.handle_entityref("#" + name)


def compact_html(source: str) -> str:
    parser = _DisplaySpacing(source)
    parser.feed(source)
    parser.close()
    parser.flush()
    # Apply non-overlapping edits without reserializing attributes or scripts.
    chunks = []
    cursor = 0
    for start, end, replacement in sorted(parser.edits):
        chunks.extend((source[cursor:start], replacement))
        cursor = end
    chunks.append(source[cursor:])
    return "".join(chunks)
