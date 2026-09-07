"""Office Math span discovery.

A protected math span is one OUTERMOST math element inside a paragraph. Outermost
matters: every `m:oMathPara` wraps at least one `m:oMath`, so a naive descent that
recurses into a match double-counts. Measured on a real manuscript (Hygrochastic
Revision v5): naive descent finds 114 elements where there are 90 spans.

Discovery is by DESCENT, not by scanning the direct children of `w:p`: math nested
inside a revision wrapper (`w:ins`/`w:del`), a hyperlink, or a content control is still
a span that must be protected. Scanning direct children under-reports, which is the
dangerous direction -- an unseen span is an unprotected span.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

OMATH = f"{{{M_NS}}}oMath"
OMATHPARA = f"{{{M_NS}}}oMathPara"
MATH_TAGS = frozenset({OMATH, OMATHPARA})

#: One OBJECT REPLACEMENT CHARACTER stands for one math span in canonical text.
#: U+FFFC is the Unicode-designated placeholder for an embedded non-text object,
#: it is not a plausible authored character in a manuscript, and it is exactly one
#: code point wide, which keeps span arithmetic trivial.
SENTINEL = "￼"


def qn(local: str) -> str:
    """Qualify a WordprocessingML local name."""
    return f"{{{W_NS}}}{local}"


def local_name(el: etree._Element) -> str:
    return etree.QName(el).localname


@dataclass(frozen=True, slots=True)
class ProtectedMathSpan:
    """One outermost math element, positioned in its paragraph's canonical text.

    `start`/`end` are offsets into `canonical_text(p)` for the SAME paragraph `p`,
    and always satisfy `end == start + 1` because a span contributes exactly one
    sentinel character. They are relative to the paragraph and carry no document
    address: MathPatch never owns addressing (see PLAN.md section 2).
    """

    element: etree._Element
    start: int
    end: int
    kind: str
    ordinal: int
    wrapper: str | None = None

    @property
    def is_display(self) -> bool:
        """True for `m:oMathPara`, Word's display-equation container."""
        return self.kind == "oMathPara"

    @property
    def is_nested(self) -> bool:
        """True when the span is not a direct child of the paragraph.

        Nested spans sit inside a revision wrapper, hyperlink, or content control.
        They are protected identically, but a consumer may not be able to edit the
        surrounding text at all.
        """
        return self.wrapper is not None


def outermost_math(el: etree._Element) -> Iterator[etree._Element]:
    """Yield outermost math descendants of `el` in document order.

    Never recurses into a match, so `m:oMath` inside `m:oMathPara` is not yielded
    separately. `el` itself is not considered, only its descendants.
    """
    for child in el:
        if child.tag in MATH_TAGS:
            yield child
        else:
            yield from outermost_math(child)


def has_math(el: etree._Element) -> bool:
    """True if any math element appears at or below `el`."""
    return el.tag in MATH_TAGS or any(d.tag in MATH_TAGS for d in el.iter())
