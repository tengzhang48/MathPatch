"""The structural traversal: one paragraph -> one ParagraphProjection.

Text, coordinates, math boundaries and other structure are produced by ONE walk, so
they cannot disagree. This mirrors the discipline in ArtifactCert's
`docx_patch/locator.py`, which is deliberately a re-export of core so two enumerations
cannot drift.

Coordinate space
----------------
`patch_text` is PRIMARY and reproduces ArtifactCert's `docx_manifest._para_text` exactly:
the concatenation of the paragraph's DIRECT `w:r` children's `w:t` text, at any depth
within such a run. That is the space a consumer's edit extents live in, so it is the
space that decides which characters an edit overwrites, and therefore the right space
for a protection oracle. The equality is the M0 gate (`tools/drift_gate.py`).

Two consequences, both deliberate:

  - Text inside a hyperlink, field, content control, or revision wrapper contributes
    NOTHING, because `_para_text` excludes it.
  - A math span inside such a wrapper still gets a boundary, because an unpositioned
    span cannot be protected (PLAN.md F5).

`sentinel_text` is a DERIVED view in which each math span occupies one U+FFFC. It exists
to show a reader where an equation sits in a sentence. It is never the coordinate system
a consumer's offsets are interpreted in (PLAN.md F10).

PLAN.md F7 (RETRACTED) records a past ArtifactCert version whose analyzer advanced its
offset by a hyperlink's text width while `_para_text` omitted that text, skewing the two
spaces. That was fixed before this project existed. The lesson it leaves is why
`patch_boundary` is a distinct field here: a consumer's coordinates and this projection's
sentinel coordinates are different systems and must be converted explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from .spans import (
    BENIGN_TAGS,
    MATH_TAGS,
    SENTINEL,
    MathSegment,
    OpaqueSegment,
    Segment,
    TextPiece,
    TextSegment,
    local_name,
    qn,
)

#: 1.3.0 (2026-09-08): math segments carry `structural_path`, which the identity oracle
#: compares instead of the raw `source_path` -- the raw path is not stable under a run's
#: `w:t` collapse (PLAN.md F14).
#: 1.2.0 (2026-09-08): the projection returns a segment map with `patch_text` primary and
#: `sentinel_text` derived; spans carry `patch_boundary` and `source_path`; text segments
#: carry `TextPiece` sub-ranges. 1.1.0 added nested-run text and the sentinel refusal;
#: 1.0.0 was the M0 projection.
#: Bump on ANY change to the projection. A consumer whose stored artifact identity
#: derives from it must record this value and refuse a mismatch rather than warn: a silent
#: change to the projection is a silent change to that identity.
CANONICAL_TEXT_CONTRACT_VERSION = "1.3.0"


class SentinelCollision(ValueError):
    """A paragraph's authored text already contains the sentinel character.

    Measured absent from the reference corpus (0 occurrences), but absence from one
    corpus is not a property of Word documents. An authored U+FFFC would make
    `sentinel_offsets()` disagree with `math_segments` and silently corrupt the derived
    view, so it is refused rather than assumed away.
    """


@dataclass(frozen=True, slots=True)
class ParagraphProjection:
    """A paragraph as a partition into text, math boundaries, and opaque structure.

    See PLAN.md section 7a for the contract and its invariants.
    """

    patch_text: str
    segments: tuple[Segment, ...]
    anomalies: tuple[str, ...] = ()

    @property
    def math_segments(self) -> tuple[MathSegment, ...]:
        return tuple(s for s in self.segments if isinstance(s, MathSegment))

    @property
    def text_segments(self) -> tuple[TextSegment, ...]:
        return tuple(s for s in self.segments if isinstance(s, TextSegment))

    @property
    def opaque_segments(self) -> tuple[OpaqueSegment, ...]:
        return tuple(s for s in self.segments if isinstance(s, OpaqueSegment))

    @property
    def sentinel_text(self) -> str:
        """`patch_text` with one U+FFFC at each math boundary. Derived, never stored."""
        out: list[str] = []
        cursor = 0
        for seg in self.math_segments:
            out.append(self.patch_text[cursor : seg.patch_boundary])
            out.append(SENTINEL)
            cursor = seg.patch_boundary
        out.append(self.patch_text[cursor:])
        return "".join(out)

    def sentinel_offsets(self) -> tuple[int, ...]:
        return tuple(i for i, ch in enumerate(self.sentinel_text) if ch == SENTINEL)

    def math_boundaries(self) -> tuple[int, ...]:
        """Zero-width math positions in `patch_text`, in document order."""
        return tuple(s.patch_boundary for s in self.math_segments)

    # -- retained vocabulary ----------------------------------------------------------
    @property
    def text(self) -> str:
        """The sentinel view. `patch_text` is the coordinate stream."""
        return self.sentinel_text

    @property
    def spans(self) -> tuple[MathSegment, ...]:
        return self.math_segments


def project(p: etree._Element) -> ParagraphProjection:
    """Project one `w:p` into a segment map. One traversal, document order."""
    segments: list[Segment] = []
    anomalies: list[str] = []
    patch_offset = 0
    ordinal = 0

    # The text stretch currently being accumulated for the enclosing direct run.
    run_el: etree._Element | None = None
    run_path: tuple[int, ...] = ()
    buf: list[str] = []
    pieces: list[TextPiece] = []

    def flush() -> None:
        nonlocal patch_offset, buf, pieces
        if not buf:
            pieces = []
            return
        if run_el is None:
            # Text accumulated with no enclosing direct run. Unreachable by design --
            # `in_direct_run` is only true inside a branch that sets `run_el` -- but
            # silently discarding it would hide a traversal bug as missing text, so it
            # fails closed instead. (A mutation test relied on this being silent.)
            raise AssertionError(
                f"traversal bug: {len(''.join(buf))} characters buffered with no run "
                "context; refusing to drop them silently"
            )
        text = "".join(buf)
        if SENTINEL in text:
            raise SentinelCollision(
                f"authored U+{ord(SENTINEL):04X} at patch offset "
                f"{patch_offset + text.index(SENTINEL)}; the sentinel cannot be "
                "distinguished from a math span"
            )
        segments.append(
            TextSegment(
                source_element=run_el,
                source_path=run_path,
                text=text,
                patch_start=patch_offset,
                patch_end=patch_offset + len(text),
                pieces=tuple(pieces),
            )
        )
        patch_offset += len(text)
        buf, pieces = [], []

    def emit_math(
        el: etree._Element,
        path: tuple[int, ...],
        structural: tuple[int, ...],
        wrapper: str | None,
    ) -> None:
        nonlocal ordinal
        segments.append(
            MathSegment(
                source_element=el,
                source_path=path,
                structural_path=structural,
                patch_boundary=patch_offset,
                # sentinel position = boundary + the sentinels already emitted, which
                # keeps `sentinel_start - ordinal == patch_boundary` true by construction
                sentinel_start=patch_offset + ordinal,
                sentinel_end=patch_offset + ordinal + 1,
                kind=local_name(el),
                ordinal=ordinal,
                wrapper=wrapper,
            )
        )
        ordinal += 1

    def emit_opaque(el: etree._Element, path: tuple[int, ...]) -> None:
        segments.append(
            OpaqueSegment(
                source_element=el,
                source_path=path,
                patch_boundary=patch_offset,
                tag=str(el.tag),
                local_name=local_name(el),
            )
        )

    def walk(
        el: etree._Element,
        path: tuple[int, ...],
        structural: tuple[int, ...],
        wrapper: str | None,
        in_direct_run: bool,
    ) -> None:
        nonlocal run_el, run_path
        structural_index = 0
        for index, child in enumerate(el):
            child_path = path + (index,)
            tag = child.tag

            if not isinstance(tag, str):
                # Comment or processing instruction. lxml gives these a callable tag, so
                # QName() raises on them. ArtifactCert's parser keeps comments
                # (`remove_comments=False`), so they reach us by design: skip. They
                # consume no structural index, so adding one cannot shift an identity.
                continue
            if tag in BENIGN_TAGS:
                continue

            if tag == qn("t"):
                # Text nodes are not structural: a run's several w:t collapse into one
                # under `_rewrite_run_text`, and that must not move anything's identity.
                if in_direct_run:
                    piece_text = child.text or ""
                    if piece_text:
                        local_start = sum(len(part) for part in buf)
                        buf.append(piece_text)
                        pieces.append(
                            TextPiece(
                                element=child,
                                local_start=local_start,
                                local_end=local_start + len(piece_text),
                            )
                        )
                continue

            child_structural = structural + (structural_index,)
            structural_index += 1

            if tag in MATH_TAGS:
                flush()
                emit_math(child, child_path, child_structural, wrapper)
                continue

            if tag == qn("r"):
                direct = (el is p) or in_direct_run
                if in_direct_run and "nested_run" not in anomalies:
                    # `_para_text` reaches this run's text through the enclosing run's
                    # `.iter()`, so dropping it would break strict extension. Word does
                    # not emit the shape (0 of 21,433 measured runs) -- included, and
                    # reported for consumers that would rather fail closed (PLAN.md F6).
                    anomalies.append("nested_run")
                if direct:
                    flush()
                    saved_el, saved_path = run_el, run_path
                    run_el, run_path = child, child_path
                    walk(
                        child,
                        child_path,
                        child_structural,
                        wrapper if wrapper is not None else ("r" if el is p else wrapper),
                        True,
                    )
                    flush()
                    run_el, run_path = saved_el, saved_path
                else:
                    walk(child, child_path, child_structural, wrapper, False)
                continue

            # Anything else: report it structurally, then descend for nested math or for
            # a `w:t` belonging to an enclosing run. MathPatch does not interpret it.
            flush()
            emit_opaque(child, child_path)
            walk(
                child,
                child_path,
                child_structural,
                wrapper if wrapper is not None else local_name(child),
                in_direct_run,
            )

    walk(p, (), (), None, False)
    flush()

    patch_text = "".join(
        seg.text for seg in segments if isinstance(seg, TextSegment)
    )
    return ParagraphProjection(
        patch_text=patch_text,
        segments=tuple(segments),
        anomalies=tuple(anomalies),
    )


def canonical_text(p: etree._Element) -> str:
    """The sentinel view of `p`. For a consumer's coordinates use `patch_text`."""
    return project(p).sentinel_text


def patch_text(p: etree._Element) -> str:
    """The consumer's edit coordinate stream, equal to `_para_text`."""
    return project(p).patch_text


def math_spans(p: etree._Element) -> tuple[MathSegment, ...]:
    """Outermost math segments of `p`, in document order."""
    return project(p).math_segments


def crosses_math_boundary(
    p: etree._Element, patch_start: int, patch_end: int
) -> tuple[MathSegment, ...]:
    """Math boundaries strictly inside the edit extent, in PATCH coordinates.

    This is the integration entry point. It mirrors ArtifactCert's own rule at `0992741`
    exactly -- `safety.py`: `if span_start < offset < span_end` -- so an edit may begin or
    end precisely at a boundary, and only an edit that spans one is reported.

    Use this, not `intersects_math`, when the caller's offsets come from a consumer.
    """
    proj = project(p)
    limit = len(proj.patch_text)
    if not (0 <= patch_start <= patch_end <= limit):
        raise ValueError(
            f"edit extent [{patch_start}, {patch_end}) is not a valid range within "
            f"patch text of length {limit}"
        )
    return tuple(s for s in proj.math_segments if patch_start < s.patch_boundary < patch_end)


def intersects_math(
    p: etree._Element, start: int, end: int
) -> tuple[MathSegment, ...]:
    """Math spans intersecting `[start, end)` in SENTINEL coordinates.

    Offsets index `sentinel_text`, NOT `patch_text`. The two differ by the number of
    preceding sentinels, so a consumer's edit extents must go to
    `crosses_math_boundary` instead -- passing them here silently mis-answers whenever
    math precedes the extent (PLAN.md F10).

    A span that merely abuts the extent does not intersect: an edit may end exactly where
    math begins.
    """
    proj = project(p)
    if not (0 <= start <= end <= len(proj.sentinel_text)):
        raise ValueError(
            f"edit extent [{start}, {end}) is not a valid range within sentinel text of "
            f"length {len(proj.sentinel_text)}"
        )
    return tuple(
        s for s in proj.math_segments if s.sentinel_start < end and start < s.sentinel_end
    )


#: Retained name for the projection type.
Projection = ParagraphProjection
