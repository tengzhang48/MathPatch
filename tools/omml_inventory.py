#!/usr/bin/env python3
"""Inventory the OMML actually present in real manuscripts, to scope the reader.

OMML's spec is large. The reader does not have to cover it -- it has to cover what these
manuscripts contain, in the order they contain it. Same move as
`corpus_math_inventory.py` for the M0 premise: measure before building.

Reports element frequencies, attribute usage, nesting depth and per-span size across
every outermost math span MathPatch discovers. Aggregate counts only -- no manuscript
content, except mathematical operator/identifier characters, which are needed to size
the symbol problem.

Usage: omml_inventory.py FILE.docx [FILE.docx ...]
"""

from __future__ import annotations

import glob
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lxml import etree  # noqa: E402

from mathpatch import M_NS, project  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def parse_hardened(xml: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        recover=False, huge_tree=False, remove_comments=False,
    )
    root = etree.fromstring(xml, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("refused: DOCTYPE")
    return root


def local(tag) -> str:
    if not isinstance(tag, str):
        return "<non-element>"
    return etree.QName(tag).localname if tag.startswith("{") else tag


def ns_of(tag) -> str:
    if not isinstance(tag, str) or not tag.startswith("{"):
        return "?"
    uri = tag[1:].split("}")[0]
    return {M_NS: "m", W[1:-1]: "w"}.get(uri, uri.rsplit("/", 1)[-1])


def main(argv: list[str]) -> int:
    paths = argv[1:] or sorted(glob.glob("*.docx"))
    if not paths:
        print(__doc__)
        return 2

    elements: Counter = Counter()
    attributes: Counter = Counter()
    foreign: Counter = Counter()
    depths: Counter = Counter()
    sizes: list[int] = []
    spans = 0
    docs = 0
    text_chars: Counter = Counter()

    for path in paths:
        try:
            with zipfile.ZipFile(path) as z:
                root = parse_hardened(z.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
            print(f"!! {os.path.basename(path)}: {exc}", file=sys.stderr)
            return 1
        docs += 1
        for p in root.iter(f"{W}p"):
            for span in project(p).math_segments:
                spans += 1
                el = span.source_element
                n = 0
                for node in el.iter():
                    n += 1
                    tag = node.tag
                    name = f"{ns_of(tag)}:{local(tag)}"
                    elements[name] += 1
                    if ns_of(tag) not in ("m", "w"):
                        foreign[name] += 1
                    for attr in node.attrib:
                        attributes[f"{name}/@{ns_of(attr)}:{local(attr)}"] += 1
                    if local(tag) == "t" and ns_of(tag) == "m":
                        for ch in node.text or "":
                            text_chars[ch] += 1
                    d = 0
                    parent = node
                    while parent is not None and parent is not el:
                        parent = parent.getparent()
                        d += 1
                    depths[d] += 1
                sizes.append(n)

    print(f"\n{docs} document(s), {spans} outermost math spans, "
          f"{sum(sizes)} elements total")
    if sizes:
        sizes.sort()
        print(f"elements per span: min={sizes[0]} median={sizes[len(sizes)//2]} "
              f"p90={sizes[int(len(sizes)*0.9)]} max={sizes[-1]}")
    print(f"max nesting depth below a span: {max(depths) if depths else 0}")

    print(f"\n{'element':28s} {'count':>7s}  cumulative %")
    total = sum(elements.values())
    cum = 0
    for name, count in elements.most_common():
        cum += count
        print(f"{name:28s} {count:7d}  {100*cum/total:5.1f}%")

    print(f"\n{'attribute':40s} {'count':>7s}")
    for name, count in attributes.most_common(18):
        print(f"{name:40s} {count:7d}")

    print(f"\nforeign-namespace elements inside math: "
          f"{dict(foreign) if foreign else 'none'}")

    non_ascii = {c: n for c, n in text_chars.items() if ord(c) > 127}
    print(f"\nm:t characters: {sum(text_chars.values())} total, "
          f"{len(text_chars)} distinct, {len(non_ascii)} non-ASCII")
    if non_ascii:
        top = sorted(non_ascii.items(), key=lambda kv: -kv[1])[:14]
        print("  most common non-ASCII: "
              + "  ".join(f"{c!r}(U+{ord(c):04X})x{n}" for c, n in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
