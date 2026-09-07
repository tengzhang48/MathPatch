"""The canonical-text projection: paragraph -> (text with sentinels, math spans).

Text and offsets are produced by ONE function, `project`, so they cannot disagree.
`canonical_text` and `math_spans` are thin views over it. This mirrors the discipline
in ArtifactCert's `docx_patch/locator.py`, which is deliberately a re-export of core
so two enumerations cannot drift.

Coordinate space
----------------
The projection is a STRICT EXTENSION of ArtifactCert's `docx_manifest._para_text`:
the concatenation of the paragraph's DIRECT `w:r` children's `w:t` text, plus one
sentinel per math span. On a math-free paragraph the two are byte-identical; that
equality is the M0 completion gate (`tools/drift_gate.py`).

Consequences of following `_para_text` exactly, both deliberate:

  - Text inside a hyperlink, field, content control, or revision wrapper contributes
    NOTHING, because `_para_text` excludes it. This is the space in which a patch
    anchor is located (`engine.py`: `text = paragraph_text(p); span_start =
    text.index(anchor)`), so it is the space that decides which characters an edit
    actually overwrites. It is therefore the correct space for a protection oracle.

  - A math span inside such a wrapper still gets a sentinel, even though the wrapper
    contributes no text. An unpositioned span cannot be protected (PLAN.md F1/F5).

See PLAN.md F7: `safety.analyze_paragraph` advances its own offset by a hyperlink's
text width while `_para_text` omits that text, so the two spaces are skewed for such
paragraphs. That skew is a live mis-target in ArtifactCert and must be resolved in
favour of this projection, not against it -- otherwise the sentinel inherits the same
class of bug the moment math offsets start being consumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from .spans import (
    MATH_TAGS,
    SENTINEL,
    ProtectedMathSpan,
    local_name,
    qn,
)

#: Bump on ANY change to the projection. A consumer whose stored artifact identity
#: derives from canonical text must record this value and refuse a mismatch rather
#: than warn: a silent change to the projection is a silent change to that identity.
CANONICAL_TEXT_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class Projection:
    """Canonical text of one paragraph plus the math spans positioned in it."""

    text: str
    spans: tuple[ProtectedMathSpan, ...]

    def sentinel_offsets(self) -> tuple[int, ...]:
        return tuple(i for i, ch in enumerate(self.text) if ch == SENTINEL)


def project(p: etree._Element) -> Projection:
    """Project one `w:p` to canonical text plus positioned math spans.

    One traversal in document order emits both, so text and offsets cannot disagree.

    Discovery is TOTAL: every math element in the paragraph is either a span or a
    descendant of one (`tests/test_canonical.py::test_every_math_element_is_covered`).
    An unseen span is an unprotected span, so under-reporting is the dangerous
    direction -- including for the schema-unusual case of math inside a `w:r`, which
    does not occur in the reference corpus but is not thereby impossible.

    Text emission reproduces `_para_text` exactly: a `w:t` contributes only when its
    run is a DIRECT child of the paragraph, at any depth within that run (`_para_text`
    uses `.iter()`, so a deeply nested `w:t` counts -- see F6).
    """
    parts: list[str] = []
    spans: list[ProtectedMathSpan] = []
    offset = 0
    ordinal = 0

    def emit_span(el: etree._Element, wrapper: str | None) -> None:
        nonlocal offset, ordinal
        spans.append(
            ProtectedMathSpan(
                element=el,
                start=offset,
                end=offset + 1,
                kind=local_name(el),
                ordinal=ordinal,
                wrapper=wrapper,
            )
        )
        parts.append(SENTINEL)
        offset += 1
        ordinal += 1

    def emit_text(text: str) -> None:
        nonlocal offset
        if text:
            parts.append(text)
            offset += len(text)

    def walk(el: etree._Element, wrapper: str | None, in_direct_run: bool) -> None:
        for child in el:
            tag = child.tag
            if tag in MATH_TAGS:
                # Outermost-only: never descend into a match.
                emit_span(child, wrapper)
            elif tag == qn("r"):
                direct = el is p
                walk(child, wrapper if wrapper is not None else ("r" if direct else None), direct)
            elif tag == qn("t"):
                if in_direct_run:
                    emit_text(child.text or "")
            else:
                # Contributes no canonical text of its own (matching _para_text), but
                # may contain math, or a nested w:t belonging to an enclosing run.
                walk(child, wrapper if wrapper is not None else local_name(child), in_direct_run)

    walk(p, None, False)
    return Projection(text="".join(parts), spans=tuple(spans))


def canonical_text(p: etree._Element) -> str:
    """Canonical editable text of `p`, with one sentinel per math span."""
    return project(p).text


def math_spans(p: etree._Element) -> tuple[ProtectedMathSpan, ...]:
    """Outermost math spans of `p`, positioned in `canonical_text(p)`."""
    return project(p).spans


def intersects_math(p: etree._Element, start: int, end: int) -> tuple[ProtectedMathSpan, ...]:
    """Math spans strictly inside the half-open edit extent `[start, end)`.

    A span that merely abuts the extent (`span.start == end`, or `span.end == start`)
    does NOT intersect: an edit may end exactly where math begins. This is the test
    the blanket `PATCH_NOT_SAFE_MATH_IN_TARGET` refusal should be narrowed to.
    """
    return tuple(s for s in project(p).spans if s.start < end and start < s.end)
