#!/usr/bin/env python3
"""Measure what is ACTUALLY still refused around equations. PLAN.md F2, M1 item 4.

The 48.5% "text on both sides of math" figure is the population *exposed* to the
problem, not the population blocked. ArtifactCert already applies deletion-only edits
across equations. The number that decides whether generalized "holes" are worth
building is narrower:

    of real AUTHORIZED edits on math-bearing paragraphs, how many are replacements
    that cross a math boundary and cannot be expressed as deletions?

This classifies every `change_spec_items` row in a real ledger by replaying the exact
decision path of the pinned ArtifactCert engine:

    verdict = safety.analyze_paragraph(p, span_start, span_end)
    if verdict.ok                                    -> applies directly
    elif refusal is PATCH_NOT_SAFE_MATH_IN_TARGET and operation is replace:
         _apply_deletion_only_diff_around_structure  -> applies via decomposition
         else                                        -> REFUSED (the M1 question)
    else                                             -> refused for another reason

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
]


def load_paragraphs(docx_path: str, enumerate_paragraphs, parse_untrusted_xml):
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(docx_path) as z:
        root = parse_untrusted_xml(z.read("word/document.xml"), part_name="word/document.xml")
    body = root.find(f"{W}body")
    return dict(enumerate_paragraphs(body))


def classify_ledger(path: str, mods) -> tuple[Counter, Counter, list[str]]:
    (enumerate_paragraphs, paragraph_text, parse_untrusted_xml,
     safety, deletion_apply, crosses_math_boundary) = mods

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

        # does this paragraph have math at all, and does the extent cross a boundary?
        crossing = crosses_math_boundary(p, start, end)
        from mathpatch import math_spans
        has_math = bool(math_spans(p))

        verdict = safety.analyze_paragraph(p, start, end)
        if verdict.ok:
            counts["no math in paragraph" if not has_math else "outside the math boundary"] += 1
            continue

        if (
            row["operation"] == "replace"
            and verdict.refusal_code == "PATCH_NOT_SAFE_MATH_IN_TARGET"
        ):
            # the decomposition MUTATES the paragraph; never let it touch the cache
            probe = copy.deepcopy(p)
            try:
                worked = deletion_apply(probe, text, start, end, row["post_state"] or "")
            except Exception:
                worked = False
            counts["deletion around math" if worked else "replacement crossing math"] += 1
            if not worked:
                notes.append(
                    f"{row['locator']}: replacement crosses "
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
    sys.path.insert(0, ac_src)

    from artifactcert.docx_manifest import enumerate_paragraphs, paragraph_text
    from artifactcert.docx_patch import safety
    from artifactcert.docx_patch.engine import _apply_deletion_only_diff_around_structure
    from artifactcert.opc_xml import parse_untrusted_xml

    from mathpatch import crosses_math_boundary

    mods = (enumerate_paragraphs, paragraph_text, parse_untrusted_xml,
            safety, _apply_deletion_only_diff_around_structure, crosses_math_boundary)

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
