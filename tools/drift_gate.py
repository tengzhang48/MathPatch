#!/usr/bin/env python3
"""M0 completion gate: prove the projection is a STRICT EXTENSION of _para_text.

MathPatch's `patch_text` must equal ArtifactCert's `docx_manifest._para_text` exactly,
because that is the coordinate system a consumer's edit extents live in. (Replacing
`_para_text` outright is NOT the plan -- that migration is withdrawn, see PLAN.md
section 2 -- but the projection is useless at the seam unless it agrees with it.)
The property proved here:

  every paragraph -> `patch_text` is byte-identical to `_para_text`
  math paragraph  -> the derived `sentinel_text` carries exactly one sentinel per
                     discovered span, each span's sentinel offset landing on one,
                     and `sentinel_start - ordinal == patch_boundary`

Any failure means the projection and the consumer disagree about which characters an
edit extent covers -- so every protected-span offset handed across the seam would be
wrong. Exit code is nonzero on any failure.

This tool deliberately REUSES ArtifactCert's own `enumerate_paragraphs` (so the two
never disagree about which paragraphs exist) and its hardened
`opc_xml.parse_untrusted_xml` (which refuses DOCTYPEs and entity references, because
entity expansion would make canonical evidence differ from the package bytes).

Usage:
    ARTIFACTCERT_SRC=/path/to/ArtifactCert/src drift_gate.py file.docx [...]
    drift_gate.py --artifactcert-src /path/to/src file.docx [...]

Run it with an interpreter that can import artifactcert (its own .venv works).
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _load_artifactcert(src: str | None):
    candidates = [
        src,
        os.environ.get("ARTIFACTCERT_SRC"),
        "/media/volume/cpu-vm/ArtifactCert/src",
        str(Path.home() / "ArtifactCert" / "src"),
    ]
    for cand in candidates:
        if cand and (Path(cand) / "artifactcert" / "docx_manifest.py").is_file():
            sys.path.insert(0, cand)
            from artifactcert.docx_manifest import (
                enumerate_paragraphs,
                paragraph_flags,
                paragraph_text,
            )
            from artifactcert.opc_xml import parse_untrusted_xml

            return (
                enumerate_paragraphs,
                paragraph_text,
                paragraph_flags,
                parse_untrusted_xml,
                cand,
            )
    raise SystemExit(
        "cannot locate ArtifactCert's src/ -- pass --artifactcert-src or set ARTIFACTCERT_SRC"
    )


def main(argv: list[str]) -> int:
    args = argv[1:]
    src = None
    if args and args[0] == "--artifactcert-src":
        src = args[1]
        args = args[2:]
    if not args:
        print(__doc__)
        return 2

    (
        enumerate_paragraphs,
        paragraph_text,
        paragraph_flags,
        parse_untrusted_xml,
        resolved,
    ) = _load_artifactcert(src)
    from mathpatch import (
        CANONICAL_TEXT_CONTRACT_VERSION,
        MATH_TAGS,
        SENTINEL,
        SentinelCollision,
        project,
    )

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    print(f"artifactcert src : {resolved}")
    print(f"contract version : {CANONICAL_TEXT_CONTRACT_VERSION}")
    print(f"sentinel         : U+{ord(SENTINEL):04X}\n")

    grand = {"paras": 0, "mathfree": 0, "math": 0, "spans": 0, "fail": 0}
    failures: list[str] = []
    unchecked: list[str] = []  # an input we could not check is a GATE FAILURE

    for path in args:
        try:
            with zipfile.ZipFile(path) as z:
                raw = z.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            unchecked.append(f"{os.path.basename(path)}: unreadable ({exc})")
            print(f"{os.path.basename(path)[:52]:54s} UNREADABLE -- {exc}")
            continue

        try:
            root = parse_untrusted_xml(raw, part_name="word/document.xml")
        except ValueError as exc:
            unchecked.append(f"{os.path.basename(path)}: refused by parser ({exc})")
            print(f"{os.path.basename(path)[:52]:54s} PARSER REFUSED -- {exc}")
            continue
        body = root.find(f"{{{W}}}body")
        if body is None:
            unchecked.append(f"{os.path.basename(path)}: no w:body")
            print(f"{os.path.basename(path)[:52]:54s} NO w:body")
            continue

        stats = {"paras": 0, "mathfree": 0, "math": 0, "spans": 0, "fail": 0}
        for loc, p in enumerate_paragraphs(body):
            ac = paragraph_text(p)
            try:
                proj = project(p)
            except SentinelCollision as exc:
                stats["fail"] += 1
                failures.append(f"{os.path.basename(path)} {loc}: {exc}")
                stats["paras"] += 1
                continue
            stats["paras"] += 1

            # Branch on ArtifactCert's INDEPENDENT math detection, not on our own
            # span count. Branching on proj.spans would let a discovery bug
            # reclassify a math paragraph as math-free and pass silently: the gate
            # must be able to falsify the error it certifies.
            ac_has_math = "math" in paragraph_flags(p)
            if ac_has_math != bool(proj.spans):
                stats["fail"] += 1
                failures.append(
                    f"{os.path.basename(path)} {loc}: detection disagreement -- "
                    f"artifactcert says math={ac_has_math}, mathpatch found "
                    f"{len(proj.spans)} span(s)"
                )

            if not ac_has_math:
                stats["mathfree"] += 1
                if proj.patch_text != ac:
                    stats["fail"] += 1
                    failures.append(
                        f"{os.path.basename(path)} {loc}: math-free text differs\n"
                        f"    artifactcert={ac!r}\n    mathpatch   ={proj.patch_text!r}"
                    )
                continue

            stats["math"] += 1
            stats["spans"] += len(proj.spans)
            # patch_text IS the comparison now that it is the primary stream; the
            # sentinel view is derived and checked separately below.
            if proj.patch_text != ac:
                stats["fail"] += 1
                failures.append(
                    f"{os.path.basename(path)} {loc}: not a strict extension\n"
                    f"    artifactcert    ={ac!r}\n    mathpatch.patch_text={proj.patch_text!r}"
                )
            if proj.sentinel_text.count(SENTINEL) != len(proj.spans):
                stats["fail"] += 1
                failures.append(
                    f"{os.path.basename(path)} {loc}: {len(proj.spans)} spans but "
                    f"{proj.sentinel_text.count(SENTINEL)} sentinels"
                )
            # Hold strong references while comparing: id() on a collected lxml
            # proxy can be reused by a new proxy for a different node.
            covered_els = [d for s in proj.spans for d in s.element.iter()]
            all_els = list(p.iter())
            covered = {id(d) for d in covered_els}
            uncovered = [
                el for el in all_els if el.tag in MATH_TAGS and id(el) not in covered
            ]
            if uncovered:
                stats["fail"] += 1
                failures.append(
                    f"{os.path.basename(path)} {loc}: {len(uncovered)} math element(s) "
                    "neither a span nor inside one -- discovery is not total"
                )

            for span in proj.spans:
                if span.sentinel_start - span.ordinal != span.patch_boundary:
                    stats["fail"] += 1
                    failures.append(
                        f"{os.path.basename(path)} {loc}: span {span.ordinal} sentinel/patch "
                        f"coordinates disagree ({span.sentinel_start} - {span.ordinal} != "
                        f"{span.patch_boundary})"
                    )
                if proj.sentinel_text[span.start : span.end] != SENTINEL:
                    stats["fail"] += 1
                    failures.append(
                        f"{os.path.basename(path)} {loc}: span {span.ordinal} at "
                        f"[{span.start},{span.end}) does not land on a sentinel"
                    )

        print(f"{os.path.basename(path)[:52]:54s} paras={stats['paras']:5d} "
              f"math-free={stats['mathfree']:5d} math={stats['math']:4d} "
              f"spans={stats['spans']:4d} FAIL={stats['fail']:3d}")
        for k in grand:
            grand[k] += stats[k]

    print(f"\n{'TOTAL':54s} paras={grand['paras']:5d} math-free={grand['mathfree']:5d} "
          f"math={grand['math']:4d} spans={grand['spans']:4d} FAIL={grand['fail']:3d}")

    if unchecked:
        print(f"\n{len(unchecked)} input(s) NOT CHECKED:")
        for u in unchecked:
            print(f"  {u}")
        print("\nM0 GATE: FAILED -- an input that cannot be checked is not a pass.")
        return 1

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for f in failures[:20]:
            print(f"  {f}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")
        print("\nM0 GATE: FAILED")
        return 1

    print("\nM0 GATE: PASSED -- the projection is a strict extension of _para_text on")
    print("         every paragraph of this corpus, differing only in sentinel positions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
