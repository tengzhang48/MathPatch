#!/usr/bin/env python3
"""M2c: produce a real .docx with one equation changed, and check everything checkable.

Everything until now has operated on XML in memory. This writes a file, and then runs
every consumer available on this machine against it. What it CANNOT do is open Word --
so it does not claim to. It prints exactly what a human still has to confirm.

Checks performed:

  package     the part list is identical, and every part except word/document.xml is
              payload-identical byte for byte
  wellformed  every XML part still parses under the hardened parser
  reader      the result reopens with python-docx, which is the library ArtifactCert
              itself uses to reread a patched document
  content     only the target paragraph's C14N digest changed, out of all of them
  equation    the target m:t holds the new text; the span's skeleton digest is
              unchanged, so nothing else inside the equation moved; the span count and
              every other span's identity are unchanged
  rels        every relationship id referenced in document.xml resolves in the rels part

Usage:
    make_demo_docx.py SOURCE.docx --locator body/p/27 --span 3 --target 5 --new m
                      [--out OUT.docx]
    make_demo_docx.py SOURCE.docx --list          # show addressable equations
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lxml import etree  # noqa: E402

from mathpatch import (  # noqa: E402
    MathTextEdit,
    apply_math_text_edit,
    digest,
    math_identity,
    project,
    skeleton_digest,
    span_digest,
    text_targets,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
DOC = "word/document.xml"


def parse_hardened(xml: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        recover=False, huge_tree=False, remove_comments=False,
    )
    root = etree.fromstring(xml, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("refused: DOCTYPE")
    return root


def paragraphs(root):
    """ArtifactCert's own addressing, so a locator here means what it means there."""
    sys.path.insert(0, os.environ.get("ARTIFACTCERT_SRC", ""))
    try:
        from artifactcert.docx_manifest import enumerate_paragraphs
        return dict(enumerate_paragraphs(root.find(f"{W}body")))
    except ImportError:
        body = root.find(f"{W}body")
        return {f"body/p/{i}": p
                for i, p in enumerate(el for el in body if el.tag == f"{W}p")}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--locator")
    ap.add_argument("--span", type=int, default=0)
    ap.add_argument("--target", type=int)
    ap.add_argument("--new")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv[1:])

    with zipfile.ZipFile(args.source) as z:
        original_bytes = {name: z.read(name) for name in z.namelist()}
        infos = z.infolist()
    root = parse_hardened(original_bytes[DOC])
    paras = paragraphs(root)

    if args.list:
        shown = 0
        for locator, p in paras.items():
            for si, span in enumerate(project(p).math_segments):
                targets = text_targets(span)
                if not targets:
                    continue
                print(f"{locator:16s} span {si}: {[t.text for t in targets]}")
                shown += 1
                if shown >= 40:
                    return 0
        return 0

    if not (args.locator and args.target is not None and args.new):
        ap.error("--locator, --target and --new are required unless --list")

    p = paras.get(args.locator)
    if p is None:
        print(f"no paragraph at {args.locator}", file=sys.stderr)
        return 2

    before_digests = {loc: digest(el) for loc, el in paras.items()}
    proj = project(p)
    span = proj.math_segments[args.span]
    target = text_targets(span)[args.target]
    other_identities = [math_identity(s) for i, s in enumerate(proj.math_segments)
                        if i != args.span]
    skeleton_before = skeleton_digest(span, args.target)

    print(f"source     {os.path.basename(args.source)}")
    print(f"equation   {args.locator} span {args.span}: "
          f"{[t.text for t in text_targets(span)]}")
    print(f"change     m:t #{args.target}  {target.text!r} -> {args.new!r}\n")

    receipt = apply_math_text_edit(
        p,
        MathTextEdit(args.span, args.target, target.text, span_digest(span), args.new),
    )

    out_path = args.out or (
        Path(args.source).with_suffix("").name + "_mathpatch_demo.docx"
    )
    new_doc = etree.tostring(root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            # carry each entry's own metadata through, so only the payload of
            # word/document.xml differs from the source package
            zout.writestr(info, new_doc if info.filename == DOC
                          else original_bytes[info.filename])
    Path(out_path).write_bytes(buffer.getvalue())

    checks: list[tuple[str, bool, str]] = []
    with zipfile.ZipFile(out_path) as z:
        names_out = z.namelist()
        checks.append(("package: part list identical",
                       names_out == list(original_bytes), f"{len(names_out)} parts"))
        same = [n for n in names_out
                if n != DOC
                and hashlib.sha256(z.read(n)).hexdigest()
                != hashlib.sha256(original_bytes[n]).hexdigest()]
        checks.append(("package: every other part payload-identical", not same,
                       "all unchanged" if not same else f"differs: {same[:3]}"))
        bad_xml = []
        for name in names_out:
            if name.endswith(".xml") or name.endswith(".rels"):
                try:
                    parse_hardened(z.read(name))
                except Exception as exc:  # noqa: BLE001
                    bad_xml.append(f"{name}: {exc}")
        checks.append(("wellformed: every XML part parses", not bad_xml,
                       "ok" if not bad_xml else str(bad_xml[:2])))
        out_root = parse_hardened(z.read(DOC))
        try:
            rels = parse_hardened(z.read("word/_rels/document.xml.rels"))
            declared = {r.get("Id") for r in rels}
            used = {v for el in out_root.iter() for k, v in el.attrib.items()
                    if k.startswith(R)}
            missing = used - declared
            checks.append(("rels: every referenced id resolves", not missing,
                           f"{len(used)} used" if not missing else str(list(missing)[:3])))
        except KeyError:
            checks.append(("rels: relationships part present", False, "missing"))

    try:
        import docx  # the library ArtifactCert rereads a patched document with
        document = docx.Document(out_path)
        n = len(document.paragraphs)
        checks.append(("reader: python-docx reopens it", True, f"{n} body paragraphs"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("reader: python-docx reopens it", False, repr(exc)))

    out_paras = paragraphs(out_root)
    changed = [loc for loc, el in out_paras.items()
               if before_digests.get(loc) != digest(el)]
    checks.append(("content: only the target paragraph changed",
                   changed == [args.locator], f"changed: {changed[:3]}"))

    after_proj = project(out_paras[args.locator])
    after_span = after_proj.math_segments[args.span]
    checks.append(("equation: span count unchanged",
                   len(after_proj.math_segments) == len(proj.math_segments),
                   f"{len(after_proj.math_segments)} spans"))
    checks.append(("equation: target holds the new text",
                   text_targets(after_span)[args.target].text == args.new,
                   repr(text_targets(after_span)[args.target].text)))
    checks.append(("equation: skeleton digest unchanged (nothing else moved)",
                   skeleton_digest(after_span, args.target) == skeleton_before,
                   skeleton_before[:12] + "..."))
    checks.append(("equation: every other span's identity unchanged",
                   [math_identity(s) for i, s in enumerate(after_proj.math_segments)
                    if i != args.span] == other_identities, ""))

    width = max(len(name) for name, _, _ in checks)
    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name:{width}s}  {detail}")

    print(f"\nwrote {out_path}  ({os.path.getsize(out_path)} bytes)")
    print(f"receipt: {receipt.old_text!r} -> {receipt.new_text!r}, "
          f"span digest {receipt.span_digest_before[:8]} -> {receipt.span_digest_after[:8]}")
    print("\nWHAT THIS DOES NOT PROVE. No Word is available on this machine, so nothing")
    print("here establishes that Word opens the file, renders the equation correctly, or")
    print("declines to 'repair' it. A human must open it and confirm:")
    print("  1. Word opens it with no repair prompt")
    print("  2. the changed equation renders, with the new symbol in place")
    print("  3. its font, size and spacing match the surrounding equations")
    print("  4. every other equation in the document is untouched")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
