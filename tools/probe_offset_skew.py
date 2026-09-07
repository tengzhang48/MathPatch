#!/usr/bin/env python3
"""Regression probe for PLAN.md F7: the hyperlink/anchor coordinate skew.

F7 is RETRACTED as a finding. ArtifactCert fixed this on 2026-08-24, before MathPatch
existed; the original report here was read off a tree diverged by 195 commits. Against
a current tree this script should print "F7 NOT reproduced".

It is kept for two reasons: it is a real regression check for a real past defect, and
it is the standing reminder of why this project fetches and quotes a commit hash before
claiming what ArtifactCert "currently" does (see PLAN.md, "Reading the ArtifactCert
tree").

The defect, as it existed BEFORE the 2026-08-24 fix:

  docx_manifest._para_text      concatenates DIRECT w:r children only.
                                Hyperlink text contributes NOTHING.
  safety.analyze_paragraph      re-walked the paragraph and, for w:hyperlink/w:smartTag,
                                advanced its offset BY that element's text width.

  At the pinned commit safety.analyze_paragraph computes those boundaries in canonical
  coordinates instead, so neither outcome below should occur.

engine.apply_patches locates the anchor in the FIRST space
(`text = paragraph_text(p); span_start = text.index(anchor)`) and then hands those
offsets to the SECOND. For a paragraph with a text-carrying hyperlink followed by
editable text, every fragment offset after the hyperlink is shifted by its width.

The two observable outcomes it produced, either of which reappearing is a regression:

  A. the shifted hyperlink interval still overlaps the edit span -> FALSE REFUSAL
  B. the shift moves it clear of the edit span -> NO refusal, and the patch
     overwrites the WRONG CHARACTERS

Usage: ARTIFACTCERT_SRC=/path/to/ArtifactCert/src probe_offset_skew.py
Run with an interpreter that can import artifactcert.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load():
    for cand in (os.environ.get("ARTIFACTCERT_SRC"),
                 "/media/volume/cpu-vm/ArtifactCert/src",
                 str(Path.home() / "ArtifactCert" / "src")):
        if cand and (Path(cand) / "artifactcert" / "docx_manifest.py").is_file():
            sys.path.insert(0, cand)
            return cand
    raise SystemExit("set ARTIFACTCERT_SRC to ArtifactCert's src/")


def case(label: str, link_text: str) -> bool:
    from lxml import etree

    from artifactcert.docx_manifest import paragraph_text
    from artifactcert.docx_patch import safety
    from artifactcert.docx_patch.engine import _apply_to_runs

    p = etree.fromstring(
        f'<w:p xmlns:w="{W}">'
        f"<w:r><w:t>AAA </w:t></w:r>"
        f"<w:hyperlink><w:r><w:t>{link_text}</w:t></w:r></w:hyperlink>"
        f"<w:r><w:t> BBB target CCC</w:t></w:r>"
        f"</w:p>"
    )
    text = paragraph_text(p)
    anchor = "target"
    s = text.index(anchor)
    e = s + len(anchor)

    print(f"\n{label}")
    print(f"  hyperlink text        {link_text!r} ({len(link_text)} chars of skew)")
    print(f"  paragraph_text()      {text!r}")
    print(f"  anchor {anchor!r} at   [{s}, {e})")

    verdict = safety.analyze_paragraph(p, s, e)
    if not verdict.ok:
        print(f"  safety                REFUSED {verdict.refusal_code}")
        print("  OUTCOME A: false refusal -- a safe edit is rejected because the")
        print("             hyperlink interval was measured in the other space.")
        return True

    print("  safety                ok, fragments:")
    for fr in verdict.fragments:
        frag = "".join(t.text or "" for t in fr.run.findall(f"{{{W}}}t"))
        print(f"                          [{fr.start:3d},{fr.end:3d}) {frag!r}")
    _apply_to_runs(p, verdict.fragments, s, e, "<<REPLACED>>")
    after = paragraph_text(p)
    expected = text.replace(anchor, "<<REPLACED>>")
    print(f"  after patch           {after!r}")
    print(f"  expected              {expected!r}")
    if after != expected:
        print("  OUTCOME B: MIS-TARGETED -- the patch overwrote the wrong characters.")
        return True
    print("  correct")
    return False


def main() -> int:
    resolved = load()
    print(f"artifactcert src: {resolved}")
    print(__doc__.split("Usage:")[0].rstrip())
    bad = False
    bad |= case("case 1: long link, shifted interval still overlaps", "LINKTEXT")
    bad |= case("case 2: short link, shifted interval clears the span", "LINK")
    print()
    if bad:
        print("F7 REPRODUCED: the two coordinate spaces disagree.")
        print("Fix direction: derive safety's offset walk from the same projection that")
        print("produces the anchor text, rather than re-walking with different rules.")
        return 1
    print("F7 NOT reproduced: the two coordinate spaces agree in this tree.")
    print("Expected against ArtifactCert origin/main -- the fix landed 2026-08-24")
    print("(safety.py: hyperlink/smartTag boundaries in canonical coordinates).")
    print("This probe is now a REGRESSION check: a reproduction here means it came back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
