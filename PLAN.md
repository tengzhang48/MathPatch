# MathPatch — Plan

**Status:** M0, M0.1 and M1 item 1 (`ParagraphProjection`) complete. Verified against the
**pinned** ArtifactCert commit `b330bf8` (2026-09-08), named in `INTEGRATION_TARGET.txt`.
The pin was advanced from `0992741` on 2026-09-08 after verifying the integration surface is
byte-identical between the two. See the reading discipline in section 3.
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

At the time this was written, the change believed to be required — putting a sentinel into
ArtifactCert's canonical paragraph text — would have rewritten the stored text of every
math-bearing paragraph and every hash derived from it, across a repository with many live
worktrees and a running pilot.

**That migration is withdrawn** (see §2, "The canonical-text contract"): F1 is retracted and
`0992741` already edits prose safely around zero-width math. So the original justification for
repo-first is gone, but the decision stands on a better one: the pure, fixture-testable half —
math structure, protection digests, and later OMML mutation — has no dependency on
ArtifactCert's identity model at all, and develops faster with its own tests. The integration
then lands as one reviewed, additive change.

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

Verified against ArtifactCert `origin/main` = `0992741` (2026-09-07), the commit pinned
in `INTEGRATION_TARGET.txt`. Findings that were read off an earlier, diverged tree are
marked RETRACTED rather than deleted.

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

So the 48.5% is the population *at risk*, not the population currently blocked. The number that
decides whether generalized holes are worth building is: *of real authorized changes on
math-bearing paragraphs, how many are replacements spanning a boundary that the deletion-only
path cannot express?*

**Measured, and it is ZERO of 364** — see M1 item 4. Generalized holes are not being built.


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

### F4 — ArtifactCert already owns math-object addressing (REVISED)

**Revised 2026-09-07.** The earlier version said "no new address space is needed for M1;
math-object addressing enters in Phase 2." The first half stands. The second was wrong:
`0992741` already has first-class equation objects. `docx_manifest._paragraph_child_objects`
emits `("docx_equation", f"{locator}#eq/{n}", None)`, and those objects are used in
technical-review context, not as dead metadata.

So Phase 2 must **not** invent an address space. It must bind to the existing one — and there
is an enumeration mismatch to resolve first (F11).

For M1 this is irrelevant: verification is paragraph-local and needs no equation address.


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

### F10 — Two coordinate systems, and they are not interchangeable

MathPatch's sentinel stream and ArtifactCert's patch stream differ by the number of preceding
sentinels:

    mathpatch text     '\ufffcAB\ufffcCD'   span starts [0, 3]
    _para_text (patch) 'ABCD'                math boundaries [0, 2]

A math span is **one character wide** in the sentinel stream and **zero width** in the patch
stream. So handing a consumer's `span_start`/`span_end` to a sentinel-space function silently
mis-answers whenever math precedes the extent.

Fixed additively in M0.1 rather than by redesign: `ProtectedMathSpan.patch_boundary` carries
the zero-width position in `Projection.patch_text`, and `crosses_math_boundary(p, start, end)`
applies ArtifactCert's own rule — `start < boundary < end`, strict on both sides — to consumer
coordinates. `intersects_math` remains sentinel-space and says so. The integration entry point
is `crosses_math_boundary`.

### F11 — ArtifactCert counts 2 equation objects where MathPatch sees 1 span

`_paragraph_child_objects` iterates `p.iter()` and emits a `docx_equation` for **every** element
in `_MATH_TAGS`. MathPatch deliberately treats an outermost `m:oMathPara` as **one** span and
does not descend into it. So a display equation shaped `m:oMathPara > m:oMath` becomes two
ArtifactCert equation objects for one MathPatch span.

Measured across the corpus:

| | ArtifactCert `docx_equation` | MathPatch spans | mismatched paragraphs |
|---|---|---|---|
| Hygrochastic Revision v5 | 114 | 90 | 24 |
| all six others | 1077 | 1077 | 0 |
| **total** | **1191** | **1167** | **24** |

Every mismatch is the `oMathPara` case, and the surplus is exactly Hygrochastic's 24 display
equations.

**M2 must open with this**, because the two enumerations must become a one-to-one binding
before an equation can be addressed and mutated. Existing equation object ids should not be
renumbered casually — live findings may already reference them — so the resolution is a
binding decision, not a renumbering, and it must not introduce a third address scheme.


### F12 — Content+placement equality would refuse correct patches

The first protected-math oracle here was `paragraph_fingerprint` equality over
`(kind, ordinal, patch_boundary, path, digest)`. That is wrong, and the tests missed it because
the "stable under an unrelated edit" case edited text *after* the equation, where the boundary
does not move.

The counterexample is an ordinary authorized edit:

    before  "The result "           [eq] " is..."     patch_boundary 11
    after   "The numerical result " [eq] " is..."     patch_boundary 21

Same OMML, same `source_path`, same `ordinal` — the equation has not moved at all — but more
text precedes it, so its boundary shifts and fingerprint equality fails. M1 would have reported
that the equation moved and refused a correct patch.

So the oracle is split in two:

- **`paragraph_identity`** = `(kind, ordinal, source_path, c14n_digest)` per span. Compared for
  equality; invariant under any authorized prose edit; still catches a genuine move, because a
  move changes `source_path` (and usually the ordinal).
- **`expected_boundaries(before_spans, edits)`** = where each boundary must land, computed from
  the authorized changed middles. A boundary shifts by the net length delta of every edit ending
  at or before it, is unaffected by edits beginning at or after it, and an edit strictly
  containing one raises `BoundaryCrossing`. Compared against `actual_boundaries` after the patch.

Together: the equations are the same equations, unchanged, in the same structural places, sitting
exactly where the authorized text transformation implies. `span_fingerprint` survives as a
diagnostic snapshot and is documented as *not* a cross-patch oracle.

This is only simple because generalized holes were dropped — a successful edit extent never
crosses a boundary, so the transform is a sum of deltas rather than a splice model.

### F13 — Three integers cannot place a zero-width insertion

`expected_boundaries` originally took `(start, end, new_length)` triples and shifted a boundary
whenever `end <= boundary`. That is under-specified. `A [eq] B` has patch text `"AB"` with a
boundary at 1, and both of these narrow to the identical changed middle `(1, 1, 1)`:

    A -> AX     the text lands BEFORE the equation      boundary 1 -> 2
    B -> XB     the text lands AFTER  the equation      boundary stays 1

Verified: both produce `patch_text == "AXB"`, with boundaries 2 and 1 respectively. The old
function answered `2` for both, so it was wrong half the time on precisely the case it exists to
police.

The consumer already knows the answer — its insertion logic chose a host run, and a prefix and a
suffix insertion deliberately inherit from different sides — so the information was thrown away
at the API, not missing. `AuthorizedTextEdit` now carries `affinity` (`"left"`/`"right"`), which
is **required** for a zero-width insertion whose position coincides with a boundary and ignored
everywhere else; omitting it raises `AmbiguousInsertion` rather than guessing.
`affinity_from_host(host_path, math_path)` derives it from document order alone, so no Word
formatting policy crosses the boundary, and refuses when the host contains the equation.

The same review pass found `expected_boundaries` trusted its caller for the rest, too: it
accepted extents outside the paragraph and overlapping edit sets, returning plausible numbers for
impossible inputs. It now takes the BEFORE `ParagraphProjection` rather than bare spans, so it
can validate extents against the real paragraph length, and it refuses overlapping edits.

### F14 — The raw index path is not stable under a legitimate edit

`math_identity` originally compared `source_path`, the element's raw index path within the
paragraph. That is not invariant under an authorized text edit.

`engine._rewrite_run_text` collapses a run's several `w:t` elements into one (and adds one to a
run that had none). Everything after them *inside that run* shifts index. Reproduced against the
pin, editing the text of a run that also contains an equation:

    source_path      (0, 2)  ->  (0, 1)
    paragraph_identity            NOT stable  -- false positive

Same failure mode as F12, one level down: an ordinary edit that moves nothing would have been
reported as an equation moving. The shape (math inside a `w:r`) occurs 0 times in 4,645 real
paragraphs, but an oracle that *can* false-positive is exactly what F12 was about, so it is
fixed rather than documented away.

`MathSegment` now carries two paths with two jobs:

- **`source_path`** — raw indices. It **locates**: following it from the paragraph reaches
  exactly this element. Invariant 11 tests that.
- **`structural_path`** — indices counting only structural siblings, skipping `w:t` and property
  elements. It is what **identity** compares. Under the collapse above it stays `(0, 0)`, while
  a genuine move still shifts it — `(1,)` to `(2,)` for `A [eq] B` becoming `A B [eq]`.

Comments and property elements consume no structural index either, so adding one cannot move an
identity. The gate now checks structural paths are unique per span and the same depth as the raw
path; making them collide yields FAIL=10 on one manuscript.

### F15 — Editing a run that contains an inline equation RELOCATES the equation

Found by running the oracle against real patches (M1 item 2's acceptance test). This is a
defect in ArtifactCert at the pinned commit, not in MathPatch, and the oracle catching it is
the clearest justification the oracle has.

    BEFORE run children: ["t('in-run ')", 'oMath', "t('tail')"]     boundary (7,)
    safety.analyze_paragraph(p, 0, 6): ok=True
    AFTER  run children: ["t('IN-RUN EDITED tail')", 'oMath']       boundary (18,)

Three things line up:

1. `safety.analyze_paragraph` scans the paragraph's **direct children** for `_MATH_TAGS`, so an
   `m:oMath` inside a `w:r` is invisible to it and the edit is not refused.
2. `_apply_to_runs` reads the run's text with `.iter(qn_w("t"))`, which spans the equation,
   rewrites the whole thing into the first `w:t`, and removes the rest.
3. The equation therefore ends up after all of the run's text — moved from mid-sentence to the
   end of the paragraph.

And nothing existing detects it: the engine's conformance check compares canonical text, in which
math is **zero width**, so it passes. The regression report's `oMath` count is unchanged too. The
defect is invisible to every current proof **by construction**.

MathPatch's boundary half catches it — predicted 14, observed 18 — while the identity half cannot,
because `structural_path` skips `w:t` and so reads the same before and after. That is exactly why
the oracle has two halves (F12), and it is the first time the two-part design has paid for itself
on something neither half alone would find.

**Reachability: latent.** The shape (math inside a `w:r`) occurs 0 times in 4,645 real paragraphs
across 7 manuscripts, so no real edit has hit it. It is reported for the record, not as an
emergency, and `tests/fixtures/descent.docx` `body/p/4` keeps it exercised: the acceptance test
lists a boundary mismatch there as the EXPECTED outcome, so the day it stops mismatching is the
day someone fixed it.

Suggested fix on the ArtifactCert side, if it is ever wanted: have safety detect math anywhere
below a candidate run, not just among the paragraph's direct children — the same descent-versus-
scan point as F5.

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

**Note on interpreting these numbers:** "with math" is the share of text-bearing
paragraphs that CONTAIN math. It is **not** a refusal rate — at `0992741` a math-bearing
paragraph is editable, and only an edit crossing a math boundary is refused (F1, retracted).
Nor is it a recovery rate. See F2 for what is actually still refused.

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

Coordinates and the protected-math oracle (from the second review pass):

- **`patch_boundary` and `path` on every span** (F10, F11). A span is one character wide in the
  sentinel stream and zero width in the consumer's stream; `crosses_math_boundary` applies
  ArtifactCert's own strict rule to consumer coordinates, and `intersects_math` is documented as
  sentinel-space only.
- **`paragraph_fingerprint` = content AND placement.** A C14N digest cannot see an equation that
  moved; the fingerprint adds patch-coordinate position and structural path, with a test that
  fails without it.
- **`CANONICAL_TEXT_CONTRACT_VERSION` bumped to 1.1.0**, as the projection's own rule requires:
  nested-run text is now included, an authored sentinel is refused, and spans carry two new
  coordinates.

The pin (the reason all of this was necessary):

- **`INTEGRATION_TARGET.txt`** names the ArtifactCert commit this milestone is verified against.
  `verify_m0.sh` checks out exactly that revision into a temporary worktree and runs everything
  against it; `make_evidence.py` refuses to write a record whose ArtifactCert HEAD differs, and
  refuses to write one at all from a dirty MathPatch tree, a failing test run, or a corpus with
  errors. The previous evidence record named `0992741` while the tree actually imported was
  `a95733c` — honest about the divergence, but certifying nothing.
- **Fixture determinism.** `ZipFile.writestr()` stamps the current time into every entry, so the
  reproducibility check could never pass and CI was red for that reason. Fixed ZipInfo dates plus
  `ZIP_STORED` remove the clock and the compressor from the output.
- **CI is manual-only** and the matrix now covers the declared 3.10 floor;
  `tools/test_local.sh` runs the same steps with no Actions minutes.
- **`c14n_roundtrip_probe.py` uses the hardened parser**, matching the production path rather
  than parsing more permissively than the code it certifies.

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
   ParagraphProjection
     ├─ patch_text               "AB"          (= _para_text, the edit coordinate stream)
     ├─ segments[]               kind, source element, [start, end)
     │                             kind ∈ {text, math_boundary, opaque}
     └─ protected_spans[]        element, patch_boundary, ordinal, kind, path, digest
   ```

   One structural traversal, from which a consumer selects its own projections. This is the
   single most valuable piece of the milestone: ArtifactCert's analyzer and writer consume one
   authoritative model instead of rebuilding offsets, which retires F6.

   **MathPatch should NOT own `review_text`** — a point worth stating because an earlier sketch
   of this milestone had it. ArtifactCert's reviewer stream additionally decodes legacy `w:sym`
   glyphs through a carefully bounded Adobe Symbol mapping that refuses unknown fonts because
   "guessing them would silently change scientific content" (F8). That is substantial non-math
   Word semantics and a policy decision about scientific fidelity. Absorbing it to produce a
   convenient `review_text` would turn MathPatch into a generic Word paragraph canonicalizer and
   blur the boundary the whole package is organised around. The division:

   ```
   MathPatch      the structural segment map: w:t segments, math boundaries,
                  opaque segments, and the source element behind each
   ArtifactCert   patch_text  = select the w:t segments
                  review_text = w:t segments + its existing w:sym decoder
   ```

   That still gives one traversal, so F6 cannot recur, without moving symbol policy across the
   boundary.

2. **Add protected-math verification to the existing patch path — identity plus a boundary
   transform, not fingerprint equality.** Before and after an ordinary patch, ArtifactCert
   requires:

   ```
   paragraph_identity(after) == paragraph_identity(before)
   actual_boundaries(after)  == expected_boundaries(before_projection, edits)
   ```

   where `edits` are `AuthorizedTextEdit(start, end, new_length, affinity)` records over the
   changed middles. `affinity` is required only for a zero-width insertion sitting exactly on a
   boundary, where three integers are genuinely ambiguous (F13); ArtifactCert can derive it from
   the host its insertion logic already chose, via `affinity_from_host`.

   The first is equality of `(kind, ordinal, structural_path, c14n_digest)` per span and is
   invariant under prose edits, including a `w:t` collapse (F14). The second predicts where each zero-width boundary must land. Requiring
   `patch_boundary` equality instead would refuse correct patches — see F12, which is why the
   oracle is shaped this way.

   This closes the count-vs-content gap of section 1(1): today the regression report records only
   a document-wide `oMath` count, so `safety.py`'s "the regression report still proves that its
   XML stayed put" claims more than the code establishes. It changes no coordinate space and no
   stored identity.

3. **Collapse the remaining duplicate run/offset computations** so MathPatch and ArtifactCert
   cannot drift (F6).

4. **Measure what is still refused — ANSWERED, and the answer is ZERO.**
   `tools/measure_math_refusals.py` replays the pinned engine's decision path over every
   `change_spec_items` row in the real ledgers — 364 authorized edits across three projects:

   | bucket | count | |
   |---|---|---|
   | no math in the paragraph | 319 | works |
   | outside the math boundary | 42 | works |
   | deletion around math (decomposition) | 2 | works |
   | **replacement crossing math** | **0** | **nothing is blocked** |
   | refused for a non-math reason | 1 | comment anchor |
   | not locatable / no-op | 0 | |

   **363 of 364 authorized edits already apply**, and not one is blocked by the
   cross-equation replacement case. **Generalized holes are conclusively unjustified and will
   not be built.**

   **CORRECTION (first run said "2").** The first version of this tool handed the FULL
   reviewer-quoted span to `safety.analyze_paragraph`. The engine does not: for a replacement it
   first calls `narrow_to_changed_middle` and safety follows only the characters that actually
   change (`engine.py:644-651` — *"Unchanged citation/math context in the human-approved quote
   stays untouched"*). A quoted phrase may span an equation while the changed middle does not:
   `"where [eq] gives the result"` with only `gives`→`yields` changing is accepted. So "2 of 364"
   was an upper bound produced by a tool that did not replay the path it claimed to. With
   narrowing applied, both of those become "outside the math boundary", and 6 of the 7 non-math
   refusals resolve too (via narrowing and the insert-beside-protected-text path).

   The tool now verifies ArtifactCert's HEAD equals the pin before measuring, and no longer
   converts an exception into `worked=False` — a tool bug must not masquerade as a genuine
   refusal.

   Incidental: the deletion decomposition fires exactly twice in the whole history.

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


## 7a. ParagraphProjection — the data model — **IMPLEMENTED 2026-09-08**

This is the seam both packages consume. Changing its shape after ArtifactCert depends on it
costs far more than another review round, so it was specified and reviewed before being built.

**Status:** implemented in `canonical.project` / `spans.py`, contract version **1.2.0**. All 15
invariants below have adversarial tests in `tests/test_projection.py` (30 tests), written first
and proved red. The drift gate still passes against the pin — 4,654 paragraphs, 1,175 spans,
FAIL=0 — so `patch_text` remains byte-identical to `_para_text`, and the gate now also checks
`sentinel_start - ordinal == patch_boundary` on every span. The corpus shape baseline is
unchanged (112 / 87 / 32).

One invariant was sharpened during implementation: see 11.

### Shape

```
ParagraphProjection
    patch_text : str                     # PRIMARY. == artifactcert _para_text
    segments   : tuple[Segment, ...]     # document order
    anomalies  : tuple[str, ...]

    sentinel_text : str                  # DERIVED view, not primary
    math_segments : tuple[MathSegment, ...]

TextSegment
    source_element  : w:r                # the DIRECT w:r child, not the w:t
    source_path     : tuple[int, ...]
    text            : str
    patch_start     : int
    patch_end       : int                # patch_end - patch_start == len(text)
    pieces          : tuple[TextPiece, ...]

TextPiece                                # which w:t owns which characters
    element         : w:t
    local_start     : int                # offset within TextSegment.text
    local_end       : int                # absolute = patch_start + local_start

MathSegment
    source_element  : m:oMath | m:oMathPara   # OUTERMOST only
    source_path     : tuple[int, ...]    # raw indices; LOCATES the element
    structural_path : tuple[int, ...]    # skips w:t and property elements; IDENTITY
    patch_boundary  : int                # zero-width position in patch_text
    sentinel_start  : int                # == patch_boundary + ordinal
    sentinel_end    : int                # == sentinel_start + 1
    ordinal         : int                # 0..n-1 in document order
    kind            : "oMath" | "oMathPara"
    wrapper         : str | None         # containing structure, if not a w:p child
    identity        : (kind, ordinal, structural_path, c14n_sha256)   # the oracle
    fingerprint     : (kind, ordinal, patch_boundary, source_path, c14n_sha256)  # diagnostic

OpaqueSegment
    source_element  : etree._Element
    source_path     : tuple[int, ...]
    patch_boundary  : int
    tag             : str                # qualified tag, verbatim
    local_name      : str                # "sym" | "hyperlink" | "fldSimple" | "sdt" | "ins" | ...
```

### Two decisions, both settled in review

**`patch_text` becomes primary and the sentinel stream becomes a derived view.** Today it is the
other way round: `Projection.text` is the sentinel stream. The consumer's coordinates are the
ones that decide which characters an edit overwrites, so they should be the primary ones, and the
sentinel should be what it actually is — a rendering convenience for showing a reviewer where an
equation sits in a sentence. This is a breaking rename (`text` -> `sentinel_text`), and it is
much cheaper now than after integration.

**`TextSegment` is per-`w:r`, not per-`w:t`.** ArtifactCert's `RunFragment` is
`(run, start, end)` over a direct `w:r` child, and the whole point of the segment map is that its
analyzer and writer stop rebuilding those offsets. So a `TextSegment` maps 1:1 onto a
`RunFragment`.

**And it carries `TextPiece` sub-ranges.** A bare tuple of `w:t` elements is not enough: a writer
must answer *"which text element owns character 13?"* to rewrite minimally, and a run can hold
several `w:t` nodes (`_para_text` even reaches nested ones — F6). Without the sub-ranges
ArtifactCert would re-walk the run to find out, recreating a smaller version of the very drift
this map exists to end. Offsets are **local** to the segment so a segment is self-contained;
absolute is `patch_start + local_start`.

### `opaque` means "MathPatch does not interpret this" — never "these are equivalent"

`OpaqueSegment` carries the qualified tag and the structural position, and **nothing else**.
MathPatch must never report that something "is a citation", that a `w:sym` "means σ", or that a
content control "is safe". Those are Word-fidelity and review-policy judgements, and they belong
to the consumer:

```
MathPatch      structural map: text segments, math boundaries, opaque segments,
               each with its source element and path
                    │
                    ├── ArtifactCert patch_text   selects the w:t stream
                    └── ArtifactCert review_text   adds its own w:sym decoding
                                                   and fidelity rules
```

The API must therefore expose enough for a consumer to distinguish `w:sym`, hyperlink, field,
content control, revision wrapper, and unknown element **without MathPatch classifying them**.
Naming the tag does that; a shared `opaque` bucket with hidden policy behind it would not.

### Invariants (each becomes an adversarial test before integration)

1. **Text partition.** Concatenating every `TextSegment.text` in order yields exactly
   `patch_text` — no gaps, no overlaps, no reordering.
2. **Contiguity.** `TextSegment` extents are non-overlapping and non-decreasing, and every
   character of `patch_text` belongs to exactly one.
3. **Zero width.** `MathSegment` and `OpaqueSegment` have a `patch_boundary` and no extent; they
   consume no character of `patch_text`.
4. **Drift.** `patch_text == artifactcert.docx_manifest._para_text(p)`, byte for byte, on every
   paragraph of the corpus. This is the existing gate and it stays.
5. **Total, non-overlapping math.** Every math element in the paragraph is exactly one
   `MathSegment` or a descendant of exactly one. `m:oMathPara` is one segment, never two. Both
   halves are checked: coverage catches under-reporting, and a nesting check catches
   double-counting. The non-overlap half was untested until the implementation self-audit.
6. **Ordinals.** `MathSegment.ordinal` runs 0..n-1 in document order and indexes
   `math_segments`.
7. **The crossing rule is the consumer's.** `crosses_math_boundary(start, end)` returns exactly
   the `MathSegment`s with `start < patch_boundary < end` — strict both sides, matching
   ArtifactCert `0992741`.
8. **No interpretation.** No segment field carries a decoded value or a semantic class. An
   `OpaqueSegment` for a `w:sym` exposes the tag and position, never the glyph it maps to.
9. **Derived view agrees.** `sentinel_text` with sentinels removed equals `patch_text`, and each
   `MathSegment`'s sentinel position minus its ordinal equals its `patch_boundary`.
10. **Refusal, not repair.** An authored U+FFFC raises `SentinelCollision`; a shape MathPatch
    cannot place is reported in `anomalies` rather than silently dropped.
11. **Path identity.** `source_path` locates the segment's source element within the
    paragraph — following the index path reaches exactly that element. The uniqueness key is
    `(source_path, position)`, **not** `source_path` alone: a run whose text is interrupted by
    interior structure (a `w:sym` between two `w:t`) yields one `TextSegment` per contiguous
    stretch, all carrying that run's path, which is correct because grouping by
    `source_element` is how a consumer recovers the `RunFragment`. Sharpened during
    implementation after the predicted collision was reproduced.
12. **Identity invariance.** `paragraph_identity` is unchanged by any authorized prose edit,
    *including one that changes the length of text before an equation*. The earlier form of this
    invariant was self-contradictory — it demanded both that the fingerprint change when
    `patch_boundary` changes and that it not change under an unrelated edit, which conflict
    exactly when the unrelated edit precedes the equation (F12).
13. **Identity sensitivity.** `paragraph_identity` changes if an equation's contents change, its
    `source_path` changes, its `ordinal` changes, or a span appears or disappears.
14. **Boundary transform.** Boundaries are verified by computation, never by equality:
    `actual_boundaries(after) == expected_boundaries(before, authorized_changed_middles)`. An
    edit extent strictly containing a boundary raises `BoundaryCrossing` rather than returning a
    guess.
15. **Piece partition.** Within a `TextSegment`, the `TextPiece` ranges are ordered,
    non-overlapping, and concatenate to exactly `TextSegment.text`; every character of the
    segment belongs to exactly one piece.
16. **Structural stability.** `structural_path` is unchanged by anything that is not a move:
    collapsing a run's `w:t` elements, adding or removing a comment, adding a property element.
    It changes when an equation actually moves. It is unique per span and the same depth as
    `source_path`. `source_path` carries no such guarantee -- it is for locating, not comparing
    (F14).

### Self-audit of the implementation (2026-09-08)

Mutation-testing the drift gate after the refactor found **two blind spots**, both now closed.
Each mutation was verified to have applied before its result was believed.

- **Segment extents were unchecked on real documents.** `patch_text` is *built* by joining the
  text segments, so comparing it against `_para_text` cannot detect corrupted extents. A
  mutation breaking every `patch_start`/`patch_end`/`patch_boundary` while leaving `patch_text`
  intact **passed the gate**. Invariants 1, 2, 3 and 15 were only ever exercised on synthetic
  fixtures — and they are exactly the fields ArtifactCert will consume for its run coordinates.
  The gate now validates the text partition, the piece partition, and that zero-width boundaries
  lie in range. That mutation now yields FAIL=19; a corrupted `TextPiece` offset yields FAIL=107.
- **Span non-overlap was unchecked.** Coverage ("every math element is a span or inside one")
  detects *under*-reporting only. Double-counting an `m:oMathPara` with its inner `m:oMath`
  satisfies coverage perfectly and inflated the span count 98 → 123 **undetected** — the exact
  bug outermost-only discovery exists to prevent (F11). The gate now asserts no span is nested
  inside another, and a unit test cross-checks the count against `outermost_math` computed
  independently of the projection. That mutation now yields FAIL=25.

One further fail-open path was closed rather than left: `flush()` silently discarded text
buffered with no enclosing run, which would have made a traversal bug look like missing text. It
now raises, and the gate reports it as a finding instead of crashing.

A third mutation initially looked like a blind spot and was not one — with the silent discard in
place it was behaviourally inert, so it never produced the leak it was meant to simulate. Worth
recording because "the gate passed" and "the mutation did nothing" are indistinguishable without
checking, and only one of them is a finding.

### Second audit round (2026-09-08)

Reviewing the boundary oracle turned up two more defects of the same family, both reproduced
against the pin before being fixed.

- **F13, zero-width insertion affinity.** `expected_boundaries` took `(start, end, new_length)`
  triples, which cannot say which side of an equation an insertion landed on. Verified: `A -> AX`
  and `B -> XB` both narrow to `(1, 1, 1)` and both yield `patch_text "AXB"`, with boundaries 2
  and 1 respectively. The old function answered `2` for both. Now `AuthorizedTextEdit.affinity`
  is required in exactly that case and `AmbiguousInsertion` is raised otherwise.
- **F14, raw paths shift under a `w:t` collapse.** `math_identity` compared `source_path`, which
  moves when `_rewrite_run_text` collapses a run's text nodes. Now it compares `structural_path`.

Also fixed in the same pass: `expected_boundaries` trusted its caller entirely — it accepted
`(99, 99, 1)` on a 6-character paragraph and two overlapping edits, returning plausible numbers
for impossible input. It now takes the BEFORE projection so it can validate against the real
paragraph, and refuses overlapping edit sets. It does **not** invent a rule for two insertions
competing for one position: ArtifactCert's `_insertions_share_a_slot` judges that using anchor
spans MathPatch does not have, so admissibility stays with the consumer's composition gate.

And one test was removed rather than kept: `assert ... or True`, which could never fail. The
condition it claimed to cover is unreachable through any input fixture and is verified by
mutation instead, which the file now says plainly.

### What this model deliberately does not have

No holes machinery (measured unnecessary — M1 item 4), no equation address space (F4: ArtifactCert
already owns it), no `review_text`, no symbol decoding, no persisted-identity role.

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
        test_local.sh              # CI-equivalent; needs only this repo
        make_evidence.py           # M0_EVIDENCE.json, fails closed on the pin
        measure_math_refusals.py   # answered M1 item 4: 0 of 364
        oracle_acceptance.py       # M1 item 2 acceptance: 44/44 real, F15 found
    tests/
        fixtures/descent.docx   # generated; the only source of wrapper-nested math

Module split follows implementation pressure; do not create files speculatively.
