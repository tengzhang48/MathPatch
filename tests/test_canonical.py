"""The canonical projection: strict extension of _para_text, one sentinel per span."""

from __future__ import annotations

from conftest import omath, omathpara, para, run

from mathpatch import (
    CANONICAL_TEXT_CONTRACT_VERSION,
    SENTINEL,
    canonical_text,
    intersects_math,
    math_spans,
    project,
)


def test_sentinel_is_object_replacement_character():
    assert ord(SENTINEL) == 0xFFFC
    assert len(SENTINEL) == 1


def test_contract_version_is_set():
    assert CANONICAL_TEXT_CONTRACT_VERSION


def test_math_free_paragraph_is_plain_concatenation():
    p = para(run("The deformation ") + run("increases rapidly."))
    assert canonical_text(p) == "The deformation increases rapidly."
    assert math_spans(p) == ()


def test_inline_math_gets_one_sentinel_at_the_right_offset():
    p = para(run("The deformation ") + omath() + run(" increases rapidly."))
    text = canonical_text(p)
    assert text == f"The deformation {SENTINEL} increases rapidly."
    (span,) = math_spans(p)
    assert text[span.start] == SENTINEL
    assert span.end == span.start + 1
    assert span.kind == "oMath"
    assert span.wrapper is None and not span.is_nested


def test_adjacent_math_spans_get_one_sentinel_each():
    p = para(run("a") + omath() + omath() + run("b"))
    assert canonical_text(p) == f"a{SENTINEL}{SENTINEL}b"
    spans = math_spans(p)
    assert [s.start for s in spans] == [1, 2]
    assert [s.ordinal for s in spans] == [0, 1]


def test_display_container_is_one_span_not_two():
    p = para(omathpara())
    (span,) = math_spans(p)
    assert span.kind == "oMathPara" and span.is_display


def test_math_only_paragraph():
    p = para(omath())
    assert canonical_text(p) == SENTINEL


def test_math_inside_revision_wrapper_is_positioned_and_marked():
    """The wrapper contributes no text (matching _para_text), but the span must
    still have a position: an unpositioned span cannot be protected."""
    p = para(run("before ") + f"<w:ins>{run('inserted')}{omath()}</w:ins>" + run(" after"))
    text = canonical_text(p)
    assert text == f"before {SENTINEL} after"      # 'inserted' excluded, sentinel present
    (span,) = math_spans(p)
    assert span.wrapper == "ins" and span.is_nested
    assert text[span.start] == SENTINEL


def test_hyperlink_text_is_excluded_matching_para_text():
    """_para_text counts DIRECT w:r children only. The projection must agree, because
    that is the space a patch anchor is located in. See PLAN.md F7."""
    p = para(run("AAA ") + f"<w:hyperlink>{run('LINK')}</w:hyperlink>" + run(" BBB"))
    assert canonical_text(p) == "AAA  BBB"


def test_sentinel_count_always_equals_span_count():
    p = para(
        run("a") + omath() + run("b") + f"<w:ins>{omath()}</w:ins>" + omathpara() + run("c")
    )
    proj = project(p)
    assert len(proj.spans) == proj.text.count(SENTINEL) == 3
    assert proj.sentinel_offsets() == tuple(s.start for s in proj.spans)


def test_text_and_offsets_cannot_disagree():
    p = para(run("xx") + omath() + run("yyy") + omath())
    proj = project(p)
    for span in proj.spans:
        assert proj.text[span.start : span.end] == SENTINEL


class TestIntersection:
    """The test the blanket math refusal should be narrowed to."""

    def setup_method(self):
        # canonical: "aaa" + SENTINEL + "bbb"  -> sentinel at offset 3
        self.p = para(run("aaa") + omath() + run("bbb"))

    def test_edit_before_math_does_not_intersect(self):
        assert intersects_math(self.p, 0, 3) == ()

    def test_edit_after_math_does_not_intersect(self):
        assert intersects_math(self.p, 4, 7) == ()

    def test_edit_ending_exactly_at_math_does_not_intersect(self):
        """An edit may end exactly where math begins."""
        assert intersects_math(self.p, 1, 3) == ()

    def test_edit_starting_exactly_after_math_does_not_intersect(self):
        assert intersects_math(self.p, 4, 5) == ()

    def test_edit_covering_math_intersects(self):
        assert len(intersects_math(self.p, 2, 5)) == 1

    def test_edit_exactly_on_math_intersects(self):
        assert len(intersects_math(self.p, 3, 4)) == 1

    def test_edit_spanning_the_whole_paragraph_intersects(self):
        """The 48.5% case: a sentence rewrite that spans the math. Needs holes."""
        assert len(intersects_math(self.p, 0, 7)) == 1
