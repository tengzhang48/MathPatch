# MathPatch — Plan

**Status:** M0 and M0.1 complete. Verified against ArtifactCert `origin/main` at
`0992741` (2026-09-07) — see the reading discipline in section 3.
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

**Rebased 2026-09-07 against ArtifactCert `origin/main` = `0992741`.** An earlier version of
this section argued that ArtifactCert blocks every text patch in a math-bearing paragraph and
that MathPatch's first job is to unblock them. That was read off a diverged tree and is false
on main. What main already does:

- refuses only when the edit span **crosses** a math boundary
  (`safety.py`: `if span_start < offset < span_end`); prose elsewhere in a math paragraph is
  editable, and math is a zero-width structural boundary in canonical text;
- decomposes a **deletion-only** edit into disjoint plain-text ranges around intervening
  equations (`engine.deletion_only_ranges`, `_apply_deletion_only_diff_around_structure`),
  checks each range independently with the ordinary safety analyzer, and applies them
  right-to-left so canonical offsets stay stable. Its own worked example is the interleaved
  case: `length of [l_f], thickness of [h_f], modulus of [E_f]`. The alignment is a greedy
  left-to-right subsequence match rather than `SequenceMatcher`, deliberately, because
  repeated letters could otherwise report a deletion that "spuriously cross[es] the preceding
  equation";
- shares that decomposition with the Track Changes projector rather than duplicating it.

So the honest motivation is narrower and sharper. Two things are missing, and both are
MathPatch's:

**(1) Protected math is counted, not proven.** After a patch, main's regression report records
a document-wide **count** of `oMath` elements (`regression.py:157`) and compares canonical
text, which excludes math. C14N hashing exists in `docx_track_changes.py` and
`revision_ingest.py`, but not in the patch regression path. A count cannot distinguish two
equations exchanging contents, or one equation's internals being altered. The engine only
rewrites `w:r` text so it probably never does that — but `safety.py`'s own comment, *"The
regression report still proves that its XML stayed put,"* claims more than the code
establishes. For a project whose principle is that no actor certifies its own patch, that is
the invariant worth closing, and a per-span C14N digest closes it.

**(2) Equation modification does not exist anywhere.** Main reads OMML for *display* only
(`docx_view._omml_to_latex`, via `dwml` + KaTeX) and quotes equations to reviewers
(`external_review_export`, commit `335f20d`). There is no Math AST, no OMML writer, and no
mutation path. That is the distinctive capability, and it stays MathPatch's:

> **Edit an existing scientific equation safely, rather than regenerate it.**


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

**Revised 2026-09-07: the identity migration is withdrawn.** An earlier version committed to
making `docx_manifest._para_text` a thin delegate to `mathpatch.canonical_text`, on the grounds
that one definition of canonical text is better than two. The reasoning still holds in the
abstract, but the justification for paying its cost does not: F1 is retracted, main already
edits prose safely around zero-width math, and changing `_para_text` would change the stored
text of every math-bearing paragraph and every hash derived from it — a migration across a
repository with many live worktrees and a running pilot, in exchange for capability that
already exists.

For now MathPatch's projection is an **internal structural and protection representation**, not
ArtifactCert's persisted canonical identity. The sentinel never has to reach a stored object.

`CANONICAL_TEXT_CONTRACT_VERSION` is kept anyway, and matters the moment any consumer derives
persisted state from the projection:

1. MathPatch bumps it on **any** change to the projection.
2. A consumer that stores anything derived from canonical text records the version alongside it.
3. A version mismatch against stored state is a **refusal**, not a warning.
4. Pin MathPatch to an exact version.

Without (1)-(4) a dependency bump silently changes identity in an audit tool. With the
migration withdrawn, none of it is load-bearing yet — which is the point of writing it down
before it is.


## 3. Findings from the ArtifactCert code that shape this design

Verified against the tree at `a95733c` on 2026-09-07.

### F1 — RETRACTED (was: math is zero-width so intersection is undecidable)

**Retracted 2026-09-07.** The observation about the coordinate space is correct — math
contributes zero width to canonical text — but the conclusion was wrong. Main treats math as a
**structural boundary at an offset** and tests `span_start < offset < span_end`, which is
decidable and needs no sentinel: an edit may end exactly where math begins, and only an edit
strictly spanning the boundary is refused. MathPatch's `intersects_math` independently arrived
at the same strict-inequality convention, which is mutual corroboration rather than a finding.

The claim that this blocked 12.8–21.3% of text-bearing paragraphs was measured against a
diverged tree and is **false on main**.

What survives: the sentinel is still useful for *showing* a reviewer where an equation sits in
a sentence, and for making span arithmetic non-degenerate inside MathPatch. It is **not**
grounds for changing ArtifactCert's persisted canonical text, and the identity migration this
finding once justified is withdrawn.


### F2 — Discontiguous edits: solved for deletions, still open for replacements

Measured across the four distinct manuscripts (`tools/corpus_math_inventory.py`, classifying
from the shipping projection), 231 math-bearing paragraphs:

| shape | count | share |
|---|---|---|
| text on **both** sides of math | 112 | 48.5% |
| math-only (display equation, no prose to edit) | 87 | 37.7% |
| text on one side only | 32 | 13.9% |

**Scope corrected 2026-09-07.** Main already handles the interleaved case for
**deletion-only** edits, via the disjoint decomposition in section 1. What remains refused is
a **replacement** that spans a math boundary — `safety.py` states it plainly: *"replacing text
on BOTH sides would splice around math and remains forbidden."* Insertions and substitutions
do not use the deletion exception.

So the 48.5% is the population *at risk*, not the population currently blocked. The number
that decides whether generalized holes are worth building is: **of real authorized changes on
math-bearing paragraphs, how many are replacements spanning a boundary that the deletion-only
path cannot express?** That is an M1 measurement, not an assumption, and it is the one number
this plan does not yet have.


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

### F6 — Two definitions of run text, in one apply path (latent)

Still present on `0992741`. `safety._run_text` uses `run.findall(qn("t"))` — direct children —
and **builds the fragment offsets**. `docx_manifest._para_text` and `engine._apply_to_runs`
both use `.iter()` — all descendants — and `_apply_to_runs` **consumes those offsets**. So one
rule measures and a different rule applies, inside a single edit.

Demonstrated consequence, on `0992741`, with a `w:t` below an intermediate element inside a
direct run: the fragment is reported as `[0,15)` while the anchor was located in a 19-character
space, and the patch produced `'AAA DEEP <<R>> CCCDEEP'` — the nested text duplicated.

**Reachability: not reachable from real documents.** Measured across the corpus: **0 of 21,433
runs** have `findall` and `.iter()` yielding different text, and in valid OOXML `w:t` is always
a direct child of `w:r`. (An earlier count of "2,142" here was an artifact of comparing lxml
proxies by `id()` without holding references — the same defect this project fixed in its own
gate. Corrected by comparing text instead.)

So this is a hardening item, not a live defect: one rule should be derived from the other, or
the shape should fail closed. MathPatch holds the rule in exactly one place, inside
`project()`'s traversal, and reports the shape as a `nested_run` anomaly. A separate `run_text`
helper was deleted during the M0 audit precisely because a second definition living inside
MathPatch would reproduce this finding.


### F7 — RETRACTED (was: a live hyperlink coordinate skew)

**Retracted 2026-09-07. It was already fixed before this project began.** ArtifactCert
`safety.py:315-323` computes hyperlink/smartTag boundaries in canonical coordinates and carries
its own record of the bug: *"Advancing offset by the element's text width desynced the fragment
map from the engine's span whenever such an element PRECEDED the anchor, making edits land on
the wrong characters (reproduced 2026-08-24: anchor GAMMA edited BETA)."*

`tools/probe_offset_skew.py` reproduced the same phenomenon against a diverged tree dated
2026-08-28. It is kept as a regression probe — pointed at a current tree it should report "F7
not reproduced" — and as the reason for the reading discipline below.

### F8 — Two canonical text streams exist, deliberately

`0992741` has both:

- `docx_manifest._para_text` — patch coordinates. Direct `w:r/w:t` only; legacy `w:sym` glyphs
  are structural boundaries, not editable characters. Kept deliberately narrow, and stable, to
  "preserve already-sealed specifications created before symbol extraction was added".
- `docx_manifest.review_paragraph_text` — the fuller reviewer-visible stream, including mapped
  legacy symbols via `word_run_text`/`word_symbol_text` (standard Symbol font only; Wingdings
  and custom fonts refuse, because "guessing them would silently change scientific content").

This matters for integration: MathPatch's projection currently extends `_para_text` only. A
single authoritative traversal must be able to yield **both** streams plus the protected spans,
or integrating it would just add a third. That materially strengthens the segment-model
proposal in M1.

### F9 — Real-world OMML defect classes are already catalogued

`docx_view.py` has paid for knowledge MathPatch's reader must inherit rather than rediscover:

- Word's upright style (`m:sty="p"`) applies to **letters only**. Wrapping operators in
  `\mathrm` costs them their relation/binary spacing — on a real manuscript this hit **47 of
  90 equations** (90 is exactly Hygrochastic v5's span count).
- Word may legally omit `m:chr` for an n-ary operator, integral being the default; `dwml`
  assumes it is present and crashes.
- Accepting a tracked equation edit can leave **empty `m:r` shells**, which `dwml` rejects as
  an invalid child inside a fraction, refusing the whole equation.
- Unknown inline wrappers appear inside OMML.

Any Phase-2 OMML reader should start from these four cases.

### Reading the ArtifactCert tree (discipline, learned the hard way)

This plan's findings were wrong three times because they were read off the wrong tree: first a
**detached HEAD** in the primary checkout (`a95733c`, 2026-08-28, 195 commits diverged), then a
worktree's **local `main`** without fetching (`c5d3da9`, 2026-09-05, 15 commits stale). The
repository has many worktrees and the primary checkout is often detached.

Before asserting what ArtifactCert "currently" does:

```
git -C <artifactcert> fetch --all
git -C <artifactcert> for-each-ref --sort=-committerdate | head
git -C <artifactcert> show origin/main:src/artifactcert/<file>
```

Quote the hash and its date in the claim. `M0_EVIDENCE.json` records both `origin/main` and the
local checkout's HEAD so any divergence is visible in the record itself.


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

### M0.1 — harden and freeze the seam — **COMPLETE (2026-09-07)**

Everything here came out of an external review plus the M0 self-audit. All defects were
reproduced before being fixed.

Library:

- **authored sentinel refused.** `project()` raises `SentinelCollision` when a paragraph's own
  text contains U+FFFC. Absence from one corpus is not a property of Word documents, and an
  authored sentinel would make `sentinel_offsets()` disagree with `spans` and corrupt every
  intersection test.
- **non-element children handled.** An XML comment or processing instruction has a callable
  `tag`, so `QName()` raised `ValueError` on it. These reach the projection **by design** —
  ArtifactCert's `parse_untrusted_xml` sets `remove_comments=False` — and now they are skipped
  without hiding math inside a wrapper.
- **nested runs no longer break strict extension.** `_para_text` reaches every `w:t` descendant
  of a direct `w:r`, so a run nested in a direct run contributes text; it is now included and
  reported as a `nested_run` anomaly for consumers that would rather fail closed (see F6).
- **`intersects_math` validates its extent.** `0 <= start <= end <= len(text)`, or `ValueError`.
  A protection API must reject an impossible range, not answer "no intersection".

Verification apparatus — both scripts were **failing open**:

- `drift_gate.py` printed `M0 GATE: PASSED` with exit 0 while an unreadable input was silently
  skipped. Unreadable files, parser refusals, and missing `w:body` now fail the gate, and a
  `SentinelCollision` is reported as a finding rather than a traceback.
- `c14n_roundtrip_probe.py` skipped unreadable inputs and counted skipped scenarios as neither
  pass nor fail. Unreadable inputs are now fatal and skips are surfaced in the result.

Record and distribution:

- `M0_EVIDENCE.json` (`tools/make_evidence.py`) binds the claims to the MathPatch commit,
  ArtifactCert's `origin/main` hash **and date**, the local checkout's HEAD (so divergence is
  visible), interpreter and lxml versions, and a sha256 + paragraph/span count per corpus
  document. Manuscripts are recorded by **alias and hash, never filename** — the titles are
  unpublished and this repository is a shared artifact.
- GitHub Actions runs the synthetic suite on 3.11/3.12/3.13 and checks the fixture generator is
  reproducible. CI deliberately does **not** run the gate or probe: those need a real corpus and
  an importable ArtifactCert, so CI proves internal consistency, not the corpus claims.
- `LICENSE` added (MIT, as README and `pyproject.toml` already declared).
- README and this plan no longer describe unimplemented capability as present.

### M1 — protected-math integration (no identity migration)

Rebased against `origin/main` `0992741`. **Deliberately smaller than the previous M1**, which
proposed changing ArtifactCert's canonical text first.

1. **Enrich `Projection` into a segment model.** Today it exposes only `text` and `spans`, so a
   consumer must re-walk the paragraph to build its own `RunFragment` map — which is exactly the
   duplicate-coordinate problem of F6, reintroduced at the seam. Target shape:

   ```
   Projection
     ├─ text                     (patch-coordinate stream, = _para_text)
     ├─ review_text              (reviewer stream, incl. mapped symbols — F8)
     ├─ text_segments[]          element, start, end
     └─ protected_spans[]        element, start, end, kind, digest
   ```

   One traversal, several projections. This is the single most valuable piece of the milestone:
   it lets ArtifactCert's analyzer and writer consume one authoritative model, and it retires
   F6 and F8 as a side effect instead of adding a third stream.

2. **Add protected-span verification to the existing patch path.** ArtifactCert calls MathPatch
   to inventory math spans in the already-located paragraph, digests them before and after an
   ordinary patch, and requires equality. This closes the count-vs-content gap of section 1(1)
   and makes `safety.py`'s "the regression report still proves that its XML stayed put" true.
   It changes no coordinate space and no stored identity.

3. **Collapse the remaining duplicate run/offset computations** so MathPatch and ArtifactCert
   cannot drift (F6).

4. **Measure what is still refused.** Specifically: of real authorized changes on math-bearing
   paragraphs, how many are *replacements* spanning a math boundary that the deletion-only
   decomposition cannot express (F2)? Only that number decides whether generalized holes are
   worth building. Do not build them first.

Not in M1: the sentinel in persisted text, a new address space (F4), generalized holes.


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

## 7. Canonical representation — and two different writers

    OMML -> source-preserving AST -> mutate smallest node -> OMML   (patch an existing equation)
    LaTeX -> parser -> Math AST -> OMML                             (construct a new equation)
    OMML -> LaTeX -> OMML                                           (never; lossy)

**Revised 2026-09-07.** An earlier version said simply `OMML -> Math AST -> modify -> OMML`.
That invites a writer that *regenerates* the equation subtree — preserving mathematical
structure while quietly changing run properties, control properties, spacing, fonts, and unknown
extension nodes. Regenerating is precisely what this project exists not to do.

So there are two writers, and only one of them touches existing equations:

- **Patch an existing equation.** The AST retains **source provenance** — every node knows which
  OMML element it came from. Changing `E_f` to `E_m` mutates one existing `m:t`, not a freshly
  serialized `m:oMath`. Minimum disturbance, verified by C14N digest of everything else in the
  span.
- **Construct a new equation.** Full AST → OMML generation, used only where no source subtree
  exists.

LaTeX is an input adapter for review findings and newly authored equations. It is never the
representation of an existing Word equation: `OMML -> LaTeX` is lossy, and ArtifactCert already
gets that direction from `dwml` for display (F9), so competing on conversion would be pure
duplication.


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
