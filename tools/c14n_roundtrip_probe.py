#!/usr/bin/env python3
"""Probe the load-bearing assumption behind PLAN.md section 5, Tier 2.

Tier 2 claims a protected math subtree can be proven unchanged by comparing an XML
canonicalization (C14N) digest before and after a patch, and that RAW byte comparison
is the wrong basis because lxml reserialization legitimately perturbs untouched
subtrees (moved namespace declarations, self-closing forms, attribute order).

If C14N digests do NOT survive an lxml mutate-and-reserialize round trip on real OMML,
Tier 2 needs redesigning, and that is worth knowing before any other code is written.

Three scenarios, increasingly close to the real M1 operation:

  S1 parse -> reserialize -> reparse, no mutation at all
  S2 mutate a MATH-FREE paragraph's run text, then reserialize   (a today-legal patch)
  S3 mutate text in a paragraph that CONTAINS math               (the M1 operation)

Digest parameters come from `mathpatch.digest.C14N_KWARGS` so this probe tests the
configuration that actually ships.

For each, every outermost math span is digested before and after and compared under
both bases. Exit code is nonzero if C14N is unstable anywhere.

Usage: c14n_roundtrip_probe.py file.docx [file.docx ...]
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mathpatch.digest import C14N_KWARGS  # noqa: E402  the config that actually ships

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MATH_TAGS = frozenset({f"{{{M}}}oMath", f"{{{M}}}oMathPara"})


def qn(local: str) -> str:
    return f"{{{W}}}{local}"


def outermost_math(el: etree._Element):
    """Outermost math descendants in document order; never recurse into a match.

    Recursing into a match would double-count: every m:oMathPara wraps an m:oMath.
    """
    for child in el:
        if child.tag in MATH_TAGS:
            yield child
        else:
            yield from outermost_math(child)


def raw_digest(el: etree._Element) -> str:
    return hashlib.sha256(etree.tostring(el)).hexdigest()


def c14n_digest(el: etree._Element) -> str:
    """Uses mathpatch.digest.C14N_KWARGS, not a local default.

    An earlier version of this probe hard-coded inclusive C14N while digest.py ships
    exclusive + with_comments, so re-running the probe did not exercise the shipping
    configuration. A probe must watch the artifact that ships.
    """
    return hashlib.sha256(etree.tostring(el, method="c14n", **C14N_KWARGS)).hexdigest()


def digests(root: etree._Element) -> tuple[list[str], list[str]]:
    raws, c14ns = [], []
    for el in outermost_math(root):
        raws.append(raw_digest(el))
        c14ns.append(c14n_digest(el))
    return raws, c14ns


def first_run_with_text(p: etree._Element) -> etree._Element | None:
    for r in p:
        if r.tag != qn("r"):
            continue
        for t in r.iter(qn("t")):
            if t.text:
                return t
    return None


def pick_paragraph(root: etree._Element, *, with_math: bool) -> etree._Element | None:
    for p in root.iter(qn("p")):
        has = any(el.tag in MATH_TAGS for el in p.iter())
        if has is with_math and first_run_with_text(p) is not None:
            return p
    return None


def roundtrip(root: etree._Element) -> etree._Element:
    """Exactly what the engine does to a part: serialize the mutated tree, reparse it."""
    return etree.fromstring(etree.tostring(root))


def scenario(raw: bytes, name: str, mutate) -> dict:
    root = etree.fromstring(raw)
    before_raw, before_c14n = digests(root)
    note = mutate(root) if mutate else "no mutation"
    if note is None:
        return {"name": name, "skipped": "no suitable paragraph"}
    after_raw, after_c14n = digests(roundtrip(root))

    if len(before_c14n) != len(after_c14n):
        return {"name": name, "note": note, "fatal": f"span count changed "
                f"{len(before_c14n)} -> {len(after_c14n)}"}
    return {
        "name": name,
        "note": note,
        "spans": len(before_c14n),
        "raw_changed": sum(a != b for a, b in zip(before_raw, after_raw)),
        "c14n_changed": sum(a != b for a, b in zip(before_c14n, after_c14n)),
    }


def mutate_mathfree(root):
    p = pick_paragraph(root, with_math=False)
    if p is None:
        return None
    t = first_run_with_text(p)
    t.text = t.text + " PROBE"
    return "edited run text in a math-free paragraph"


def mutate_mathpara(root):
    p = pick_paragraph(root, with_math=True)
    if p is None:
        return None
    t = first_run_with_text(p)
    t.text = t.text + " PROBE"
    return "edited run text in a paragraph CONTAINING math"


def main(argv: list[str]) -> int:
    paths = argv[1:]
    if not paths:
        print(__doc__)
        return 2

    unstable = False
    for path in paths:
        try:
            with zipfile.ZipFile(path) as z:
                raw = z.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            print(f"!! {os.path.basename(path)}: {exc}", file=sys.stderr)
            continue

        print(f"\n{os.path.basename(path)}")
        for name, mut in (
            ("S1 no mutation", None),
            ("S2 math-free paragraph edited", mutate_mathfree),
            ("S3 math-bearing paragraph edited", mutate_mathpara),
        ):
            r = scenario(raw, name, mut)
            if "skipped" in r:
                print(f"  {r['name']:34s} SKIPPED ({r['skipped']})")
                continue
            if "fatal" in r:
                print(f"  {r['name']:34s} FATAL: {r['fatal']}")
                unstable = True
                continue
            verdict = "C14N STABLE" if r["c14n_changed"] == 0 else "C14N UNSTABLE"
            if r["c14n_changed"]:
                unstable = True
            print(f"  {r['name']:34s} spans={r['spans']:4d}"
                  f"  raw-changed={r['raw_changed']:4d}"
                  f"  c14n-changed={r['c14n_changed']:4d}   {verdict}")

    print()
    if unstable:
        print("RESULT: C14N is NOT stable under lxml round trip -> PLAN.md section 5 Tier 2")
        print("        needs redesign (consider raw-XML splicing of the target part).")
        return 1
    print("RESULT: C14N digests of untouched math subtrees survive an lxml")
    print("        mutate-and-reserialize round trip. PLAN.md section 5 Tier 2 stands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
