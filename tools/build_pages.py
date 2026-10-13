#!/usr/bin/env python3
"""Build the GitHub Pages copy of the web app.

app/index.html is written as a Claude artifact page: it starts with <title>, <link> and
<style>, and claude.ai wraps it in the document skeleton when it's published. Served
as-is from GitHub Pages it would have no doctype (quirks mode), no charset, no language
and no viewport (phones render it at desktop width). This script adds that skeleton and
moves the leading <title>/<link>/<style> into <head>.

Usage:  python tools/build_pages.py [SOURCE] [OUT]
        (defaults: app/index.html -> _site/index.html)
"""
import os
import re
import sys

HEAD_END = re.compile(r"</style>\s*", re.I)


def build(source_html):
    if re.match(r"\s*<!doctype", source_html, re.I):
        return source_html                      # already a full document
    head, body = "", source_html
    if re.match(r"\s*<title>", source_html, re.I):
        m = HEAD_END.search(source_html)
        if m:
            head, body = source_html[:m.start()] + "</style>", source_html[m.end():]
    return ("<!doctype html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
            f"{head.strip()}\n"
            "</head>\n"
            "<body>\n"
            f"{body.strip()}\n"
            "</body>\n"
            "</html>\n")


def main(argv):
    src = argv[0] if argv else "app/index.html"
    out = argv[1] if len(argv) > 1 else "_site/index.html"
    with open(src, encoding="utf-8") as fh:
        html = build(fh.read())
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
