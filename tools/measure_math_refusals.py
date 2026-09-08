#!/usr/bin/env python3
"""Measure what is ACTUALLY still refused around equations. PLAN.md F2, M1 item 4.

The 48.5% "text on both sides of math" figure is the population *exposed* to the
problem, not the population blocked. ArtifactCert already applies deletion-only edits
across equations. The number that decides whether generalized "holes" are worth
building is narrower:

    of real AUTHORIZED edits on math-bearing paragraphs, how many are replacements
    that cross a math boundary and cannot be expressed as deletions?

This classifies every `change_spec_items` row in a real ledger by replaying the exact
decision path of the pinned ArtifactCert engine (engine.py around line 644):

    if operation is replace:
        edit_start, edit_end, edit_text = narrow_to_changed_middle(
            text, post_state, span_start, span_end)      # <-- SAFETY FOLLOWS THIS
    verdict = safety.analyze_paragraph(p, edit_start, edit_end)
    if verdict.ok                                        -> applies directly
    elif replace and the middle is a pure insertion and the refusal is a
         citation/field one and _insert_beside_unchanged_protected_text succeeds
                                                          -> applies beside protected text
    elif replace and refusal is PATCH_NOT_SAFE_MATH_IN_TARGET and
         _apply_deletion_only_diff_around_structure(FULL span) succeeds
                                                          -> applies via decomposition
    else                                                  -> refused

The narrowing step is essential and an earlier version of this tool omitted it, which
made its answer an UPPER BOUND rather than the engine's result. Safety follows only the
characters that actually change, so a reviewer-quoted phrase may span an equation while
the changed middle does not -- "where [eq] gives the result" with only "gives"->"yields"
changing is accepted by the real engine.

Buckets reported:

    no math in paragraph          already works
    outside the math boundary     already works
    deletion around math          already works (decomposition)
    replacement crossing math     REFUSED TODAY  <- the number that matters
    refused for another reason    not a math problem
    preimage not locatable        stale spec or a coordinate this tool cannot resolve

Reports aggregate counts only -- never manuscript text.

Usage:
    ARTIFACTCERT_SRC=<pinned worktree>/src measure_math_refusals.py LEDGER [LEDGER ...]
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
    "no math in paragraph",
    "outside the math boundary",
    "deletion around math",
    "replacement crossing math",
    "refused for another reason",
    "preimage not locatable",
    "no-op (nothing changes)",
]


def load_paragraphs(docx_path: str, enumerate_paragraphs, parse_untrusted_xml):
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(docx_path) as z:
        root = parse_untrusted_xml(z.read("word/document.xml"), part_name="word/document.xml")
    body = root.find(f"{W}body")
    return dict(enumerate_paragraphs(body))


def classify_ledger(path: str, mods) -> tuple[Counter, Counter, list[str]]:
    (enumerate_paragraphs, paragraph_text, parse_untrusted_xml, safety,
     deletion_apply, insert_beside, narrow, crosses_math_boundary) = mods

    counts: Counter = Counter()
    other: Counter = Counter()
    notes: list[str] = []

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT i.locator, i.operation, i.preimage, i.post_state, c.frozen_path
        FROM change_spec_items i
        JOIN change_specs s ON s.spec_id = i.spec_id
        JOIN candidates c ON c.candidate_id = s.base_candidate_id
        ORDER BY i.spec_id, i.ordinal
        """
    ).fetchall()
    con.close()

    cache: dict[str, dict] = {}
    for row in rows:
        docx = row["frozen_path"]
        if not docx or not os.path.isfile(docx):
            counts["preimage not locatable"] += 1
            notes.append(f"missing source: {os.path.basename(str(docx))}")
            continue
        if docx not in cache:
            try:
                cache[docx] = load_paragraphs(docx, enumerate_paragraphs, parse_untrusted_xml)
            except Exception as exc:
                cache[docx] = {}
                notes.append(f"unreadable source ({exc})")
        paras = cache[docx]
        p = paras.get(row["locator"])
        if p is None:
            counts["preimage not locatable"] += 1
            continue

        text = paragraph_text(p)
        pre = row["preimage"] or ""
        if not pre or text.count(pre) != 1:
            counts["preimage not locatable"] += 1
            continue
        start = text.index(pre)
        end = start + len(pre)
        post = row["post_state"] or ""
        op = row["operation"]

        # THE STEP THE EARLIER VERSION MISSED: safety follows the changed middle.
        if op == "replace":
            edit_start, edit_end, edit_text = narrow(text, post, start, end)
        else:
            edit_start, edit_end, edit_text = start, end, post

        if op == "replace" and edit_start == edit_end and not edit_text:
            counts["no-op (nothing changes)"] += 1
            continue

        from mathpatch import math_spans
        has_math = bool(math_spans(p))
        crossing = crosses_math_boundary(p, edit_start, edit_end)

        verdict = safety.analyze_paragraph(p, edit_start, edit_end)
        if verdict.ok:
            counts["no math in paragraph" if not has_math else "outside the math boundary"] += 1
            continue

        # accepted path: a pure insertion beside protected citation/field text
        if (
            op == "replace"
            and edit_start == edit_end
            and edit_text
            and verdict.refusal_code in {
                "PATCH_PROTECTED_CITATION_MANAGER_FIELD",
                "PATCH_NOT_SAFE_FIELD_IN_TARGET",
            }
            and insert_beside(
                copy.deepcopy(p), full_start=start, full_end=end,
                position=edit_start, insertion=edit_text,
            )
        ):
            counts["no math in paragraph" if not has_math else "outside the math boundary"] += 1
            continue

        if op == "replace" and verdict.refusal_code == "PATCH_NOT_SAFE_MATH_IN_TARGET":
            # the decomposition uses the FULL authorized span, and MUTATES: deepcopy.
            # Exceptions are NOT swallowed -- a tool bug must not masquerade as a
            # genuine cross-equation refusal.
            probe = copy.deepcopy(p)
            worked = deletion_apply(probe, text, start, end, post)
            counts["deletion around math" if worked else "replacement crossing math"] += 1
            if not worked:
                notes.append(
                    f"{row['locator']}: changed middle [{edit_start},{edit_end}) crosses "
                    f"{len(crossing)} boundary(ies), not expressible as deletions"
                )
            continue

        counts["refused for another reason"] += 1
        other[verdict.refusal_code or "?"] += 1

    return counts, other, notes


def main(argv: list[str]) -> int:
    ledgers = argv[1:]
    if not ledgers:
        print(__doc__)
        return 2

    ac_src = os.environ.get("ARTIFACTCERT_SRC")
    if not ac_src or not (Path(ac_src) / "artifactcert" / "docx_manifest.py").is_file():
        print("set ARTIFACTCERT_SRC to a pinned ArtifactCert src/ tree", file=sys.stderr)
        return 2

    # This tool claims to replay "the pinned engine". Verify that, rather than trusting
    # whatever tree happens to sit at ARTIFACTCERT_SRC -- three findings in this project
    # were wrong for exactly that reason.
    root = Path(__file__).resolve().parents[1]
    expected = next(
        line.strip()
        for line in (root / "INTEGRATION_TARGET.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )
    try:
        actual = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(ac_src).parent,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cannot read ArtifactCert HEAD at {ac_src}: {exc}", file=sys.stderr)
        return 3
    if actual != expected:
        print(
            f"REFUSED: ArtifactCert at {ac_src} is {actual}, not the pinned {expected}. "
            "This measurement is only meaningful against the pinned engine.",
            file=sys.stderr,
        )
        return 3
    print(f"pinned engine verified: {actual}")
    sys.path.insert(0, ac_src)

    from artifactcert.docx_manifest import enumerate_paragraphs, paragraph_text
    from artifactcert.docx_patch import safety
    from artifactcert.docx_patch.engine import (
        _apply_deletion_only_diff_around_structure,
        _insert_beside_unchanged_protected_text,
        narrow_to_changed_middle,
    )
    from artifactcert.opc_xml import parse_untrusted_xml

    from mathpatch import crosses_math_boundary

    mods = (enumerate_paragraphs, paragraph_text, parse_untrusted_xml, safety,
            _apply_deletion_only_diff_around_structure,
            _insert_beside_unchanged_protected_text,
            narrow_to_changed_middle, crosses_math_boundary)

    total: Counter = Counter()
    total_other: Counter = Counter()
    all_notes: list[str] = []

    print(f"artifactcert src: {ac_src}\n")
    print(f"{'ledger':44s} " + "".join(f"{b[:13]:>15s}" for b in BUCKETS))
    for path in ledgers:
        try:
            counts, other, notes = classify_ledger(path, mods)
        except sqlite3.Error as exc:
            print(f"{os.path.basename(os.path.dirname(path))[:44]:44s} SQL error: {exc}")
            continue
        label = os.path.basename(os.path.dirname(path))[:44]
        print(f"{label:44s} " + "".join(f"{counts[b]:15d}" for b in BUCKETS))
        total.update(counts)
        total_other.update(other)
        all_notes.extend(notes)

    print(f"\n{'TOTAL':44s} " + "".join(f"{total[b]:15d}" for b in BUCKETS))
    n = sum(total.values())
    blocked = total["replacement crossing math"]
    print(f"\n  authorized edits examined            {n}")
    print(f"  already work today                   "
          f"{total['no math in paragraph'] + total['outside the math boundary'] + total['deletion around math']}")
    print(f"      of which via decomposition       {total['deletion around math']}")
    print(f"  REPLACEMENT CROSSING MATH (refused)  {blocked}"
          f"   {100 * blocked / n if n else 0:.1f}% of examined")
    print(f"  refused for a non-math reason        {total['refused for another reason']}"
          f"  {dict(total_other) if total_other else ''}")
    print(f"  not locatable (stale spec etc.)      {total['preimage not locatable']}")
    print("\n  Each edit is evaluated against the PRISTINE paragraph. The real engine folds")
    print("  multiple patches on one locator sequentially, so a same-paragraph series can")
    print("  differ; this is the per-edit question, which is the one M1 asks.")
    if blocked == 0:
        print("\n  => No real authorized edit is blocked by the cross-equation replacement")
        print("     case. Generalized holes are NOT justified by this history (PLAN.md M1.4).")
    if all_notes:
        print(f"\n  {len(all_notes)} note(s); first few:")
        for note in all_notes[:6]:
            print(f"    {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
