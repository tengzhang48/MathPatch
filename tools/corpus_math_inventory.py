#!/usr/bin/env python3
"""Measure the Office Math population of real .docx manuscripts.

Two tables, both baselines for MathPatch milestones (see PLAN.md):

  Table 1 (representation)  -- is the math native OMML, or legacy OLE/MathType/image?
                               If it is not native, "edit rather than regenerate" does
                               not apply and the work is out of scope.

  Table 2 (shape)           -- for each math-bearing paragraph, is there editable text
                               before the math, after it, on both sides, or neither?
                               "Both sides" is the population that needs discontiguous
                               edits with holes (PLAN.md finding F2); it is NOT
                               recoverable by a single contiguous non-intersecting span.

The "with math" percentage in Table 1 is the REFUSAL rate under
artifactcert/docx_patch/safety.py:210. It is not the recoverable rate. Table 2 is.

Coordinate note: shapes are classified from mathpatch.project()'s canonical text, the
same projection the library ships and the drift gate certifies as a strict extension of
artifactcert.docx_manifest._para_text. Earlier revisions of this tool reimplemented the
walk locally, which meant the F2 numbers driving the M1 scope decision were not covered
by the library's tests.

Usage:
    corpus_math_inventory.py [file.docx ...]
    corpus_math_inventory.py            # defaults to *.docx in $ARTIFACTCERT_DIR or cwd
"""

from __future__ import annotations

import glob
import os
import sys
import zipfile
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mathpatch import SENTINEL, project  # noqa: E402  the shipping projection

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

OMATH = f"{{{M}}}oMath"
OMATHPARA = f"{{{M}}}oMathPara"
MATH_TAGS = (OMATH, OMATHPARA)


def qn(local: str) -> str:
    return f"{{{W}}}{local}"


def parse_hardened(xml: bytes) -> etree._Element:
    """Parse without DTD/entity/network capability, refusing a DOCTYPE.

    Same rationale as ArtifactCert's `opc_xml.parse_untrusted_xml`: entity expansion
    would make the parsed evidence differ from the bytes actually in the package.
    Duplicated rather than imported so this tool needs no artifactcert dependency.
    """
    parser = etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        recover=False, huge_tree=False,
    )
    root = etree.fromstring(xml, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("refused: document.xml declares a DOCTYPE")
    return root


def has_math(p: etree._Element) -> bool:
    return any(el.tag in MATH_TAGS for el in p.iter())


def para_shape(p: etree._Element) -> str | None:
    """'both' | 'before' | 'after' | 'mathonly', or None if the paragraph has no math.

    Classification is derived from `mathpatch.project`'s canonical text -- the shipping
    projection, not a parallel reimplementation -- so these numbers are certified by
    the same tests and drift gate as the library. "Text before/after" means text in the
    coordinate space an edit actually operates in, which is what the F2 question is
    really asking.
    """
    proj = project(p)
    if not proj.spans:
        return None
    text = proj.text
    first = proj.spans[0].start
    last = proj.spans[-1].end
    before = bool(text[:first].strip())
    after = bool(text[last:].strip())
    if before and after:
        return "both"
    if before:
        return "before"
    if after:
        return "after"
    return "mathonly"


def inspect(path: str) -> dict | None:
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        print(f"  !! {os.path.basename(path)}: unreadable ({exc})", file=sys.stderr)
        return None

    text = raw.decode("utf-8", "replace")
    root = parse_hardened(raw)

    rec = {
        "name": os.path.basename(path),
        "omath": text.count("<m:oMath>") + text.count("<m:oMath "),
        "omathpara": text.count("<m:oMathPara>") + text.count("<m:oMathPara "),
        "ole": text.count("<o:OLEObject"),
        "mathtype": text.count("Equation.DSMT4") + text.count("MathType"),
        "eq3": text.count("Equation.3"),
        "paras": 0,
        "math_paras": 0,
        "both": 0, "before": 0, "after": 0, "mathonly": 0,
        "tracked": text.count("<w:ins ") + text.count("<w:del "),
    }

    for p in root.iter(qn("p")):
        proj = project(p)
        body_text = proj.text.replace(SENTINEL, "").strip()
        if not body_text and not proj.spans:
            continue
        rec["paras"] += 1
        if not proj.spans:
            continue
        rec["math_paras"] += 1
        shape = para_shape(p)
        if shape:
            rec[shape] += 1

    return rec


def main(argv: list[str]) -> int:
    paths = argv[1:]
    if not paths:
        base = os.environ.get("ARTIFACTCERT_DIR", ".")
        paths = sorted(glob.glob(os.path.join(base, "*.docx")))
    if not paths:
        print("no .docx given or found (try ARTIFACTCERT_DIR=/path)", file=sys.stderr)
        return 2

    recs = [r for r in (inspect(p) for p in paths) if r]
    if not recs:
        return 1

    print("\nTable 1 - representation (is the math natively editable?)")
    print(f"{'manuscript':44s} {'oMath':>6s} {'oMPara':>7s} {'OLE':>4s} {'MType':>6s}"
          f" {'Eq3':>4s} {'paras':>6s} {'w/math':>7s} {'ins+del':>8s}")
    for r in recs:
        pct = 100 * r["math_paras"] / r["paras"] if r["paras"] else 0.0
        print(f"{r['name'][:44]:44s} {r['omath']:6d} {r['omathpara']:7d} {r['ole']:4d}"
              f" {r['mathtype']:6d} {r['eq3']:4d} {r['paras']:6d} {pct:6.1f}%"
              f" {r['tracked']:8d}")

    legacy = sum(r["ole"] + r["mathtype"] + r["eq3"] for r in recs)
    print(f"\n  legacy (OLE/MathType/Equation.3) objects across corpus: {legacy}"
          f"  -> {'NATIVE OMML premise holds' if legacy == 0 else 'PREMISE BROKEN: see PLAN.md non-goals'}")
    print("  'w/math' is the REFUSAL rate (safety.py:210), not the recoverable rate.")

    print("\nTable 2 - shape of math paragraphs (what can actually be recovered)")
    print(f"{'manuscript':44s} {'math paras':>11s} {'both sides':>11s} {'before':>7s}"
          f" {'after':>6s} {'math-only':>10s}")
    tot = {k: 0 for k in ("math_paras", "both", "before", "after", "mathonly")}
    for r in recs:
        print(f"{r['name'][:44]:44s} {r['math_paras']:11d} {r['both']:11d}"
              f" {r['before']:7d} {r['after']:6d} {r['mathonly']:10d}")
        for k in tot:
            tot[k] += r[k]

    n = tot["math_paras"] or 1
    one_sided = tot["before"] + tot["after"]
    print(f"\n{'TOTAL':44s} {tot['math_paras']:11d} {tot['both']:11d}"
          f" {tot['before']:7d} {tot['after']:6d} {tot['mathonly']:10d}")
    print(f"\n  needs holes (text both sides):  {tot['both']:4d}  ({100*tot['both']/n:.1f}%)")
    print(f"  display-only (no prose to edit): {tot['mathonly']:4d}  ({100*tot['mathonly']/n:.1f}%)")
    print(f"  clean contiguous case:           {one_sided:4d}  ({100*one_sided/n:.1f}%)")
    print("\n  NOTE: pass only DISTINCT manuscripts; tracked-changes derivatives of the")
    print("  same paper double-count. See PLAN.md section 4.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
