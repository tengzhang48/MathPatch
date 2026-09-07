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

PLAN.md F7 (RETRACTED) records a past version of ArtifactCert that advanced its offset
by a hyperlink's text width while `_para_text` omitted that text, skewing the two
spaces. That was fixed on 2026-08-24, before this project existed; at the pinned commit
both use canonical coordinates. The lesson it leaves is the reason `patch_boundary`
exists here: a consumer's offsets and this projection's offsets are different
coordinate systems, and they must be converted explicitly rather than assumed equal.
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

#: 1.1.0 (2026-09-07, M0.1): nested-run text is now included, an authored sentinel is
#: refused, and spans carry `patch_boundary` and `path`. 1.0.0 was the M0 projection.
#: Bump on ANY change to the projection. A consumer whose stored artifact identity
#: derives from canonical text must record this value and refuse a mismatch rather
#: than warn: a silent change to the projection is a silent change to that identity.
CANONICAL_TEXT_CONTRACT_VERSION = "1.1.0"


class SentinelCollision(ValueError):
    """A paragraph's authored text already contains the sentinel character.

    Measured absent from the reference corpus (0 occurrences), but absence from
    one corpus is not a property of Word documents. Once the sentinel carries
    meaning, an authored U+FFFC would make `sentinel_offsets()` disagree with
    `spans` and silently corrupt every intersection test, so it is refused
    rather than assumed away.
    """


@dataclass(frozen=True, slots=True)
class Projection:
    """Canonical text of one paragraph plus the math spans positioned in it."""

    text: str
    spans: tuple[ProtectedMathSpan, ...]
    anomalies: tuple[str, ...] = ()

    @property
    def patch_text(self) -> str:
        """The consumer's edit coordinate stream: `text` without sentinels.

        Equal to ArtifactCert's `docx_manifest._para_text` on every paragraph of the
        reference corpus (`tools/drift_gate.py`). Edit extents supplied by a consumer
        index THIS string, never `text`.
        """
        return self.text.replace(SENTINEL, "")

    def sentinel_offsets(self) -> tuple[int, ...]:
        return tuple(i for i, ch in enumerate(self.text) if ch == SENTINEL)

    def math_boundaries(self) -> tuple[int, ...]:
        """Zero-width math positions in `patch_text`, in document order."""
        return tuple(s.patch_boundary for s in self.spans)


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
    anomalies: list[str] = []
    offset = 0        # sentinel-stream offset
    patch_offset = 0  # consumer/_para_text offset; sentinels do NOT advance it
    ordinal = 0

    def emit_span(el: etree._Element, wrapper: str | None, path: tuple[int, ...]) -> None:
        nonlocal offset, ordinal
        spans.append(
            ProtectedMathSpan(
                element=el,
                start=offset,
                end=offset + 1,
                kind=local_name(el),
                ordinal=ordinal,
                wrapper=wrapper,
                patch_boundary=patch_offset,
                path=path,
            )
        )
        parts.append(SENTINEL)
        offset += 1
        ordinal += 1

    def emit_text(text: str) -> None:
        nonlocal offset, patch_offset
        if not text:
            return
        if SENTINEL in text:
            raise SentinelCollision(
                f"authored U+{ord(SENTINEL):04X} at canonical offset "
                f"{offset + text.index(SENTINEL)}; the sentinel cannot be "
                "distinguished from a math span"
            )
        parts.append(text)
        offset += len(text)
        patch_offset += len(text)

    def walk(
        el: etree._Element,
        wrapper: str | None,
        in_direct_run: bool,
        path: tuple[int, ...] = (),
    ) -> None:
        for index, child in enumerate(el):
            child_path = path + (index,)
            tag = child.tag
            if not isinstance(tag, str):
                # Comment or processing instruction. lxml gives these a callable
                # tag, so QName() raises on them. ArtifactCert's parser keeps
                # comments (`remove_comments=False`), so they reach us by design.
                # They carry no canonical text and no math: skip.
                continue
            if tag in MATH_TAGS:
                # Outermost-only: never descend into a match.
                emit_span(child, wrapper, child_path)
            elif tag == qn("r"):
                # `_para_text` reaches every w:t descendant of a DIRECT w:r child,
                # so a run nested inside a direct run still contributes text. Word
                # does not emit that shape (0 divergent runs in 21,433 measured), but
                # silently dropping it would break the strict-extension property, so
                # it is included and reported as an anomaly for consumers that would
                # rather fail closed.
                nested = in_direct_run
                if nested and "nested_run" not in anomalies:
                    anomalies.append("nested_run")
                direct = (el is p) or in_direct_run
                walk(
                    child,
                    wrapper if wrapper is not None else ("r" if direct else None),
                    direct,
                    child_path,
                )
            elif tag == qn("t"):
                if in_direct_run:
                    emit_text(child.text or "")
            else:
                # Contributes no canonical text of its own (matching _para_text), but
                # may contain math, or a nested w:t belonging to an enclosing run.
                walk(
                    child,
                    wrapper if wrapper is not None else local_name(child),
                    in_direct_run,
                    child_path,
                )

    walk(p, None, False)
    return Projection(
        text="".join(parts), spans=tuple(spans), anomalies=tuple(anomalies)
    )


def canonical_text(p: etree._Element) -> str:
    """Canonical editable text of `p`, with one sentinel per math span."""
    return project(p).text


def math_spans(p: etree._Element) -> tuple[ProtectedMathSpan, ...]:
    """Outermost math spans of `p`, positioned in `canonical_text(p)`."""
    return project(p).spans


def crosses_math_boundary(
    p: etree._Element, patch_start: int, patch_end: int
) -> tuple[ProtectedMathSpan, ...]:
    """Math boundaries strictly inside the edit extent, in PATCH coordinates.

    This is the integration entry point. It mirrors ArtifactCert's own rule at
    `0992741` exactly -- `safety.py`: `if span_start < offset < span_end` -- so an
    edit may begin or end precisely at a boundary, and only an edit that spans one
    is reported. Extents index `Projection.patch_text` (= `_para_text`), which is
    the space a consumer's `span_start`/`span_end` already live in.

    Use this, not `intersects_math`, when the caller's offsets come from a consumer.
    """
    proj = project(p)
    limit = len(proj.patch_text)
    if not (0 <= patch_start <= patch_end <= limit):
        raise ValueError(
            f"edit extent [{patch_start}, {patch_end}) is not a valid range within "
            f"patch text of length {limit}"
        )
    return tuple(s for s in proj.spans if patch_start < s.patch_boundary < patch_end)


def intersects_math(p: etree._Element, start: int, end: int) -> tuple[ProtectedMathSpan, ...]:
    """Math spans intersecting `[start, end)` in SENTINEL coordinates.

    Offsets index `Projection.text`, NOT `patch_text`. The two differ by the number
    of preceding sentinels, so a consumer's edit extents must go to
    `crosses_math_boundary` instead -- passing them here silently mis-answers
    whenever math precedes the extent (PLAN.md F10).

    A span that merely abuts the extent does not intersect: an edit may end exactly
    where math begins.
    """
    proj = project(p)
    if not (0 <= start <= end <= len(proj.text)):
        raise ValueError(
            f"edit extent [{start}, {end}) is not a valid range within canonical "
            f"text of length {len(proj.text)}; a protection API must reject an "
            "impossible range rather than report no intersection"
        )
    return tuple(s for s in proj.spans if s.start < end and start < s.end)
