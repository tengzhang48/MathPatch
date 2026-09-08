"""Segment types and Office Math discovery.

One structural traversal of a paragraph (`canonical.project`) yields a partition of it
into three kinds of segment. A consumer selects its own projections from that map; see
PLAN.md section 7a for the frozen contract and its invariants.

Two coordinate systems, deliberately separate (PLAN.md F10):

- **patch coordinates** index `ParagraphProjection.patch_text`, which equals
  ArtifactCert's `docx_manifest._para_text`. This is the space a consumer's edit extents
  live in, so it is the primary one. Math and other non-text structure are ZERO WIDTH
  here, positioned by a single `patch_boundary`.
- **sentinel coordinates** index the derived `sentinel_text` view, where each math span
  occupies one U+FFFC. Useful for showing a reader where an equation sits in a sentence,
  and nothing else. The two differ by the number of preceding sentinels.

Outermost-only math discovery matters: every `m:oMathPara` wraps at least one `m:oMath`,
so a descent that recursed into a match would double-count. Measured on Hygrochastic
Revision v5: naive descent finds 114 elements where there are 90 spans. Discovery is by
DESCENT rather than a scan of the paragraph's direct children, because math nested in a
revision wrapper, hyperlink, or run is still a span that must be protected, and
under-reporting is the dangerous direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

OMATH = f"{{{M_NS}}}oMath"
OMATHPARA = f"{{{M_NS}}}oMathPara"
MATH_TAGS = frozenset({OMATH, OMATHPARA})

#: One OBJECT REPLACEMENT CHARACTER stands for one math span in `sentinel_text`.
#: U+FFFC is the Unicode-designated placeholder for an embedded non-text object, is not
#: a plausible authored character in a manuscript, and is exactly one code point wide.
SENTINEL = "￼"

#: Property and bookkeeping elements. Excluded from the segment map because they are not
#: content and occupy no position in the text stream -- a structural distinction, not a
#: semantic judgement. Reporting one per run would flood the map with noise.
BENIGN_TAGS = frozenset(
    f"{{{W_NS}}}{name}"
    for name in ("rPr", "pPr", "sectPr", "proofErr", "lastRenderedPageBreak")
)


def qn(local: str) -> str:
    """Qualify a WordprocessingML local name."""
    return f"{{{W_NS}}}{local}"


def local_name(el: etree._Element) -> str:
    return etree.QName(el).localname


@dataclass(frozen=True, slots=True)
class TextPiece:
    """Which `w:t` owns which characters of a `TextSegment`.

    Exists so a writer never has to re-walk a run to answer "which element owns
    character 13?" -- doing that would recreate a smaller version of the duplicate-
    coordinate drift this map exists to end (PLAN.md F6). Offsets are LOCAL to the
    segment, so a segment is self-contained; absolute is `patch_start + local_start`.
    """

    element: etree._Element
    local_start: int
    local_end: int


@dataclass(frozen=True, slots=True)
class TextSegment:
    """A contiguous stretch of editable text contributed by one direct `w:r` child.

    A run whose children are only `w:t` yields exactly one of these, which maps 1:1 onto
    ArtifactCert's `RunFragment(run, start, end)`. A run that interleaves text with other
    structure yields one segment per contiguous stretch; group by `source_element` to
    recover the run.
    """

    source_element: etree._Element
    source_path: tuple[int, ...]
    text: str
    patch_start: int
    patch_end: int
    pieces: tuple[TextPiece, ...] = ()


@dataclass(frozen=True, slots=True)
class MathSegment:
    """One outermost math element, positioned in both coordinate systems.

    `patch_boundary` is the zero-width position in `patch_text`; `sentinel_start` /
    `sentinel_end` bracket its single sentinel in `sentinel_text` and always differ by
    one. `source_path` is the element's index path within the paragraph, which makes
    PLACEMENT comparable: a C14N digest proves contents are unchanged but not that an
    equation stayed where it was (PLAN.md F12).

    All coordinates are relative to the paragraph and carry no document address:
    MathPatch never owns addressing.
    """

    source_element: etree._Element
    source_path: tuple[int, ...]
    structural_path: tuple[int, ...]
    patch_boundary: int
    sentinel_start: int
    sentinel_end: int
    kind: str
    ordinal: int
    wrapper: str | None = None

    # -- legacy vocabulary, one object underneath ------------------------------------
    @property
    def element(self) -> etree._Element:
        return self.source_element

    @property
    def path(self) -> tuple[int, ...]:
        return self.source_path

    @property
    def start(self) -> int:
        return self.sentinel_start

    @property
    def end(self) -> int:
        return self.sentinel_end

    @property
    def is_display(self) -> bool:
        """True for `m:oMathPara`, Word's display-equation container."""
        return self.kind == "oMathPara"

    @property
    def is_nested(self) -> bool:
        """True when the span is not a direct child of the paragraph."""
        return self.wrapper is not None

    @property
    def identity(self) -> tuple[str, int, tuple[int, ...], str]:
        """`(kind, ordinal, source_path, c14n_digest)` -- the equality oracle's half."""
        from .digest import math_identity

        return math_identity(self)

    @property
    def fingerprint(self) -> tuple[str, int, int, tuple[int, ...], str]:
        """Full diagnostic observation, including `patch_boundary`. NOT a cross-patch
        oracle -- see `digest.span_fingerprint`."""
        from .digest import span_fingerprint

        return span_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OpaqueSegment:
    """Structure MathPatch does not interpret, positioned but not explained.

    "Opaque" means *"MathPatch does not interpret this"* -- never *"these are
    equivalent"*. The qualified `tag` and `local_name` are reported verbatim so a
    consumer can distinguish `w:sym` from a hyperlink from a field from a content control
    from a revision wrapper from an unknown element, and decide what each MEANS for
    review, patching, and Word fidelity.

    MathPatch must never report that something "is a citation", that a `w:sym` "means σ",
    or that a content control "is safe". ArtifactCert owns the bounded Adobe Symbol
    mapping and its fail-closed policy for unknown fonts; absorbing that here would turn
    this package into a generic Word paragraph canonicalizer.
    """

    source_element: etree._Element
    source_path: tuple[int, ...]
    patch_boundary: int
    tag: str
    local_name: str


Segment = TextSegment | MathSegment | OpaqueSegment

#: Retained name for the math span type; `MathSegment` is the same object.
ProtectedMathSpan = MathSegment


def outermost_math(el: etree._Element) -> Iterator[etree._Element]:
    """Yield outermost math descendants of `el` in document order.

    Never recurses into a match, so `m:oMath` inside `m:oMathPara` is not yielded
    separately. `el` itself is not considered, only its descendants.
    """
    for child in el:
        if child.tag in MATH_TAGS:
            yield child
        elif isinstance(child.tag, str):
            yield from outermost_math(child)


def has_math(el: etree._Element) -> bool:
    """True if any math element appears at or below `el`."""
    return el.tag in MATH_TAGS or any(d.tag in MATH_TAGS for d in el.iter())
