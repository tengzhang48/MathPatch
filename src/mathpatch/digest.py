"""Canonicalized digests of protected math subtrees.

A protection oracle must prove a subtree did not change across a patch. Raw
serialization is the wrong basis: `lxml` legitimately perturbs untouched subtrees on
reserialization (namespace declarations move, empty-element forms and attribute order
normalize). XML canonicalization removes exactly that noise.

Parameters were chosen on measurement, not taste. `tools/c14n_roundtrip_probe.py`
found all four candidate parameter sets stable across 499 real math spans under a
parse -> mutate -> reserialize -> reparse round trip, including a mutation inside a
math-bearing paragraph. The choice therefore rests on purpose:

  exclusive=True      matches ArtifactCert's existing `revision_ingest._canonical_xml`,
                      and omits inherited namespace declarations the subtree does not
                      visibly use, so a span that moves in the tree still digests equal.

  with_comments=True  DIVERGES from `revision_ingest`, deliberately. That function
                      hashes textual revision evidence, where comments are noise. This
                      one proves a protected region did not change, so nothing inside
                      it may change undetected -- a comment included. ArtifactCert's
                      `opc_xml.parse_untrusted_xml` already preserves comments
                      (`remove_comments=False`), so they survive to be hashed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from lxml import etree

from .spans import MathSegment, ProtectedMathSpan

if TYPE_CHECKING:  # pragma: no cover
    from .canonical import ParagraphProjection

C14N_KWARGS: dict[str, bool] = {"exclusive": True, "with_comments": True}


def c14n_bytes(el: etree._Element) -> bytes:
    """Canonical (C14N 1.0, exclusive, comments retained) serialization of `el`."""
    return etree.tostring(el, method="c14n", **C14N_KWARGS)


def digest(el: etree._Element) -> str:
    """sha256 of `el`'s canonical serialization."""
    return hashlib.sha256(c14n_bytes(el)).hexdigest()


def span_digest(span: ProtectedMathSpan | etree._Element) -> str:
    """sha256 of a protected span's canonical serialization."""
    el = span.source_element if isinstance(span, MathSegment) else span
    return digest(el)


def span_digests(spans: tuple[ProtectedMathSpan, ...] | list[ProtectedMathSpan]) -> tuple[str, ...]:
    """Ordered digests, for comparing a whole paragraph's protected regions."""
    return tuple(span_digest(s) for s in spans)


def math_identity(span: ProtectedMathSpan) -> tuple[str, int, tuple[int, ...], str]:
    """What must NOT change when prose around an equation is edited.

    `(kind, ordinal, source_path, c14n_digest)` -- contents and structural place.
    Deliberately EXCLUDES `patch_boundary`, because a legitimate authorized edit that
    changes the length of text *before* an equation moves its boundary without moving
    the equation:

        before  "The result "      [eq] " is..."      boundary 11
        after   "The numerical result " [eq] " is..." boundary 21

    Same OMML, same path, same ordinal. An oracle that required boundary equality would
    report that the equation moved and refuse a correct patch. Boundaries are verified
    separately, against a computed expectation -- see `expected_boundaries`.
    """
    return (span.kind, span.ordinal, span.path, span_digest(span))


def paragraph_identity(
    spans: tuple[ProtectedMathSpan, ...] | list[ProtectedMathSpan],
) -> tuple[tuple[str, int, tuple[int, ...], str], ...]:
    """The equality half of the protected-math oracle.

    Equality proves: same span count, same order, same contents, same structural
    placement. It is invariant under any authorized edit to surrounding prose, so it
    can be compared directly before and after a patch.
    """
    return tuple(math_identity(s) for s in spans)


class BoundaryCrossing(ValueError):
    """An authorized edit extent spans a math boundary.

    The pinned consumer refuses these (`safety.py`: `span_start < offset < span_end`),
    and MathPatch does not implement generalized holes -- measured unnecessary: **0 of
    364** real authorized edits are blocked by the cross-equation replacement case once
    the engine's `narrow_to_changed_middle` step is replayed. So a crossing extent has no
    defined boundary transform.
    """


class AmbiguousInsertion(ValueError):
    """A zero-width insertion sits exactly on a math boundary, with no side declared.

    `A [eq] B` has patch text `"AB"` and a boundary at 1. Both of these narrow to the
    same changed middle `(1, 1, 1)`:

        A -> AX     the text lands BEFORE the equation; the boundary moves 1 -> 2
        B -> XB     the text lands AFTER  the equation; the boundary stays at 1

    Three integers cannot tell those apart, so guessing would make the oracle wrong half
    the time on exactly the case it is supposed to police. The consumer already knows the
    answer -- its insertion logic chose a host run -- so it must say which side, either
    by setting `AuthorizedTextEdit.affinity` or by deriving it with `affinity_from_host`.
    """


@dataclass(frozen=True, slots=True)
class AuthorizedTextEdit:
    """One authorized change to a paragraph's patch text.

    `start`/`end` index the BEFORE `patch_text` and describe the *changed middle*, not
    the full reviewer-quoted span -- that is what the consumer actually rewrites
    (`engine.narrow_to_changed_middle`).

    `affinity` is meaningful only for a zero-width insertion (`start == end`) whose
    position coincides with a math boundary, and is REQUIRED there:

      "left"   the inserted text goes before the math element in document order,
               so the boundary shifts right by `new_length`
      "right"  it goes after the math element, so the boundary does not move
    """

    start: int
    end: int
    new_length: int
    affinity: str | None = None

    def __post_init__(self) -> None:
        if self.affinity not in (None, "left", "right"):
            raise ValueError(
                f"affinity must be 'left', 'right' or None, not {self.affinity!r}"
            )
        if self.new_length < 0:
            raise ValueError(f"new_length must be non-negative, not {self.new_length}")


def affinity_from_host(
    host_path: tuple[int, ...], math_path: tuple[int, ...]
) -> str:
    """Derive affinity from the element the consumer's insertion logic chose as host.

    Document order only -- no Word formatting policy crosses this boundary. Index paths
    within a paragraph sort in document order, so a host that precedes the math element
    means the insertion lands before it.

    Raises if the host CONTAINS the math element (one path is a prefix of the other):
    an insertion inside the run that holds the equation could fall on either side, and
    only the consumer knows which.
    """
    shorter = min(len(host_path), len(math_path))
    if host_path[:shorter] == math_path[:shorter]:
        raise AmbiguousInsertion(
            f"host {host_path} and math {math_path} are on the same branch; the host "
            "contains or is contained by the equation, so affinity must be stated "
            "explicitly"
        )
    return "left" if host_path < math_path else "right"


def expected_boundaries(
    before: "ParagraphProjection",
    edits: "Sequence[AuthorizedTextEdit | tuple[int, int, int]]",
) -> tuple[int, ...]:
    """Where each math boundary MUST land after the given authorized edits.

    Takes the BEFORE projection, not just its spans, so it can validate the edit set
    against the actual paragraph rather than trusting its caller for something this
    central. Refuses:

      - an extent outside `[0, len(before.patch_text)]`, or inverted;
      - two edits that overlap (the consumer's composition gate should prevent this, but
        an oracle that computes a plausible answer for an impossible edit set is worse
        than one that refuses);
      - an edit strictly containing a math boundary (`BoundaryCrossing`);
      - a zero-width insertion on a boundary with no affinity (`AmbiguousInsertion`).

    A boundary otherwise shifts by the net length delta of every edit ending at or before
    it, and is unaffected by edits beginning at or after it.

    Pair with `paragraph_identity` equality: together they say the equations are the same
    equations, unchanged, still in the same structural places, and sitting exactly where
    the authorized text transformation implies they should.
    """
    limit = len(before.patch_text)
    normalized: list[AuthorizedTextEdit] = [
        e if isinstance(e, AuthorizedTextEdit) else AuthorizedTextEdit(*e) for e in edits
    ]

    for edit in normalized:
        if not 0 <= edit.start <= edit.end <= limit:
            raise ValueError(
                f"edit extent [{edit.start}, {edit.end}) is not a valid range within "
                f"patch text of length {limit}"
            )

    ordered = sorted(normalized, key=lambda e: (e.start, e.end))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.end > current.start:
            raise ValueError(
                f"edits [{previous.start}, {previous.end}) and "
                f"[{current.start}, {current.end}) overlap; the authorized edit set is "
                "not a valid transformation of one paragraph"
            )

    out: list[int] = []
    for span in before.math_segments:
        boundary = span.patch_boundary
        delta = 0
        for edit in normalized:
            if edit.start < boundary < edit.end:
                raise BoundaryCrossing(
                    f"edit extent [{edit.start}, {edit.end}) strictly contains the math "
                    f"boundary at {boundary}; generalized holes are not implemented"
                )
            if edit.start == edit.end == boundary:
                if edit.affinity is None:
                    raise AmbiguousInsertion(
                        f"a zero-width insertion of {edit.new_length} character(s) sits "
                        f"exactly on the math boundary at {boundary}; declare affinity "
                        "'left' (before the equation) or 'right' (after it)"
                    )
                if edit.affinity == "left":
                    delta += edit.new_length
            elif edit.end <= boundary:
                delta += edit.new_length - (edit.end - edit.start)
        out.append(boundary + delta)
    return tuple(out)


def actual_boundaries(
    spans: tuple[ProtectedMathSpan, ...] | list[ProtectedMathSpan],
) -> tuple[int, ...]:
    """Observed boundaries, for comparison against `expected_boundaries`."""
    return tuple(s.patch_boundary for s in spans)


def span_fingerprint(span: ProtectedMathSpan) -> tuple[str, int, int, tuple[int, ...], str]:
    """Full observation including `patch_boundary`: `(kind, ordinal, patch_boundary,
    path, digest)`.

    Useful as a diagnostic record of what a span looked like at one moment. NOT an
    equality oracle across a patch -- use `paragraph_identity` plus
    `expected_boundaries` for that, because `patch_boundary` legitimately moves when
    prose before the equation changes length.
    """
    return (
        span.kind,
        span.ordinal,
        span.patch_boundary,
        span.path,
        span_digest(span),
    )


def paragraph_fingerprint(
    spans: tuple[ProtectedMathSpan, ...] | list[ProtectedMathSpan],
) -> tuple[tuple[str, int, int, tuple[int, ...], str], ...]:
    """Ordered `span_fingerprint`s. A diagnostic snapshot, not a cross-patch oracle."""
    return tuple(span_fingerprint(s) for s in spans)
