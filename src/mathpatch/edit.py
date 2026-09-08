"""M2a: swap the text of one `m:t` inside an equation, source-preserving.

Scoped by measurement (PLAN.md F16). In the reference corpus every named Phase-2 edit --
change one identifier, one subscript, one literal, one operator -- is a change to the text
of a single `m:t`. So the first real mutation needs no AST: address one `m:t`, verify the
exact source state the caller said was authorized, and change that text and nothing else.

Why source-preserving rather than regenerating, in numbers: about **72% of all elements
inside a real equation are Word run formatting** (`w:rPr` and its thirteen children --
3,239 `w:rPr`, 3,178 `w:rFonts`, and nine more at ~920 apiece). A writer that serializes a
fresh subtree must reproduce every one of them exactly. Mutating the smallest original node
keeps them for free, along with `m:ctrlPr`, `m:rPr`/`m:sty`, and the
`xml:space="preserve"` that 63% of `m:t` elements carry.

The division of responsibility is unchanged: ArtifactCert decides what may change.
MathPatch owns the deterministic statement

    "I mutated exactly the source state you said was authorized, and nothing else."

which is why an edit carries a preimage -- the expected text AND the span's C14N digest --
and refuses when either has moved. That is the analogue of ArtifactCert's own exact-proposal
binding.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from lxml import etree

from .canonical import project
from .digest import span_digest
from .spans import M_NS, MathSegment

#: `m:t`, the only element in OMML that carries mathematical text.
M_TEXT = f"{{{M_NS}}}t"

#: Whitespace in `m:t` is significant and 63% of them declare it (PLAN.md F16).
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


class PreimageMismatch(ValueError):
    """The source no longer matches what the caller said was authorized.

    Either the target's text differs from `expected_text`, or the span's C14N digest
    differs from `expected_span_digest` -- meaning something in the equation changed
    between authorization and application. Nothing is mutated.
    """


class TargetNotFound(ValueError):
    """No span or no `m:t` at the requested ordinal."""


@dataclass(frozen=True, slots=True)
class MathTextTarget:
    """One addressable `m:t` inside a math span.

    `text_ordinal` counts non-empty `m:t` elements within the span in document order.
    `source_path` is the raw index path from the span element, and locates it: following
    those indices from `MathSegment.source_element` reaches exactly this node.
    """

    element: etree._Element
    text_ordinal: int
    source_path: tuple[int, ...]
    text: str


@dataclass(frozen=True, slots=True)
class MathTextEdit:
    """An authorized change to the text of one `m:t`, with its preimage condition."""

    span_ordinal: int
    text_ordinal: int
    expected_text: str
    expected_span_digest: str
    new_text: str


@dataclass(frozen=True, slots=True)
class MathTextReceipt:
    """What was changed, and the digests proving nothing else was."""

    applied: bool
    span_ordinal: int
    text_ordinal: int
    source_path: tuple[int, ...]
    old_text: str
    new_text: str
    span_digest_before: str
    span_digest_after: str
    skeleton_digest_before: str
    skeleton_digest_after: str


def text_targets(span: MathSegment) -> tuple[MathTextTarget, ...]:
    """Every non-empty `m:t` in the span, in document order.

    Empty `m:t` elements are skipped: they carry no text to swap, and Word leaves them
    behind when a tracked equation edit is accepted (`docx_view.py` strips them for the
    same reason -- PLAN.md F9).
    """
    out: list[MathTextTarget] = []

    def walk(el: etree._Element, path: tuple[int, ...]) -> None:
        for index, child in enumerate(el):
            if not isinstance(child.tag, str):
                continue
            child_path = path + (index,)
            if child.tag == M_TEXT:
                text = child.text or ""
                if text:
                    out.append(
                        MathTextTarget(
                            element=child,
                            text_ordinal=len(out),
                            source_path=child_path,
                            text=text,
                        )
                    )
                continue
            walk(child, child_path)

    walk(span.source_element, ())
    return tuple(out)


def skeleton_digest(span: MathSegment, text_ordinal: int) -> str:
    """C14N digest of the span with ONE target's text CONTENT neutralized.

    Equality before and after an edit proves that everything except that target's text is
    byte-identical under canonicalization -- a containment proof for the inside of an
    equation, complementing the whole-span digest, which is expected to change.

    "Neutralized" means the text is blanked AND its `xml:space` declaration removed. Both
    belong to the target's text content: a swap may legitimately need to declare
    whitespace significant, since 63% of real `m:t` elements carry `xml:space="preserve"`
    and dropping or omitting it changes how Word renders the equation (PLAN.md F16).
    Leaving `xml:space` inside the skeleton made this function report a violation for a
    correct edit -- caught by the fail-closed check in `apply_math_text_edit`, which is
    what that check is for.

    Everything else -- every `w:rPr` block, `m:ctrlPr`, `m:rPr`/`m:sty`, structure,
    sibling text -- remains inside the digest and is therefore protected.

    The neutralizing happens on a deepcopy, located by the target's `source_path`, so the
    original is untouched and the ordinal cannot drift.
    """
    targets = text_targets(span)
    if not 0 <= text_ordinal < len(targets):
        raise TargetNotFound(
            f"m:t ordinal {text_ordinal} not in span with {len(targets)} text node(s)"
        )
    path = targets[text_ordinal].source_path
    clone = copy.deepcopy(span.source_element)
    node = clone
    for index in path:
        node = node[index]
    node.text = None
    if node.get(XML_SPACE) is not None:
        del node.attrib[XML_SPACE]
    from .digest import digest

    return digest(clone)


def apply_math_text_edit(
    p: etree._Element, edit: MathTextEdit
) -> MathTextReceipt:
    """Apply one authorized `m:t` text swap to a paragraph, in place.

    Refuses -- mutating nothing -- when the span or target does not exist, when the
    preimage does not match, or when the edit is a no-op or would empty the node.
    Emptying an `m:t` or removing it is a STRUCTURAL edit and belongs to M2b, not here:
    it would renumber the span's text ordinals.
    """
    spans = project(p).math_segments
    if not 0 <= edit.span_ordinal < len(spans):
        raise TargetNotFound(
            f"span ordinal {edit.span_ordinal} not in paragraph with {len(spans)} span(s)"
        )
    span = spans[edit.span_ordinal]

    actual_digest = span_digest(span)
    if actual_digest != edit.expected_span_digest:
        raise PreimageMismatch(
            f"span {edit.span_ordinal} C14N digest is {actual_digest[:12]}..., authorized "
            f"against {edit.expected_span_digest[:12]}...; the equation changed since "
            "authorization"
        )

    targets = text_targets(span)
    if not 0 <= edit.text_ordinal < len(targets):
        raise TargetNotFound(
            f"m:t ordinal {edit.text_ordinal} not in span {edit.span_ordinal} with "
            f"{len(targets)} text node(s)"
        )
    target = targets[edit.text_ordinal]

    if target.text != edit.expected_text:
        raise PreimageMismatch(
            f"m:t {edit.text_ordinal} text is {target.text!r}, authorized against "
            f"{edit.expected_text!r}"
        )
    if not edit.new_text:
        raise ValueError(
            "new_text is empty; emptying or removing an m:t is a structural edit "
            "(it renumbers the span's text ordinals) and is out of scope here"
        )
    if edit.new_text == target.text:
        raise ValueError(f"edit is a no-op: text is already {edit.new_text!r}")

    skeleton_before = skeleton_digest(span, edit.text_ordinal)

    target.element.text = edit.new_text
    # Keep xml:space if it was declared, add it if the new text needs it, never remove it.
    if edit.new_text != edit.new_text.strip() or target.element.get(XML_SPACE):
        target.element.set(XML_SPACE, "preserve")

    after = project(p).math_segments[edit.span_ordinal]
    skeleton_after = skeleton_digest(after, edit.text_ordinal)
    if skeleton_after != skeleton_before:
        raise AssertionError(
            "the edit changed something other than the target's text; refusing to "
            "report success"
        )

    return MathTextReceipt(
        applied=True,
        span_ordinal=edit.span_ordinal,
        text_ordinal=edit.text_ordinal,
        source_path=target.source_path,
        old_text=edit.expected_text,
        new_text=edit.new_text,
        span_digest_before=actual_digest,
        span_digest_after=span_digest(after),
        skeleton_digest_before=skeleton_before,
        skeleton_digest_after=skeleton_after,
    )
