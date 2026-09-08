#!/usr/bin/env python3
"""Exercise the M2a mutation on every real `m:t` in the corpus.

The unit tests use synthetic equations. This runs the same code against real ones -- with
their real formatting, which is 72% of what is in them (PLAN.md F16) and exactly what a
source-preserving writer must not disturb.

For every non-empty `m:t` in every outermost math span:

    swap its text for a marker, with the correct preimage, then check
      - the skeleton digest is unchanged  (nothing but that text moved)
      - the target now holds the new text
      - patch_text is unchanged           (math is zero width in the text stream)
      - the math boundaries are unchanged
      - every OTHER span's identity is unchanged
      - the edited span's identity DID change
      - xml:space is declared whenever the text needs it or the original had it
      - a stale DIGEST alone is refused (isolated from the text check)
      - a stale preimage on the same target is refused

Both of the last two exist because mutation testing showed this tool passing without
them: dropping xml:space entirely, and disabling the preimage digest check, each left
this run green. The unit suite caught both, but a tool whose verdict depends on another
suite being sound is not self-sufficient.

Then restore and move on, so each target is exercised against a pristine equation.
Reports aggregate counts and character-class coverage -- no manuscript content beyond
mathematical symbol counts.

Usage: edit_acceptance.py FILE.docx [FILE.docx ...]
"""

from __future__ import annotations

import copy
import glob
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lxml import etree  # noqa: E402

from mathpatch import (  # noqa: E402
    MathTextEdit,
    PreimageMismatch,
    apply_math_text_edit,
    math_identity,
    project,
    skeleton_digest,
    span_digest,
    text_targets,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def parse_hardened(xml: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        recover=False, huge_tree=False, remove_comments=False,
    )
    root = etree.fromstring(xml, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("refused: DOCTYPE")
    return root


def main(argv: list[str]) -> int:
    paths = argv[1:] or sorted(glob.glob("*.docx"))
    if not paths:
        print(__doc__)
        return 2

    counts: Counter = Counter()
    classes: Counter = Counter()
    failures: list[str] = []

    for path in paths:
        try:
            with zipfile.ZipFile(path) as z:
                root = parse_hardened(z.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
            print(f"!! {os.path.basename(path)}: {exc}", file=sys.stderr)
            return 1

        for original in root.iter(f"{W}p"):
            if not project(original).math_segments:
                continue
            for span_ordinal, _ in enumerate(project(original).math_segments):
                n_targets = len(text_targets(project(original).math_segments[span_ordinal]))
                for text_ordinal in range(n_targets):
                    # a pristine copy per target
                    p = copy.deepcopy(original)
                    proj = project(p)
                    span = proj.math_segments[span_ordinal]
                    target = text_targets(span)[text_ordinal]
                    old = target.text
                    counts["targets exercised"] += 1
                    for ch in old:
                        classes["non-ASCII" if ord(ch) > 127 else "ASCII"] += 1
                    if target.element.get(XML_SPACE):
                        counts["with xml:space"] += 1

                    before_patch_text = proj.patch_text
                    before_boundaries = proj.math_boundaries()
                    before_others = [
                        math_identity(s)
                        for i, s in enumerate(proj.math_segments)
                        if i != span_ordinal
                    ]
                    before_identity = math_identity(span)
                    before_skeleton = skeleton_digest(span, text_ordinal)
                    digest_before = span_digest(span)
                    had_space = target.element.get(XML_SPACE) is not None

                    # isolate the digest condition: correct text, bogus digest
                    digest_isolated = False
                    try:
                        apply_math_text_edit(
                            copy.deepcopy(p),
                            MathTextEdit(span_ordinal, text_ordinal, old, "0" * 64, "Q"),
                        )
                    except PreimageMismatch as exc:
                        digest_isolated = "digest" in str(exc).lower()
                    except Exception:
                        digest_isolated = False

                    # Vary the replacement shape. Only ever appending a character left
                    # shorter, whitespace-padded and same-length swaps unexercised.
                    shape = counts["targets exercised"] % 4
                    if shape == 0:
                        new = old + "′"                 # longer, real math char
                    elif shape == 1:
                        new = old[:-1] or "Z"           # shorter (or minimal)
                    elif shape == 2:
                        new = " " + old.strip() + " "   # whitespace-padded
                    else:
                        new = "Z" * len(old)            # same length, different text
                    if new == old:
                        new = old + "″"
                    classes[f"shape:{shape}"] += 1
                    try:
                        receipt = apply_math_text_edit(
                            p,
                            MathTextEdit(span_ordinal, text_ordinal, old, digest_before, new),
                        )
                    except Exception as exc:  # noqa: BLE001 -- any failure is a finding
                        counts["APPLY FAILED"] += 1
                        failures.append(f"{os.path.basename(path)}: apply raised {exc!r}")
                        continue

                    after = project(p)
                    span_after = after.math_segments[span_ordinal]
                    problems = []
                    if receipt.skeleton_digest_after != before_skeleton:
                        problems.append("skeleton digest moved")
                    if text_targets(span_after)[text_ordinal].text != new:
                        problems.append("target text not set")
                    if after.patch_text != before_patch_text:
                        problems.append("patch_text changed")
                    if after.math_boundaries() != before_boundaries:
                        problems.append("boundaries changed")
                    others_after = [
                        math_identity(s)
                        for i, s in enumerate(after.math_segments)
                        if i != span_ordinal
                    ]
                    if others_after != before_others:
                        problems.append("another span's identity changed")
                    if math_identity(span_after) == before_identity:
                        problems.append("edited span's identity did NOT change")
                    edited = text_targets(span_after)[text_ordinal].element
                    needs_space = new != new.strip()
                    if (needs_space or had_space) and edited.get(XML_SPACE) != "preserve":
                        problems.append("xml:space not declared when required")
                    if not digest_isolated:
                        problems.append("a stale span digest alone was not refused")
                    try:
                        apply_math_text_edit(
                            p,
                            MathTextEdit(span_ordinal, text_ordinal, old, digest_before, "X"),
                        )
                        problems.append("stale preimage was NOT refused")
                    except PreimageMismatch:
                        pass
                    except Exception:  # a different refusal is still a refusal
                        pass

                    if problems:
                        counts["VIOLATION"] += 1
                        failures.append(
                            f"{os.path.basename(path)}: " + "; ".join(problems)
                        )
                    else:
                        counts["verified"] += 1

    print(f"\n{'metric':30s} {'count':>8s}")
    for key in ("targets exercised", "verified", "VIOLATION", "APPLY FAILED",
                "with xml:space"):
        print(f"{key:30s} {counts[key]:8d}")
    print(f"\ncharacters exercised: {dict(classes)}")
    if failures:
        print(f"\n{len(failures)} failure(s):")
        for f in failures[:10]:
            print(f"  {f}")
    bad = counts["VIOLATION"] + counts["APPLY FAILED"]
    if bad or counts["verified"] == 0:
        print("\nEDIT ACCEPTANCE: FAILED")
        return 1
    print(f"\nEDIT ACCEPTANCE: PASSED -- {counts['verified']} real m:t targets mutated, "
          "each leaving everything else in its equation byte-identical under C14N.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
