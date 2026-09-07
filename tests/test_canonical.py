"""The canonical projection: strict extension of _para_text, one sentinel per span."""

from __future__ import annotations

import pytest
from conftest import omath, omathpara, para, run

from mathpatch import (
    CANONICAL_TEXT_CONTRACT_VERSION,
    SENTINEL,
    canonical_text,
    crosses_math_boundary,
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
    """Sentinel-coordinate intersection. NOTE: a consumer's offsets belong in
    crosses_math_boundary, not here -- see TestPatchCoordinates."""

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


class TestTotalDiscovery:
    """Discovery must be total: an unseen span is an unprotected span."""

    def test_math_inside_a_run_is_discovered(self):
        """Schema-unusual and absent from the reference corpus (audit B: 0 of 4,645
        paragraphs), but absent is not impossible, and missing it is the dangerous
        direction."""
        p = para(f"<w:r><w:t>a</w:t>{omath()}<w:t>b</w:t></w:r>")
        text = canonical_text(p)
        assert text == f"a{SENTINEL}b"
        (span,) = math_spans(p)
        assert span.wrapper == "r" and span.is_nested
        assert text[span.start] == SENTINEL

    def test_every_math_element_is_covered(self):
        """Partition invariant: each math element is a span or inside one -- never
        both missed and never double-counted."""
        from mathpatch import MATH_TAGS

        p = para(
            run("a") + omath() + f"<w:ins>{omathpara()}</w:ins>"
            + f"<w:r><w:t>b</w:t>{omath()}</w:r>" + run("c")
        )
        spans = math_spans(p)
        # strong references held for the lifetime of the comparison: id() on a
        # collected lxml proxy can be reused for a different node
        covered_els = [d for s in spans for d in s.element.iter()]
        all_els = list(p.iter())
        covered = {id(d) for d in covered_els}
        all_math = [el for el in all_els if el.tag in MATH_TAGS]
        assert all_math, "fixture must contain math"
        assert all(id(el) in covered for el in all_math)
        # oMathPara + its inner oMath = 4 elements, but only 3 spans
        assert len(all_math) == 4 and len(spans) == 3

    def test_deeply_nested_w_t_in_a_direct_run_is_included(self):
        """_para_text uses .iter(), so a w:t below an intermediate element still
        counts. safety._run_text uses .findall() and would drop it -- that is F6."""
        p = para("<w:r><w:t>x</w:t><w:smartTag><w:t>deep</w:t></w:smartTag></w:r>")
        assert canonical_text(p) == "xdeep"

    def test_text_inside_a_revision_wrapper_stays_excluded(self):
        """A w:ins is not a direct w:r child, so _para_text omits its text and so
        must the projection."""
        p = para(run("keep") + f"<w:ins>{run('dropped')}</w:ins>" + run("keep2"))
        assert canonical_text(p) == "keepkeep2"


def test_outermost_math_agrees_with_the_projection():
    """spans.outermost_math and project()'s traversal both implement "outermost".
    Two definitions of one fact is the F6 hazard, so it is guarded here rather than
    left to drift."""
    from mathpatch import outermost_math

    p = para(
        run("a") + omath() + f"<w:ins>{omathpara()}</w:ins>"
        + f"<w:r><w:t>b</w:t>{omath()}</w:r>" + run("c") + omathpara()
    )
    from_helper = list(outermost_math(p))
    from_projection = [s.element for s in math_spans(p)]
    assert len(from_helper) == len(from_projection) == 4
    assert all(a is b for a, b in zip(from_helper, from_projection))


class TestHardening:
    """M0.1: refuse or handle the shapes the corpus happened not to contain."""

    def test_xml_comment_child_is_skipped(self):
        """ArtifactCert's parser keeps comments (remove_comments=False), so they
        reach the projection by design. lxml gives them a callable tag, which
        QName() rejects."""
        p = para(run("a") + "<!-- reviewer note -->" + run("b"))
        assert canonical_text(p) == "ab"

    def test_processing_instruction_child_is_skipped(self):
        p = para(run("a") + "<?custom directive?>" + run("b"))
        assert canonical_text(p) == "ab"

    def test_comment_does_not_hide_math(self):
        p = para(run("a") + f"<w:ins><!-- c -->{omath()}</w:ins>" + run("b"))
        assert len(math_spans(p)) == 1

    def test_nested_run_text_is_included_and_flagged(self):
        """_para_text reaches every w:t descendant of a direct w:r, so dropping a
        nested run's text would break strict extension. Word does not emit this
        shape (0 of 21,433 measured runs), so it is also reported as an anomaly."""
        p = para("<w:r><w:t>outer</w:t><w:r><w:t>NESTED</w:t></w:r></w:r>")
        proj = project(p)
        assert proj.text == "outerNESTED"
        assert "nested_run" in proj.anomalies

    def test_ordinary_paragraph_reports_no_anomalies(self):
        p = para(run("plain ") + omath() + run(" text"))
        assert project(p).anomalies == ()

    def test_authored_sentinel_is_refused(self):
        """Absence from one corpus is not a property of Word documents. An
        authored U+FFFC would make sentinel_offsets() disagree with spans."""
        from mathpatch import SentinelCollision

        p = para(run(f"real{SENTINEL}text"))
        with pytest.raises(SentinelCollision) as exc:
            canonical_text(p)
        assert "FFFC" in str(exc.value)

    def test_authored_sentinel_refused_even_with_real_math(self):
        from mathpatch import SentinelCollision

        p = para(run(f"a{SENTINEL}b") + omath())
        with pytest.raises(SentinelCollision):
            project(p)

    @pytest.mark.parametrize("start,end", [(-5, -1), (0, 99), (5, 2), (-1, 3)])
    def test_intersects_math_rejects_impossible_ranges(self, start, end):
        p = para(run("aaa") + omath() + run("bbb"))
        with pytest.raises(ValueError):
            intersects_math(p, start, end)

    def test_intersects_math_accepts_the_full_valid_range(self):
        p = para(run("aaa") + omath() + run("bbb"))
        text = canonical_text(p)
        assert len(intersects_math(p, 0, len(text))) == 1
        assert intersects_math(p, 0, 0) == ()


class TestPatchCoordinates:
    """Two coordinate systems, never interchangeable. PLAN.md F10."""

    def test_patch_text_equals_text_without_sentinels(self):
        p = para(omath() + run("AB") + omath() + run("CD"))
        proj = project(p)
        assert proj.text == f"{SENTINEL}AB{SENTINEL}CD"
        assert proj.patch_text == "ABCD"

    def test_sentinel_starts_differ_from_patch_boundaries(self):
        """The landmine: handing a consumer's offsets to intersects_math would
        mis-answer whenever math precedes the extent."""
        p = para(omath() + run("AB") + omath() + run("CD"))
        proj = project(p)
        assert [s.start for s in proj.spans] == [0, 3]
        assert proj.math_boundaries() == (0, 2)
        assert [s.start for s in proj.spans] != list(proj.math_boundaries())

    def test_patch_boundary_is_zero_width(self):
        p = para(run("aaa") + omath() + run("bbb"))
        (span,) = math_spans(p)
        assert span.patch_boundary == 3
        assert project(p).patch_text == "aaabbb"

    def test_structural_path_is_recorded(self):
        p = para(run("a") + omath() + f"<w:ins>{omath()}</w:ins>")
        direct, nested = math_spans(p)
        assert direct.path == (1,)
        assert nested.path == (2, 0)

    class TestCrossingRule:
        """crosses_math_boundary mirrors ArtifactCert 0992741's own rule:
        `if span_start < offset < span_end` -- strict on both sides."""

        def setup_method(self):
            # patch_text "aaabbb", one math boundary at 3
            self.p = para(run("aaa") + omath() + run("bbb"))

        def test_edit_ending_at_the_boundary_is_allowed(self):
            assert crosses_math_boundary(self.p, 0, 3) == ()

        def test_edit_starting_at_the_boundary_is_allowed(self):
            assert crosses_math_boundary(self.p, 3, 6) == ()

        def test_edit_spanning_the_boundary_is_reported(self):
            assert len(crosses_math_boundary(self.p, 2, 4)) == 1

        def test_whole_paragraph_replacement_is_reported(self):
            assert len(crosses_math_boundary(self.p, 0, 6)) == 1

        def test_extent_validated_against_patch_text_not_sentinel_text(self):
            # patch_text is 6 chars; sentinel text is 7. 7 must be rejected.
            assert len(project(self.p).text) == 7
            crosses_math_boundary(self.p, 0, 6)
            with pytest.raises(ValueError):
                crosses_math_boundary(self.p, 0, 7)
