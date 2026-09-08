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

from lxml import etree

from .spans import ProtectedMathSpan

C14N_KWARGS: dict[str, bool] = {"exclusive": True, "with_comments": True}


def c14n_bytes(el: etree._Element) -> bytes:
    """Canonical (C14N 1.0, exclusive, comments retained) serialization of `el`."""
    return etree.tostring(el, method="c14n", **C14N_KWARGS)


def digest(el: etree._Element) -> str:
    """sha256 of `el`'s canonical serialization."""
    return hashlib.sha256(c14n_bytes(el)).hexdigest()


def span_digest(span: ProtectedMathSpan | etree._Element) -> str:
    """sha256 of a protected span's canonical serialization."""
    el = span.element if isinstance(span, ProtectedMathSpan) else span
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
    and MathPatch does not implement generalized holes -- measured unnecessary, 2 of 364
    real authorized edits. So a crossing extent has no defined boundary transform.
    """


def expected_boundaries(
    spans: tuple[ProtectedMathSpan, ...] | list[ProtectedMathSpan],
    edits: tuple[tuple[int, int, int], ...] | list[tuple[int, int, int]],
) -> tuple[int, ...]:
    """Where each math boundary MUST land after the given authorized edits.

    `spans` are the BEFORE spans; `edits` are `(start, end, new_length)` triples in
    BEFORE patch coordinates -- the *changed middles*, not the full reviewer-quoted
    spans, because that is what the consumer actually rewrites
    (`engine.narrow_to_changed_middle`).

    A boundary shifts by the net length delta of every edit that ends at or before it,
    and is unaffected by edits that begin at or after it. An edit strictly containing a
    boundary raises `BoundaryCrossing`.

    Pair this with `paragraph_identity` equality: together they say the equations are
    the same equations, unchanged, still in the same structural places, and sitting
    exactly where the authorized text transformation implies they should.
    """
    out: list[int] = []
    for span in spans:
        boundary = span.patch_boundary
        delta = 0
        for start, end, new_length in edits:
            if start > end:
                raise ValueError(f"edit extent [{start}, {end}) is inverted")
            if start < boundary < end:
                raise BoundaryCrossing(
                    f"edit extent [{start}, {end}) strictly contains the math boundary "
                    f"at {boundary}; generalized holes are not implemented"
                )
            if end <= boundary:
                delta += new_length - (end - start)
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
