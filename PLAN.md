# MathPatch — Plan

**Status:** standalone repository, pre-implementation.
**Relationship to ArtifactCert:** MathPatch is developed as an independent package and
integrated into ArtifactCert afterwards. It is not a fork, not a plugin, and it never
becomes an authority over document identity.

**One line:** precise, auditable editing of equations in Word documents.

---

## 0. Decision record: why a separate repository first

The earlier position in this design discussion was "build it in-tree inside
`artifactcert/docx_patch/math/`, extract later," on the grounds that
`ArtifactCert/docs/ecosystem.md` §4 requires *"a working local solution has already
shown that extraction is worthwhile"* before a package is split out.

That is reversed here, deliberately, for reasons visible in the ArtifactCert repository
state on 2026-09-07:

- `git worktree list` shows **seven** live ArtifactCert worktrees on separate in-flight
  branches (`integration/t8-proof-round-v2`, `milestone/docx-internal-pilot-2026-08-28`,
  `audit/pdf-workflow-real-paper-2026-08-31`, `fix/pdf-coverage-and-verifier`,
  `feature/track-changes-download`, `main`, plus the primary checkout).
- The primary checkout is on a **detached HEAD** (`a95733c`).
- The Evidence Bundle v1 pilot is in progress.

The largest single change this work requires — putting a sentinel character for math into
the canonical paragraph text (§3, finding F1) — **changes the stored text of every
math-bearing paragraph object, and therefore every content hash derived from it.** Landing
that into a tree with seven parallel branches and a running pilot would force a
ledger-identity migration across all of them simultaneously.

Doing the pure, fixture-testable half of the work outside that tree first is the lower-risk
sequence. The integration then lands as one reviewed change against a quiet tree.

### Honest cost of this choice

`ecosystem.md` §4 condition 6 (demonstrated value of independent distribution) stays
**unmet** for the foreseeable future, and the named risk of a separate repo is that it grows
a second document-addressing system — the exact drift that
`artifactcert/docx_patch/locator.py`'s docstring was written to prevent. §2 is the
mitigation, and it is binding, not aspirational.

**Review date:** if MathPatch is still only a span-finder with no consumer other than
ArtifactCert three months after M1 lands, that is evidence for folding it back in-tree.
Fold it back; do not defend the repository.

---

## 1. What MathPatch is for

ArtifactCert currently fails closed on any patch whose target paragraph contains Office
Math (`artifactcert/docx_patch/safety.py:210`):

    PATCH_NOT_SAFE_MATH_IN_TARGET
    "Target paragraph contains Office Math; math editing is out of scope for v0."

That refusal is correct for the current implementation and blocks a large fraction of
otherwise safe text edits in real scientific manuscripts. The first useful capability is
therefore **not** equation modification:

> Allow ordinary text patches to proceed inside paragraphs that contain math, preserving
> each math span exactly, and refuse only when the authorized edit actually intersects math.

Equation *modification* comes second, and is the smaller half of the value.

---

## 2. Boundary contract (binding)

This section is the reason a separate repository is acceptable. Violating it makes the
split harmful.

### MathPatch owns

- recognition of Office Math spans inside a caller-supplied paragraph element;
- the canonical-text projection of a paragraph **including** math sentinels (§3, F1);
- canonicalized (C14N) hashing of protected math subtrees;
- later: the Math AST, OMML reader, OMML writer, LaTeX input adapter.

### MathPatch must never own

- paragraph or object enumeration, addressing, or locators;
- candidate, object, or finding identity;
- authorization, policy, or release decisions;
- ledger state;
- reading or writing `.docx` files as a whole.

### API shape that enforces it

Every entry point takes an **already-located** `lxml` element and returns offsets
**relative to that element**. MathPatch never sees a file path, a locator string, or an
object id.

    canonical_text(p: etree._Element) -> str
    math_spans(p: etree._Element)     -> list[ProtectedMathSpan]   # offsets relative to p
    span_digest(span)                 -> str                        # C14N sha256
    CANONICAL_TEXT_CONTRACT_VERSION: str

### The canonical-text contract

ArtifactCert's `docx_manifest._para_text` becomes a thin delegate to
`mathpatch.canonical_text`, so there is exactly **one** definition of canonical paragraph
text — the same move already made for `docx_patch/locator.py`, which is deliberately a
re-export of core so that two enumerations cannot drift.

This inverts the dependency: ArtifactCert's object identity would then depend on an external
package's text projection. That is only safe if it is versioned and recorded, so:

1. MathPatch exposes `CANONICAL_TEXT_CONTRACT_VERSION`, bumped on **any** change to the
   projection.
2. ArtifactCert records that version in the candidate/manifest alongside policy version and
   reviewer configuration.
3. ArtifactCert pins MathPatch to an exact version.
4. A version mismatch against a stored candidate is a **refusal**, not a warning.

Without (1)–(4) a dependency bump silently changes candidate identity in an audit tool.

---

## 3. Findings from the ArtifactCert code that shape this design

Verified against the tree at `a95733c` on 2026-09-07.

### F1 — Math is currently zero-width in the only coordinate space that exists

`docx_manifest._para_text` (`docx_manifest.py:455`) is the concatenation of direct `w:r`
children's `w:t` **only**. Its docstring is explicit that math *"is deliberately NOT part of
the canonical text ... so it must also be invisible to matching."* `RunFragment.start/end`
(`docx_patch/safety.py:71`) are offsets in that same space.

So a math span occupies **zero characters**, and "the edit range does not intersect the math
span" is undecidable — a zero-width point at offset *k* lies in `[start, end)` only by
convention.

This is latent, not a live bug, because `safety.py:210` refuses first. Lifting that refusal
without fixing the coordinate space makes it live:

    actual:       "The deformation <math> increases rapidly."
    canonical:    "The deformation  increases rapidly."
    finding span: "deformation  increases"   -> matches CONTIGUOUSLY, crosses the math

**Consequence for M1:** the sentinel must land *before* the refusal is lifted. See §6.

**Fix:** one `U+FFFC OBJECT REPLACEMENT CHARACTER` per math span in canonical text.
Intersection becomes an ordinary interval test; a reviewer sees a placeholder instead of a
misleading elision; any proposed span crossing math provably contains the sentinel.

**Cost:** changes canonical text of every math paragraph, hence stored object text and
derived hashes. Existing ledger findings bound to math paragraphs are invalidated. This also
means `"math"` should be retired from `paragraph_flags`' lossy reasons
(`docx_manifest.py:521`, marker emitted at `docx_manifest.py:604`) in the same change, or the
sentinel and `_LOSSY_MARKER` will assert contradictory things about the same paragraph.

### F2 — Half of all math paragraphs need discontiguous edits

Measured across the four distinct manuscripts in the ArtifactCert working directory
(`tools/corpus_math_inventory.py`), 231 math-bearing paragraphs:

| shape | count | share |
|---|---|---|
| text on **both** sides of math (a sentence rewrite wants to span it) | 112 | 48.5% |
| math-only paragraph (display equation, no prose to edit) | 87 | 37.7% |
| **text on one side only — the clean contiguous case** | **32** | **13.9%** |

Hierarchical Jamming alone: 141 math paragraphs -> 61 math-only, 76 sandwiched, **4**
one-sided.

`_apply_to_runs(span_start, span_end)` (`docx_patch/engine.py:100`) executes a single
contiguous span. A "must not intersect math" rule over a contiguous span therefore recovers
almost nothing on the worst document.

**Consequence:** discontiguous extents with immutable holes belong in **M1**, not a later
phase. The model is not `PREFIX | TARGET | SUFFIX` but:

    PREFIX | ( EDIT, HOLE, EDIT, HOLE, EDIT ) | SUFFIX

where each `HOLE` is a protected math span, byte-stable under C14N, and each `EDIT` is an
ordinary text extent.

### F3 — Byte-level containment conflicts with a decision already made

`docx_patch/regression.py`'s module docstring: *"Binary ZIP/XML byte differences are
deliberately ignored: re-serialization legitimately alters package bytes."* The engine
mutates the lxml tree and reserializes; it does not splice raw XML.

So a literal "prefix byte-for-byte identical" invariant would raise false alarms on correct
patches, and switching to raw-XML splicing is a rewrite of a working engine rather than an
addition.

**Three-tier oracle instead** (§5).

Also: `regression.py:_style_signature` walks only `child.tag == w:r`, so it has **no** math
awareness whatsoever — it cannot currently detect that a math subtree changed. The
protected-span check is new code, not a re-use.

### F4 — No new address space is needed for M1

The engine already targets sub-paragraph by **text match**: `docx_patch/spec.py` fills
`DocxPatch.original_text` from the finding's `span`, and `_locate_span`
(`engine.py:87`) finds it inside the paragraph's canonical text.

Introducing `body/p/37/math/0` style addresses would touch `_is_docx_locator`, `spec.py`'s
binding, `docx_patch/authorization.py`, and `objects.locator` in the ledger — the sealed
authority path that commit `18cdd1c` ("bind patch authority to exact proposal revision")
specifically hardened.

**Defer math-object addressing to Phase 2**, where a math object genuinely *is* the patch
target. M1 needs only relative span offsets, which never leave the paragraph.

### F5 — Tracked-change fixtures are unreachable behind a different guard

`safety.document_has_tracked_changes` (`docx_patch/safety.py:99`) fails the **entire patch
set** if any revision tag appears anywhere in the document body.

Consequences: a "math inside tracked changes" fixture cannot be exercised until that
separate v0 limitation is lifted; and the `_structured_tracked_*.docx` outputs ArtifactCert
itself produces are unpatchable for a reason unrelated to math. Choose M1 regression
documents that are actually reachable, and record this as a dependency M1 does not own.

Note also that `safety.analyze_paragraph` iterates **direct children** of `w:p`, so math
nested inside `w:ins`/`w:del`/`w:hyperlink` is not matched by `_MATH_TAGS` there. Today the
document-wide tracked-changes guard makes that unreachable, so it is not a live hole — but
MathPatch's own span discovery must descend, not scan direct children, or it will
under-report protected spans in exactly the documents ArtifactCert emits.

### F6 — ArtifactCert holds two definitions of run text (latent)

`docx_manifest._para_text` (`docx_manifest.py:468`) extracts a run's text with
`child.iter(qn("w:t"))` — all `w:t` **descendants**. `docx_patch/safety._run_text`
(`safety.py:88`) uses `run.findall(qn("t"))` — **direct children only**.

Two definitions of one fact, in the two files whose offsets must agree. Measured: they
agree on **all 12,394 runs** of the reference corpus, so the difference is latent, not
live. But it is the drift hazard `docx_patch/locator.py`'s docstring exists to prevent,
sitting unguarded between two modules.

MathPatch's projection follows `_para_text` (the anchor space, see F7) and holds that
rule in exactly one place, inside `project()`'s traversal. A separate `run_text` helper
was removed during the M0 audit precisely because a second definition of run text
living inside MathPatch would reproduce this very finding. When the projection is
integrated, both ArtifactCert call sites should delegate to it, retiring F6.

### F7 — the two coordinate spaces are already skewed, and it mis-targets patches (LIVE)

`engine.apply_patches` locates the anchor in `_para_text`'s space:

    text = paragraph_text(p)              # hyperlink text contributes NOTHING
    span_start = text.index(anchor)
    verdict = safety.analyze_paragraph(p, span_start, span_end)

but `safety.analyze_paragraph` re-walks the paragraph and, for `w:hyperlink` /
`w:smartTag`, advances its offset **by that element's text width**
(`safety.py:197-206`). Every fragment offset after a text-carrying hyperlink is
therefore shifted by its width relative to the space the anchor was located in.

Reproduced with ArtifactCert's own code — `tools/probe_offset_skew.py`, two outcomes:

- **A, false refusal.** 8-char link: the shifted hyperlink interval still overlaps the
  edit span, so a safe edit is refused as `PATCH_NOT_SAFE_HYPERLINK_INTERSECTS_TARGET`.
- **B, mis-target.** 4-char link: the shift moves the interval clear of the span, no
  refusal fires, and the patch overwrites the wrong characters —
  `'AAA  <<REPLACED>>rget CCC'` where `'AAA  BBB <<REPLACED>> CCC'` was authorized.

Two paragraphs in the reference corpus have the exposing shape (a text-carrying
hyperlink followed by editable text). This is a defect in ArtifactCert, not in
MathPatch, and it is **not** MathPatch's to fix — but it is load-bearing for M1:

> The sentinel must be emitted by the same walk that advances a consumer's offsets.
> If `safety.analyze_paragraph` keeps re-walking with its own rules, math offsets will
> acquire an identical skew the moment they are consumed.

That is why the projection follows `_para_text` and not `safety`: `_para_text`'s space
is the one in which the anchor is located, and therefore the one that decides which
characters an edit actually overwrites. F7 must be resolved in favour of the
projection.

---

## 4. Corpus evidence

Native OMML is universal in this corpus; the "edit rather than regenerate" premise holds.

| manuscript | oMath | oMathPara | OLE / MathType / Eq3 | text paras | with math |
|---|---|---|---|---|---|
| Fictitious magnetic charge | 59 | 0 | 0 / 0 / 0 | 94 | 21.3% |
| Hierarchical Jamming | 316 | 0 | 0 / 0 / 0 | 864 | 16.3% |
| Hygrochastic Revision v5 | 90 | 24 | 0 / 0 / 0 | 291 | 17.5% |
| Shear by Design Nature R1 | 34 | 0 | 0 / 0 / 0 | 411 | 4.6% |

No legacy MathType/OLE objects and no equation images anywhere. The OCR path stays
correctly out of scope.

**Note on interpreting these numbers:** "with math" is the *refusal* rate, not the
*recoverable* rate. See F2 — recoverable is much smaller until holes exist.

`tools/corpus_math_inventory.py` regenerates both tables and is the baseline for the M1
recovery metric. Since the M0 audit it classifies shapes from `mathpatch.project`'s
canonical text rather than a local reimplementation, so the numbers driving the M1
scope decision are covered by the library's own tests and drift gate.

---

## 5. Verification model — three tiers

Every mutation is checked by oracles that cannot mask each other's failures.

### Tier 1 — non-target OPC parts: strict payload bytes

Every package part not explicitly authorized by the patch retains identical payload bytes.
Compared by payload hash, never by ZIP stream bytes (CRC, compression, and package metadata
change legitimately).

### Tier 2 — protected math subtrees: C14N digest

Each `ProtectedMathSpan` is hashed with XML canonicalization before and after. Raw-byte
comparison is wrong here: lxml reserialization can legitimately move namespace declarations
and alter self-closing forms in untouched subtrees. C14N survives the round trip.

### Tier 3 — target part: logical comparison

As `docx_patch/regression.py` already does — paragraph text map plus style signature —
extended so the signature is math-aware (F3).

### Semantic oracle (Phase 2+)

Independently re-parse the patched OMML and compare structure to the intended AST:

    AST(actual patched equation) == AST(intended equation)

A mathematically correct edit that rewrites unrelated XML fails Tier 1/2. A perfectly
contained patch that changes the equation wrongly fails the semantic oracle. Neither
oracle may be derived from the other's output.

---

## 6. Milestones

### M0 — the seam (MathPatch only, no ArtifactCert change)

Deliver, against synthetic fixtures plus the real corpus, read-only:

- `canonical_text(p)` with `U+FFFC` sentinels, byte-identical to
  `artifactcert.docx_manifest._para_text` on all **math-free** paragraphs (this is the
  drift gate — prove the projection is a strict extension before anything depends on it);
- `math_spans(p)` returning relative `[start, end)` offsets consistent with that text,
  discovering math by **descent** (F5), not direct-child scan;
- `span_digest(span)` C14N sha256, stable across an lxml parse/reserialize round trip;
- `CANONICAL_TEXT_CONTRACT_VERSION`.

**Completion check:** on all four corpus manuscripts, for every math-free paragraph,
`mathpatch.canonical_text(p) == artifactcert._para_text(p)`; for every math paragraph, the
projections differ in exactly the sentinel positions and nowhere else. Zero exceptions.

**STATUS: M0 COMPLETE (2026-09-07).** `tools/drift_gate.py` over the seven reference
manuscripts plus `tests/fixtures/descent.docx`:

    paras=4654   math-free=4115   math-bearing=539   spans=1175   FAIL=0

`tools/c14n_roundtrip_probe.py` settled Tier 2 before any of it was written: C14N
digests of untouched math subtrees survive a parse -> mutate -> reserialize -> reparse
round trip on every span of the four distinct manuscripts, in all three scenarios
including the actual M1 operation (editing text in a math-bearing paragraph). All four
candidate parameter sets were stable, so the choice rests on purpose (see `digest.py`).

32 unit tests cover the fixture matrix of section 9. `tools/verify_m0.sh` reproduces
every claim above in one command. Two findings were added to this plan during M0: F6
and F7.

### M0 self-audit: what the gate does and does not certify

The gate's coverage is bounded by its corpus, so the corpus was measured rather than
assumed. Six checks; four held, two did not.

Held:

- **no sentinel collision.** U+FFFC does not occur anywhere in the corpus, so a
  sentinel can never be confused with authored text.
- **enumerator coverage is complete.** ArtifactCert's `enumerate_paragraphs` reaches
  every one of the 4,645 `w:p` elements in the corpus, and no math sits in an
  unenumerated paragraph.
- **detection agrees with an independent oracle.** ArtifactCert's `paragraph_flags`
  "math" flag and this projection's span discovery disagree on 0 of 4,645 paragraphs.
- **the tests can fail.** Six independent mutations of the traversal (double-count,
  dropped descent, text/offset desync, wrong intersection bound, unguarded text
  emission, wrong directness test) each produce 3-4 test failures. The gate itself
  fails on a dropped sentinel (141 failures) and on leaked text (268).

Did not hold, now corrected:

- **CORRECTION.** An earlier version of this section claimed the tracked-changes
  documents "exercise the `w:ins` nesting path of F5". They do not. All **1,167**
  corpus spans are direct children of `w:p`; **zero** sit in any wrapper. The claim was
  inferred from the documents containing `w:ins` at all, without checking whether any
  `w:ins` contains math. Consequence: a regression that dropped wrapper descent
  entirely **passed the gate unnoticed**. `tests/fixtures/descent.docx` now supplies
  the missing shapes (math in `w:ins`, in `w:hyperlink`, in `w:r`), and that same
  mutation now fails the gate with 5 failures. Descent over *real* documents remains
  **unverified**: no reference manuscript contains the shape.
- **the probe was watching the wrong artifact.** `c14n_roundtrip_probe.py` hard-coded
  inclusive C14N while `digest.py` ships exclusive + comments, so re-running the
  committed probe did not exercise the shipping configuration. It now imports
  `C14N_KWARGS`. The conclusion itself stood -- the shipping parameters were covered by
  a one-off variant comparison -- but the committed probe did not test them.

Two smaller repairs from the same audit: the gate branched on its own span count, so a
discovery bug would have been reclassified as "math-free" and passed silently (it now
branches on `paragraph_flags` and asserts total coverage); and the `id()`-based coverage
comparison held no strong references to the lxml proxies it compared, which can reuse
addresses after collection.

### M1 — retire the blanket math refusal (ArtifactCert integration)

Ordered, because F1 makes the order load-bearing:

1. `_para_text` delegates to `mathpatch.canonical_text`; record the contract version in the
   candidate; retire `"math"` from `paragraph_flags` lossy reasons; **migrate/invalidate
   existing findings bound to math paragraphs.**
2. Teach `safety.analyze_paragraph` to emit math spans as protected holes rather than
   refusing at `safety.py:210`.
3. Extend `_apply_to_runs` to a discontiguous extent with immutable holes (F2).
4. Add Tier 1 and Tier 2 oracles to `regression.py`.
5. **Only now** lift `PATCH_NOT_SAFE_MATH_IN_TARGET` to fire solely when an authorized edit
   extent actually intersects a math span.

**Completion checks:**

- every existing non-math patch test passes unchanged;
- an authorized text edit wholly outside math spans succeeds, math preserved;
- an authorized text edit that spans a math span succeeds via holes, math preserved;
- an edit whose extent intersects a math span still fails closed;
- all protected spans C14N-identical; all non-target parts payload-identical;
- patched DOCX opens in Word;
- `tools/corpus_math_inventory.py` shows a measured reduction in math-related refusals,
  reported against the F2 breakdown rather than the headline refusal rate.

### M2 — first native equation patch

Bind one existing Office Math object, parse to a minimal Math AST, apply one narrow
authorized change (one identifier, one subscript, or one literal), serialize only that
target back to OMML, and pass both containment and semantic oracles. Math-object addressing
(F4) enters here, not before.

Demonstration target: a one-symbol change in a real manuscript equation with all
surrounding XML preserved.

### M3 — construction

Fractions, roots, scripts, accents, symbols, integrals, sums, matrices, cases, decorated
symbols; inline and display. Not a reimplementation of Word's equation UI — only the
structures scientific manuscripts need.

---

## 7. Canonical representation

    OMML -> Math AST -> modify AST -> OMML          (trusted path)
    OMML -> LaTeX -> OMML                            (never; lossy)
    LaTeX -> parser -> Math AST -> OMML              (input adapter only)

LaTeX is how a review finding or a newly authored equation arrives. It is internal
machinery, not the product, and never the representation of an existing Word equation.

---

## 8. Non-goals

Not a CAS. Not equation OCR. Not a Word replacement. Not a general DOCX converter. Not a
LaTeX editor. Not a Pandoc alternative. Not a second document locator. Not a reason to
reimplement mature XML infrastructure.

Where conversion or standards support is commodity, reuse or learn from existing
implementations. Own only what defines the capability: **precise, authorized,
loss-contained, verifiable mutation of scientific-document math.**

---

## 9. Test strategy

**Fixtures:** one inline symbol; several inline spans; text before only; text after only;
text both sides; adjacent spans; display equation; equation in a numbering table (the
Hygrochastic idiom — 34 of its math spans sit inside tables); math inside `w:ins`; comment
anchor near math; hyperlink near math; mixed run formatting across the surrounding text.

**Edit cases per fixture:** wholly before; wholly after; between two spans; ending exactly
at a boundary; starting exactly at a boundary; spanning a span (holes); intersecting a span
(must refuse).

**Real corpus:** the four manuscripts as a regression suite, tracking refusals recovered,
false accepts, false refusals, unintended XML changes, and Word-open failures. Report
against the F2 shape breakdown.

**Package checks after every patch:** OPC validity, relationship resolution, non-target
payload hashes, protected-span C14N digests, ArtifactCert binding re-verification.

---

## 10. Layout

    src/mathpatch/
        canonical.py     # canonical_text, sentinel projection, contract version
        spans.py         # ProtectedMathSpan, descent-based discovery
        digest.py        # C14N subtree hashing
        # Phase 2:
        ast.py  omml_reader.py  omml_writer.py  latex_adapter.py
    tools/
        corpus_math_inventory.py   # F2 baseline: representation + shape tables
        c14n_roundtrip_probe.py    # settles section 5 Tier 2 before relying on it
        drift_gate.py              # the M0 gate: strict extension of _para_text
        probe_offset_skew.py       # reproduces F7 against ArtifactCert's own code
        make_fixture_docx.py       # shapes the real corpus lacks (wrapper-nested math)
        verify_m0.sh               # one command: tests + fixture + probe + gate
    tests/
        fixtures/descent.docx   # generated; the only source of wrapper-nested math

Module split follows implementation pressure; do not create files speculatively.
