"""Adversarial tests for the ParagraphProjection invariants (PLAN.md section 7a).

Written before the implementation, and each one proved red first. The numbering
matches the plan's invariant list so a failure names the invariant it broke.
"""

from __future__ import annotations

import pytest
from conftest import omath, omathpara, para, run

from mathpatch import (
    SENTINEL,
    MathSegment,
    OpaqueSegment,
    ParagraphProjection,
    TextSegment,
    project,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def texts(proj):
    return [s for s in proj.segments if isinstance(s, TextSegment)]


def maths(proj):
    return [s for s in proj.segments if isinstance(s, MathSegment)]


def opaques(proj):
    return [s for s in proj.segments if isinstance(s, OpaqueSegment)]


# A paragraph exercising every segment kind at once, reused by the partition tests.
BUSY = (
    run("alpha ")
    + omath()
    + run("beta")
    + '<w:r><w:sym w:font="Symbol" w:char="F073"/></w:r>'
    + run(" gamma")
    + f'<w:hyperlink w:anchor="a">{run("link")}</w:hyperlink>'
    + omathpara()
    + f"<w:ins>{run('ins')}{omath()}</w:ins>"
    + run("omega")
)


class TestShape:
    def test_projection_is_returned(self):
        assert isinstance(project(para(run("a"))), ParagraphProjection)

    def test_patch_text_is_primary_and_sentinel_is_derived(self):
        p = para(run("A") + omath() + run("B"))
        proj = project(p)
        assert proj.patch_text == "AB"
        assert proj.sentinel_text == f"A{SENTINEL}B"

    def test_segments_cover_every_kind(self):
        proj = project(para(BUSY))
        assert texts(proj) and maths(proj) and opaques(proj)


class TestInvariant1And2TextPartition:
    """1. Text partition. 2. Contiguity."""

    def test_text_segments_concatenate_to_patch_text(self):
        proj = project(para(BUSY))
        assert "".join(s.text for s in texts(proj)) == proj.patch_text

    def test_text_extents_are_ordered_and_non_overlapping(self):
        proj = project(para(BUSY))
        cursor = 0
        for seg in texts(proj):
            assert seg.patch_start == cursor, "gap or overlap in the text partition"
            assert seg.patch_end - seg.patch_start == len(seg.text)
            cursor = seg.patch_end
        assert cursor == len(proj.patch_text)

    def test_every_character_belongs_to_exactly_one_text_segment(self):
        proj = project(para(BUSY))
        owners = [0] * len(proj.patch_text)
        for seg in texts(proj):
            for i in range(seg.patch_start, seg.patch_end):
                owners[i] += 1
        assert owners and set(owners) == {1}

    def test_empty_runs_contribute_no_segment(self):
        proj = project(para(run("a") + "<w:r><w:t></w:t></w:r>" + run("b")))
        assert proj.patch_text == "ab"
        assert all(s.text for s in texts(proj))


class TestInvariant3ZeroWidth:
    def test_math_and_opaque_segments_consume_no_characters(self):
        proj = project(para(BUSY))
        for seg in maths(proj) + opaques(proj):
            assert isinstance(seg.patch_boundary, int)
            assert not hasattr(seg, "patch_end")

    def test_a_math_only_paragraph_has_empty_patch_text(self):
        proj = project(para(omath()))
        assert proj.patch_text == ""
        assert len(maths(proj)) == 1
        assert maths(proj)[0].patch_boundary == 0


class TestInvariant5And6MathTotality:
    """5. Total, non-overlapping math. 6. Ordinals."""

    def test_omathpara_is_one_segment_not_two(self):
        proj = project(para(omathpara()))
        assert len(maths(proj)) == 1
        assert maths(proj)[0].kind == "oMathPara"

    def test_every_math_element_is_a_segment_or_inside_one(self):
        p = para(BUSY)
        proj = project(p)
        covered_els = [d for s in maths(proj) for d in s.source_element.iter()]
        all_els = list(p.iter())
        covered = {id(d) for d in covered_els}
        all_math = [el for el in all_els if el.tag in (M + "oMath", M + "oMathPara")]
        assert all_math
        assert all(id(el) in covered for el in all_math)

    def test_ordinals_are_dense_and_in_document_order(self):
        proj = project(para(BUSY))
        ms = maths(proj)
        assert [s.ordinal for s in ms] == list(range(len(ms)))
        assert [s.patch_boundary for s in ms] == sorted(s.patch_boundary for s in ms)

    def test_math_segments_view_matches_the_segment_list(self):
        proj = project(para(BUSY))
        assert list(proj.math_segments) == maths(proj)


class TestInvariant7CrossingRule:
    def test_crossing_is_strict_on_both_sides(self):
        from mathpatch import crosses_math_boundary

        p = para(run("aaa") + omath() + run("bbb"))
        assert crosses_math_boundary(p, 0, 3) == ()
        assert crosses_math_boundary(p, 3, 6) == ()
        assert len(crosses_math_boundary(p, 2, 4)) == 1


class TestInvariant8NoInterpretation:
    """MathPatch reports structure; it never says what structure MEANS."""

    def test_opaque_segment_exposes_the_qualified_tag(self):
        proj = project(para(BUSY))
        names = {s.local_name for s in opaques(proj)}
        assert {"sym", "hyperlink", "ins"} <= names
        for seg in opaques(proj):
            assert seg.tag.startswith("{") and seg.local_name in seg.tag

    def test_opaque_segment_carries_no_decoded_value_or_class(self):
        proj = project(para(BUSY))
        forbidden = {
            "value", "decoded", "unicode", "char", "glyph", "meaning",
            "semantic", "category", "classification", "is_citation", "is_safe",
        }
        for seg in opaques(proj):
            assert not (forbidden & set(vars(seg) if hasattr(seg, "__dict__") else seg.__slots__))

    def test_symbol_is_not_decoded(self):
        """ArtifactCert owns the Adobe Symbol mapping and its fail-closed policy."""
        proj = project(para('<w:r><w:sym w:font="Symbol" w:char="F073"/></w:r>'))
        (seg,) = opaques(proj)
        assert seg.local_name == "sym"
        assert "σ" not in repr(seg)


class TestInvariant9DerivedViewAgrees:
    def test_sentinel_text_minus_sentinels_equals_patch_text(self):
        proj = project(para(BUSY))
        assert proj.sentinel_text.replace(SENTINEL, "") == proj.patch_text

    def test_sentinel_position_minus_ordinal_equals_patch_boundary(self):
        proj = project(para(BUSY))
        for seg in maths(proj):
            assert seg.sentinel_start - seg.ordinal == seg.patch_boundary

    def test_sentinel_count_equals_math_segment_count(self):
        proj = project(para(BUSY))
        assert proj.sentinel_text.count(SENTINEL) == len(maths(proj))


class TestInvariant10RefusalNotRepair:
    def test_authored_sentinel_raises(self):
        from mathpatch import SentinelCollision

        with pytest.raises(SentinelCollision):
            project(para(run(f"a{SENTINEL}b")))

    def test_nested_run_is_reported_not_dropped(self):
        proj = project(para("<w:r><w:t>outer</w:t><w:r><w:t>NESTED</w:t></w:r></w:r>"))
        assert proj.patch_text == "outerNESTED"
        assert "nested_run" in proj.anomalies

    def test_ordinary_paragraph_has_no_anomalies(self):
        assert project(para(run("x") + omath())).anomalies == ()


def position(seg):
    return getattr(seg, "patch_start", None) if isinstance(seg, TextSegment) else seg.patch_boundary


class TestInvariant11PathIdentity:
    """The uniqueness key is (source_path, position), not source_path alone.

    A run whose text is interrupted by interior structure yields one TextSegment per
    contiguous stretch, and all of them carry that run's path -- which is correct, since
    grouping by `source_element` is how a consumer recovers the run.
    """

    def test_every_segment_has_a_path(self):
        proj = project(para(BUSY))
        assert all(isinstance(s.source_path, tuple) and s.source_path for s in proj.segments)

    def test_path_and_position_are_unique(self):
        proj = project(para(BUSY))
        keys = [(s.source_path, position(s)) for s in proj.segments]
        assert len(set(keys)) == len(keys)

    def test_a_split_run_shares_a_path_but_not_a_position(self):
        """The case that sharpened this invariant: one run, interior w:sym, two text
        stretches. Paths collide by design; positions do not."""
        proj = project(
            para('<w:r><w:t>left</w:t><w:sym w:font="Symbol" w:char="F073"/><w:t>right</w:t></w:r>')
        )
        assert proj.patch_text == "leftright"
        segs = texts(proj)
        assert len(segs) == 2
        assert segs[0].source_path == segs[1].source_path
        assert segs[0].source_element is segs[1].source_element
        keys = [(s.source_path, position(s)) for s in proj.segments]
        assert len(set(keys)) == len(keys)

    def test_a_split_run_still_partitions_the_text(self):
        proj = project(
            para('<w:r><w:t>left</w:t><w:sym w:font="Symbol" w:char="F073"/><w:t>right</w:t></w:r>')
        )
        assert "".join(s.text for s in texts(proj)) == proj.patch_text
        cursor = 0
        for seg in texts(proj):
            assert seg.patch_start == cursor
            cursor = seg.patch_end

    def test_path_locates_the_element(self):
        p = para(run("a") + omath() + f"<w:ins>{omath()}</w:ins>")
        for seg in project(p).segments:
            node = p
            for index in seg.source_path:
                node = node[index]
            assert node is seg.source_element


class TestInvariant15PiecePartition:
    def test_pieces_concatenate_to_the_segment_text(self):
        proj = project(para('<w:r><w:t>aa</w:t><w:t>bbb</w:t></w:r>' + run("c")))
        for seg in texts(proj):
            assert "".join(seg.text[p.local_start : p.local_end] for p in seg.pieces) == seg.text

    def test_pieces_are_ordered_and_non_overlapping(self):
        proj = project(para('<w:r><w:t>aa</w:t><w:t>bbb</w:t></w:r>'))
        (seg,) = texts(proj)
        cursor = 0
        for piece in seg.pieces:
            assert piece.local_start == cursor
            assert piece.local_end > piece.local_start
            cursor = piece.local_end
        assert cursor == len(seg.text)

    def test_piece_answers_which_element_owns_a_character(self):
        """The reason pieces exist: a writer must not re-walk the run."""
        proj = project(para('<w:r><w:t>aa</w:t><w:t>bbb</w:t></w:r>'))
        (seg,) = texts(proj)
        owner = next(p for p in seg.pieces if p.local_start <= 3 < p.local_end)
        assert owner.element.text == "bbb"

    def test_absolute_offset_is_patch_start_plus_local(self):
        proj = project(para(run("xx") + '<w:r><w:t>yy</w:t><w:t>zz</w:t></w:r>'))
        seg = texts(proj)[1]
        assert seg.patch_start == 2
        for piece in seg.pieces:
            absolute = seg.patch_start + piece.local_start
            assert proj.patch_text[absolute] == piece.element.text[0]


class TestInvariant4DriftIsTheGate:
    def test_patch_text_rule_matches_para_text_locally(self):
        """The real check is tools/drift_gate.py over the corpus; this asserts the
        rule on the shapes that make it non-obvious."""
        cases = [
            (run("a") + f'<w:hyperlink w:anchor="x">{run("LINK")}</w:hyperlink>' + run("b"), "ab"),
            (run("keep") + f"<w:ins>{run('dropped')}</w:ins>" + run("keep2"), "keepkeep2"),
            ("<w:r><w:t>x</w:t><w:smartTag><w:t>deep</w:t></w:smartTag></w:r>", "xdeep"),
            (run("a") + "<!-- c -->" + run("b"), "ab"),
        ]
        for inner, expected in cases:
            assert project(para(inner)).patch_text == expected


class TestInvariant5NonOverlap:
    """The half of invariant 5 that coverage cannot check.

    Coverage ("every math element is a span or inside one") detects
    UNDER-reporting. Double-counting an m:oMathPara together with its inner
    m:oMath satisfies coverage perfectly while inflating the span count -- the
    exact bug outermost-only discovery exists to prevent (PLAN.md F11), and it
    passed the drift gate until this was added.
    """

    def test_no_span_is_nested_inside_another(self):
        proj = project(para(BUSY))
        els = [s.source_element for s in proj.math_segments]  # keep proxies alive
        ids = {id(e) for e in els}
        for outer in els:
            assert not any(id(d) in ids for d in outer.iterdescendants())

    def test_display_container_yields_one_span_not_two(self):
        proj = project(para(omathpara()))
        assert len(proj.math_segments) == 1

    def test_span_count_equals_outermost_element_count(self):
        """An independent count: outermost math elements, computed without the
        projection. Catches over- and under-reporting alike."""
        from mathpatch import outermost_math

        p = para(BUSY)
        assert len(project(p).math_segments) == len(list(outermost_math(p)))

    def test_paragraph_level_stray_text_contributes_nothing(self):
        """A w:t that is not inside a direct w:r is excluded, matching _para_text."""
        assert project(para("<w:t>stray</w:t>")).patch_text == ""

    # NOTE: flush() also raises if text is ever buffered with no enclosing run context.
    # That state is unreachable through any input fixture -- `in_direct_run` is only true
    # inside the branch that sets the run -- so it is verified by MUTATION, not by a unit
    # test: forcing `in_direct_run=True` for a run inside a wrapper makes the drift gate
    # report "traversal bug: 8 characters buffered with no run context". An earlier
    # version of this file asserted `... or True` here, which could never fail; in a
    # project whose tests are meant to be evidence, a green test that proves nothing is
    # worse than an honest note.
