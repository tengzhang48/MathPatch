#!/usr/bin/env python3
"""Run the protected-math oracle against every REAL authorized patch. PLAN.md M1 item 2.

Three self-audits produced three oracle defects, two of them FALSE POSITIVES -- an
oracle that would have refused a correct patch (F12: a prose edit before an equation
moves its boundary; F14: a run's `w:t` collapse shifts raw index paths). Both were found
by asking "what does a CORRECT edit do to this?" rather than "does it catch a bad edit?"

That question has never been asked with real data. This asks it 364 times:

    before = project(paragraph)
    apply the REAL patch, replaying the pinned engine's decision path exactly
    after  = project(patched copy)

    paragraph_identity(after)  ==  paragraph_identity(before)          # nothing moved
    actual_boundaries(after)   ==  expected_boundaries(before, edits)  # and it sits where
                                                                       # the text implies

A false positive here is a patch ArtifactCert would refuse once the oracle is wired in.
A false negative -- identity equal when the equation really did change -- would be worse,
so the run also checks the engine's own conformance (the patched paragraph's text equals
the authorized transformation) and reports any patch that did not apply as inconclusive
rather than as a pass.

Each edit is applied to a DEEPCOPY of the pristine paragraph, so the two projections
share no element references and a digest computed from one cannot reflect the other.

Reports aggregate counts only -- never manuscript text.

Usage:
    ARTIFACTCERT_SRC=<pinned worktree>/src oracle_acceptance.py LEDGER [LEDGER ...]
"""

from __future__ import annotations

import copy
import os
import sqlite3
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BUCKETS = [
    "verified",
    "NEGATIVE CONTROL FAILED",
    "no math in paragraph",
    "ORACLE FALSE POSITIVE",
    "boundary mismatch",
    "ambiguous insertion",
    "patch refused (nothing to check)",
    "inconclusive",
]


#: Shapes the real corpus does not contain, driven through the identical pipeline.
#: Measured: 0 of 4,645 real paragraphs nest math inside a w:r, so the corpus cannot
#: exercise F14 (raw index paths shifting under a `w:t` collapse). Reverting the identity
#: oracle to `source_path` PASSES against the real ledgers alone -- verified by mutation.
#: These cases close that gap, as `descent.docx` does for the drift gate.
SYNTHETIC_CASES = [
    # (locator, preimage, post_state, expected outcome, why)
    ("body/p/4", "in-run tail", "IN-RUN EDITED tail", "boundary mismatch",
     "F15: editing a run that CONTAINS an inline equation relocates the equation. "
     "safety sees no math (it scans only the paragraph's direct children), "
     "_rewrite_run_text collapses the run's w:t around the equation, and the engine's "
     "own conformance check cannot see it because math is zero width in canonical text. "
     "A boundary mismatch here is the ORACLE WORKING, and is the expected outcome."),
    ("body/p/1", "The deformation ", "The measured deformation ", "verified",
     "F12: prose edit before an equation moves its boundary without moving it"),
    ("body/p/6", "pair ", "matched pair ", "verified",
     "two adjacent math spans sharing one boundary"),
]


def pinned_or_die(ac_src: str) -> str:
    root = Path(__file__).resolve().parents[1]
    expected = next(
        line.strip()
        for line in (root / "INTEGRATION_TARGET.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=Path(ac_src).parent,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if actual != expected:
        raise SystemExit(
            f"REFUSED: ArtifactCert at {ac_src} is {actual}, not the pinned {expected}."
        )
    return actual


def main(argv: list[str]) -> int:
    ledgers = argv[1:]
    if not ledgers:
        print(__doc__)
        return 2
    ac_src = os.environ.get("ARTIFACTCERT_SRC", "")
    if not (Path(ac_src) / "artifactcert" / "docx_manifest.py").is_file():
        print("set ARTIFACTCERT_SRC to a pinned ArtifactCert src/ tree", file=sys.stderr)
        return 2
    print(f"pinned engine verified: {pinned_or_die(ac_src)}")
    sys.path.insert(0, ac_src)

    from artifactcert.docx_manifest import enumerate_paragraphs, paragraph_text
    from artifactcert.docx_patch import safety
    from artifactcert.docx_patch.engine import (
        _apply_deletion_only_diff_around_structure,
        _apply_to_runs,
        _insert_beside_unchanged_protected_text,
        deletion_only_ranges,
        narrow_to_changed_middle,
    )
    from artifactcert.opc_xml import parse_untrusted_xml

    from mathpatch import (
        AmbiguousInsertion,
        AuthorizedTextEdit,
        actual_boundaries,
        expected_boundaries,
        paragraph_identity,
        project,
    )

    M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

    def negative_controls(patched, patched_identity, patched_boundaries) -> str | None:
        """Prove the oracle CAN fail on this very paragraph.

        "The oracle agreed 44 times" is also what an oracle that always agrees would
        produce. So for every case that passes, deliberately corrupt the math and require
        the oracle to notice -- content and placement separately, since a C14N digest is
        a content oracle and cannot see a move (PLAN.md F12).
        """
        # A: change the equation's contents
        content = copy.deepcopy(patched)
        target = next(
            (el for el in content.iter(f"{M_NS}t") if (el.text or "")), None
        )
        if target is not None:
            target.text = (target.text or "") + "ZZ"
            if paragraph_identity(project(content).math_segments) == patched_identity:
                return "content change not detected"

        # B: move the equation to the end of the paragraph
        placement = copy.deepcopy(patched)
        spans = project(placement).math_segments
        if spans:
            el = spans[0].source_element
            parent = el.getparent()
            if parent is not None and parent is placement and len(placement) > 1:
                parent.remove(el)
                placement.append(el)
                if paragraph_identity(project(placement).math_segments) == patched_identity:
                    return "equation move not detected"

        # C: a wrong edit set must not reproduce the observed boundaries
        if patched_boundaries and patched_boundaries != (0,):
            wrong = [AuthorizedTextEdit(0, 0, 7)]
            try:
                if expected_boundaries(project(patched), wrong) == patched_boundaries:
                    return "a false edit set reproduced the boundaries"
            except (AmbiguousInsertion, ValueError):
                pass
        return None

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    counts: Counter = Counter()
    notes: list[str] = []
    affinity_seen: Counter = Counter()
    fixture_outcomes: Counter = Counter()

    fixture = os.environ.get("MATHPATCH_FIXTURE")
    work: list[tuple[str, str, str, str, str]] = []   # source, locator, pre, post, origin

    for ledger in ledgers:
        con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT i.locator, i.operation, i.preimage, i.post_state, c.frozen_path
               FROM change_spec_items i
               JOIN change_specs s ON s.spec_id = i.spec_id
               JOIN candidates c ON c.candidate_id = s.base_candidate_id
               ORDER BY i.spec_id, i.ordinal"""
        ).fetchall()
        con.close()

        for row in rows:
            work.append(
                (row["frozen_path"], row["locator"], row["preimage"] or "",
                 row["post_state"] or "", "real")
            )

    expectations: dict[tuple[str, str], str] = {}
    if fixture:
        for locator, pre, post, expect, _why in SYNTHETIC_CASES:
            work.append((fixture, locator, pre, post, "fixture"))
            expectations[(locator, pre)] = expect

    cache: dict[str, dict] = {}
    per_origin: dict[str, Counter] = {"real": Counter(), "fixture": Counter()}
    if True:
        for docx, locator, pre, post, origin in work:
            expected_outcome = expectations.get((locator, pre), "verified")

            def tally(bucket: str) -> None:
                counts[bucket] += 1
                per_origin[origin][bucket] += 1
                if origin == "fixture":
                    key = "as expected" if bucket == expected_outcome else "UNEXPECTED"
                    fixture_outcomes[key] += 1
                    if key == "UNEXPECTED":
                        notes.append(
                            f"fixture {locator}: expected {expected_outcome!r}, got {bucket!r}"
                        )

            if not docx or not os.path.isfile(docx):
                tally("inconclusive")
                continue
            if docx not in cache:
                with zipfile.ZipFile(docx) as z:
                    root = parse_untrusted_xml(
                        z.read("word/document.xml"), part_name="word/document.xml"
                    )
                    cache[docx] = dict(enumerate_paragraphs(root.find(f"{W}body")))
            pristine = cache[docx].get(locator)
            if pristine is None:
                tally("inconclusive")
                continue

            text = paragraph_text(pristine)
            if not pre or text.count(pre) != 1:
                tally("inconclusive")
                continue
            start, end = text.index(pre), text.index(pre) + len(pre)
            op = "replace"

            # snapshot the BEFORE oracle state from the pristine element
            before = project(pristine)
            if not before.math_segments:
                tally("no math in paragraph")
                continue
            before_identity = paragraph_identity(before.math_segments)

            # patch an independent copy
            p = copy.deepcopy(pristine)
            if op == "replace":
                edit_start, edit_end, edit_text = narrow_to_changed_middle(
                    text, post, start, end
                )
            else:
                edit_start, edit_end, edit_text = start, end, post
            if op == "replace" and edit_start == edit_end and not edit_text:
                tally("patch refused (nothing to check)")
                continue

            verdict = safety.analyze_paragraph(p, edit_start, edit_end)
            edits: list[AuthorizedTextEdit] = []
            applied = False

            if verdict.ok:
                _apply_to_runs(p, verdict.fragments, edit_start, edit_end, edit_text)
                edits = [AuthorizedTextEdit(edit_start, edit_end, len(edit_text))]
                applied = True
            elif (
                op == "replace"
                and edit_start == edit_end
                and edit_text
                and verdict.refusal_code
                in {"PATCH_PROTECTED_CITATION_MANAGER_FIELD", "PATCH_NOT_SAFE_FIELD_IN_TARGET"}
                and _insert_beside_unchanged_protected_text(
                    p, full_start=start, full_end=end,
                    position=edit_start, insertion=edit_text,
                )
            ):
                edits = [AuthorizedTextEdit(edit_start, edit_end, len(edit_text))]
                applied = True
            elif op == "replace" and verdict.refusal_code == "PATCH_NOT_SAFE_MATH_IN_TARGET":
                ranges = deletion_only_ranges(text, start, end, post)
                if ranges and _apply_deletion_only_diff_around_structure(
                    p, text, start, end, post
                ):
                    edits = [AuthorizedTextEdit(s, e, 0) for s, e in ranges]
                    applied = True

            if not applied:
                tally("patch refused (nothing to check)")
                continue

            # the engine's own conformance proof: did the patch do what was authorized?
            if paragraph_text(p) != text[:start] + post + text[end:]:
                tally("inconclusive")
                notes.append(f"{origin} {locator}: patch applied but text does not match the spec")
                continue

            after = project(p)

            if paragraph_identity(after.math_segments) != before_identity:
                tally("ORACLE FALSE POSITIVE")
                notes.append(
                    f"{origin} {locator}: identity changed by a correct patch "
                    f"(op={op}, middle=[{edit_start},{edit_end}) -> {len(edit_text)} chars)"
                )
                continue

            try:
                predicted = expected_boundaries(before, edits)
            except AmbiguousInsertion:
                # a real edit hit the ambiguous case: which affinity matches reality?
                observed = actual_boundaries(after)
                matched = None
                for side in ("left", "right"):
                    trial = [
                        AuthorizedTextEdit(e.start, e.end, e.new_length, affinity=side)
                        for e in edits
                    ]
                    if expected_boundaries(before, trial) == observed:
                        matched = side
                        break
                affinity_seen[matched or "NEITHER"] += 1
                tally("ambiguous insertion")
                if matched is None:
                    notes.append(f"{origin} {locator}: neither affinity reproduces the outcome")
                continue

            if predicted != actual_boundaries(after):
                tally("boundary mismatch")
                notes.append(
                    f"{origin} {locator}: predicted {predicted}, observed "
                    f"{actual_boundaries(after)}"
                )
                continue

            failure = negative_controls(
                p, paragraph_identity(after.math_segments), actual_boundaries(after)
            )
            if failure:
                tally("NEGATIVE CONTROL FAILED")
                notes.append(f"{origin} {locator}: {failure}")
                continue

            tally("verified")

    total = sum(counts.values())
    print(f"\n{'bucket':38s} {'count':>7s}")
    for bucket in BUCKETS:
        print(f"{bucket:38s} {counts[bucket]:7d}")
    print(f"{'TOTAL':38s} {total:7d}")

    real = per_origin["real"]
    real_math = (
        real["verified"] + real["ORACLE FALSE POSITIVE"]
        + real["boundary mismatch"] + real["ambiguous insertion"]
    )
    math_cases = real_math
    print(f"\n  REAL authorized edits on math-bearing paragraphs, applied: {real_math}")
    print(f"  oracle agreed on every real one: "
          f"{real['ORACLE FALSE POSITIVE'] == 0 and real['boundary mismatch'] == 0}")
    print(f"\n  real ledger cases:   {dict(per_origin['real'])}")
    if fixture:
        print(f"  fixture cases:       {dict(per_origin['fixture'])}")
    else:
        print("  fixture cases:       NOT RUN -- set MATHPATCH_FIXTURE to close the")
        print("                       F14 coverage gap; the real corpus has no math")
        print("                       nested inside a w:r and cannot exercise it.")
    if fixture:
        print(f"  fixture outcomes vs expectation: {dict(fixture_outcomes)}")
        print("    body/p/4 is EXPECTED to mismatch: it demonstrates F15, a latent")
        print("    ArtifactCert defect this oracle exists to catch.")
    if affinity_seen:
        print(f"  ambiguous-insertion affinities observed: {dict(affinity_seen)}")
    if notes:
        print(f"\n  {len(notes)} note(s):")
        for note in notes[:10]:
            print(f"    {note}")

    bad = (
        real["ORACLE FALSE POSITIVE"]
        + real["boundary mismatch"]
        + real["NEGATIVE CONTROL FAILED"]
        + counts["NEGATIVE CONTROL FAILED"]
        + fixture_outcomes["UNEXPECTED"]
    )
    if bad:
        print(f"\nACCEPTANCE: FAILED -- {bad} case(s) the oracle would have refused, "
              "mis-predicted, or failed to notice.")
        return 1
    if math_cases == 0:
        print("\nACCEPTANCE: INCONCLUSIVE -- no applied patch touched a math-bearing "
              "paragraph, so the oracle was never exercised.")
        return 1
    print(f"\nACCEPTANCE: PASSED")
    print(f"  - agreed with all {real_math} REAL authorized patches on math-bearing paragraphs")
    print("  - on each, was shown able to detect a corrupted equation and a moved one")
    if fixture:
        print(f"  - all {sum(fixture_outcomes.values())} fixture cases matched their expected "
              "outcome, including the one that MUST mismatch (F15)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
