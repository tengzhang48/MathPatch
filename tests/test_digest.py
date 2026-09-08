"""Protected-span digests survive reserialization and catch real change."""

from __future__ import annotations

import pytest

from conftest import omath, omathpara, para, run
from mathpatch import project
from lxml import etree

from mathpatch import C14N_KWARGS, math_spans, span_digest, span_digests


def _roundtrip(p):
    """What the engine does to a part: serialize the tree, parse it back."""
    return etree.fromstring(etree.tostring(p))


def test_digest_survives_a_reserialization_round_trip():
    p = para(run("a") + omath() + run("b"))
    before = span_digests(math_spans(p))
    after = span_digests(math_spans(_roundtrip(p)))
    assert before == after


def test_digest_survives_an_edit_to_surrounding_text():
    """The M1 operation: text next to math changes, the math must not."""
    p = para(run("before ") + omath() + run(" after"))
    before = span_digests(math_spans(p))
    for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
        if t.text == "before ":
            t.text = "BEFORE EDITED "
    after = span_digests(math_spans(_roundtrip(p)))
    assert before == after


def test_digest_changes_when_the_math_changes():
    """A protection oracle that cannot fail is not an oracle."""
    p = para(omath("<m:r><m:t>x</m:t></m:r>"))
    q = para(omath("<m:r><m:t>y</m:t></m:r>"))
    assert span_digest(math_spans(p)[0]) != span_digest(math_spans(q)[0])


def test_digest_accepts_element_or_span():
    p = para(omath())
    span = math_spans(p)[0]
    assert span_digest(span) == span_digest(span.element)


def test_comments_are_covered_by_the_digest():
    """with_comments=True diverges from revision_ingest deliberately: nothing inside
    a protected region may change undetected."""
    assert C14N_KWARGS["with_comments"] is True
    plain = para(omath("<m:r><m:t>x</m:t></m:r>"))
    commented = para(omath("<m:r><m:t>x</m:t></m:r><!-- smuggled -->"))
    assert span_digest(math_spans(plain)[0]) != span_digest(math_spans(commented)[0])


class TestPlacementOracle:
    """A C14N digest proves contents, not location. PLAN.md F10."""

    @staticmethod
    def _moved_pair():
        # A [eq] B   vs   A B [eq]
        return (
            para(run("A") + omath() + run("B")),
            para(run("A") + run("B") + omath()),
        )

    def test_moved_equation_defeats_digest_only(self):
        """The gap that makes digest-only verification insufficient: every content
        check agrees while the equation has moved."""
        before, after = self._moved_pair()
        b, a = math_spans(before), math_spans(after)
        assert before[0] is not after[0]
        # patch text is identical because math is zero width
        assert project(before).patch_text == project(after).patch_text == "AB"
        assert len(b) == len(a) == 1
        assert [s.ordinal for s in b] == [s.ordinal for s in a]
        assert span_digests(b) == span_digests(a)  # content oracle cannot see it

    def test_fingerprint_catches_the_moved_equation(self):
        from mathpatch import paragraph_fingerprint

        before, after = self._moved_pair()
        fb = paragraph_fingerprint(math_spans(before))
        fa = paragraph_fingerprint(math_spans(after))
        assert fb != fa, "fingerprint must detect what the digest cannot"
        # and it is placement, not content, that differs
        assert fb[0][-1] == fa[0][-1]        # same C14N digest
        assert (fb[0][2], fb[0][3]) != (fa[0][2], fa[0][3])  # boundary/path differ

    def test_fingerprint_stable_under_an_unrelated_text_edit(self):
        """The oracle must not cry wolf: editing text AFTER the math changes
        neither the math's contents nor its position."""
        from mathpatch import paragraph_fingerprint

        p = para(run("keep ") + omath() + run(" tail"))
        before = paragraph_fingerprint(math_spans(p))
        for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
            if t.text == " tail":
                t.text = " TAIL EDITED"
        assert paragraph_fingerprint(math_spans(p)) == before

    def test_fingerprint_detects_a_content_change_too(self):
        from mathpatch import paragraph_fingerprint

        a = para(run("x") + omath("<m:r><m:t>a</m:t></m:r>"))
        b = para(run("x") + omath("<m:r><m:t>b</m:t></m:r>"))
        assert paragraph_fingerprint(math_spans(a)) != paragraph_fingerprint(math_spans(b))


class TestIdentityVsPlacement:
    """The oracle must not refuse a correct patch. PLAN.md F12."""

    @staticmethod
    def _prose_before_equation():
        # the exact case the fingerprint got wrong: text BEFORE the math changes length
        return (
            para(run("The result ") + omath() + run(" is...")),
            para(run("The numerical result ") + omath() + run(" is...")),
        )

    def test_prose_edit_before_an_equation_moves_its_boundary(self):
        before, after = self._prose_before_equation()
        assert math_spans(before)[0].patch_boundary == 11
        assert math_spans(after)[0].patch_boundary == 21

    def test_full_fingerprint_would_falsely_report_a_move(self):
        """Why patch_boundary is not in the equality oracle: this comparison is the
        false positive, documented so nobody reinstates it."""
        from mathpatch import paragraph_fingerprint

        before, after = self._prose_before_equation()
        assert paragraph_fingerprint(math_spans(before)) != paragraph_fingerprint(
            math_spans(after)
        )

    def test_identity_is_invariant_under_a_prose_edit_before_the_equation(self):
        from mathpatch import paragraph_identity

        before, after = self._prose_before_equation()
        assert paragraph_identity(math_spans(before)) == paragraph_identity(
            math_spans(after)
        )

    def test_identity_still_catches_the_moved_equation(self):
        from mathpatch import paragraph_identity

        b = para(run("A") + omath() + run("B"))
        a = para(run("A") + run("B") + omath())
        assert paragraph_identity(math_spans(b)) != paragraph_identity(math_spans(a))

    def test_expected_boundary_predicts_the_shift(self):
        from mathpatch import actual_boundaries, expected_boundaries

        before, after = self._prose_before_equation()
        # authorized changed middle: "result" at [4,10) becomes "numerical result" (16)
        assert expected_boundaries(project(before), [(4, 10, 16)]) == (21,)
        assert actual_boundaries(project(after)) == (21,)

    def test_edit_after_the_equation_leaves_the_boundary_fixed(self):
        from mathpatch import expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        assert expected_boundaries(project(p), [(3, 6, 12)]) == (3,)

    def test_a_crossing_edit_has_no_defined_transform(self):
        from mathpatch import BoundaryCrossing, expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        with pytest.raises(BoundaryCrossing):
            expected_boundaries(project(p), [(2, 5, 3)])

    def test_multiple_edits_accumulate_only_before_the_boundary(self):
        from mathpatch import expected_boundaries

        # patch_text "aaabbbccc" with math after "aaabbb" -> boundary 6
        p = para(run("aaa") + run("bbb") + omath() + run("ccc"))
        assert math_spans(p)[0].patch_boundary == 6
        # +2 before, -1 before, +5 after -> boundary 6 + 1
        assert expected_boundaries(project(p), [(0, 3, 5), (3, 6, 2), (6, 9, 14)]) == (7,)


class TestZeroWidthInsertionAffinity:
    """One edit triple, two correct answers. PLAN.md F13."""

    @staticmethod
    def _before():
        return para(run("A") + omath() + run("B"))   # patch_text "AB", boundary 1

    def test_both_outcomes_are_reachable_from_the_same_edit_triple(self):
        """The ambiguity itself: identical patch text, different boundaries."""
        left = para(run("AX") + omath() + run("B"))
        right = para(run("A") + omath() + run("XB"))
        assert project(left).patch_text == project(right).patch_text == "AXB"
        assert math_spans(left)[0].patch_boundary == 2
        assert math_spans(right)[0].patch_boundary == 1

    def test_undeclared_affinity_is_refused_not_guessed(self):
        from mathpatch import AmbiguousInsertion, expected_boundaries

        with pytest.raises(AmbiguousInsertion):
            expected_boundaries(project(self._before()), [(1, 1, 1)])

    def test_left_affinity_shifts_the_boundary(self):
        from mathpatch import AuthorizedTextEdit, expected_boundaries

        edit = AuthorizedTextEdit(1, 1, 1, affinity="left")
        assert expected_boundaries(project(self._before()), [edit]) == (2,)

    def test_right_affinity_leaves_it_fixed(self):
        from mathpatch import AuthorizedTextEdit, expected_boundaries

        edit = AuthorizedTextEdit(1, 1, 1, affinity="right")
        assert expected_boundaries(project(self._before()), [edit]) == (1,)

    def test_a_zero_width_insertion_away_from_the_boundary_needs_no_affinity(self):
        from mathpatch import expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        assert expected_boundaries(project(p), [(1, 1, 4)]) == (7,)   # before -> shifts
        assert expected_boundaries(project(p), [(5, 5, 4)]) == (3,)   # after  -> fixed

    def test_affinity_from_host_uses_document_order_only(self):
        from mathpatch import affinity_from_host

        assert affinity_from_host((0,), (1,)) == "left"
        assert affinity_from_host((2,), (1,)) == "right"

    def test_affinity_from_host_refuses_a_containing_host(self):
        from mathpatch import AmbiguousInsertion, affinity_from_host

        with pytest.raises(AmbiguousInsertion):
            affinity_from_host((1,), (1, 0))

    def test_invalid_affinity_value_is_refused(self):
        from mathpatch import AuthorizedTextEdit

        with pytest.raises(ValueError):
            AuthorizedTextEdit(1, 1, 1, affinity="sideways")


class TestEditSetValidation:
    """An oracle must not compute a plausible answer for an impossible edit set."""

    def test_out_of_range_extent_is_refused(self):
        from mathpatch import expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        with pytest.raises(ValueError):
            expected_boundaries(project(p), [(99, 99, 1)])

    def test_inverted_extent_is_refused(self):
        from mathpatch import expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        with pytest.raises(ValueError):
            expected_boundaries(project(p), [(4, 2, 1)])

    def test_overlapping_edits_are_refused(self):
        from mathpatch import expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        with pytest.raises(ValueError):
            expected_boundaries(project(p), [(0, 2, 5), (1, 3, 5)])

    def test_an_edit_inside_another_is_refused(self):
        from mathpatch import expected_boundaries

        p = para(run("aaabbb") + omath())
        with pytest.raises(ValueError):
            expected_boundaries(project(p), [(0, 5, 3), (2, 2, 1)])

    def test_adjacent_edits_are_allowed(self):
        from mathpatch import expected_boundaries

        # patch_text "aaabbb", boundary 6. [0,3)->4 chars is +1; [3,6)->6 chars is +3.
        p = para(run("aaabbb") + omath())
        assert expected_boundaries(project(p), [(0, 3, 4), (3, 6, 6)]) == (10,)

    def test_negative_new_length_is_refused(self):
        from mathpatch import AuthorizedTextEdit

        with pytest.raises(ValueError):
            AuthorizedTextEdit(0, 1, -1)


class TestStructuralPathStability:
    """Identity must survive a w:t collapse. PLAN.md F14."""

    def test_structural_path_ignores_w_t_siblings(self):
        """A run's several w:t collapse into one when its text is rewritten. The raw
        index of anything after them inside that run shifts; the structural index
        must not."""
        many = para('<w:r><w:t>aa</w:t><w:t>bb</w:t>' + omath() + '</w:r>')
        one = para('<w:r><w:t>aabb</w:t>' + omath() + '</w:r>')
        (a,) = math_spans(many)
        (b,) = math_spans(one)
        assert a.source_path != b.source_path          # raw index moved
        assert a.structural_path == b.structural_path  # structural index did not

    def test_identity_survives_the_collapse(self):
        from mathpatch import paragraph_identity

        many = para('<w:r><w:t>aa</w:t><w:t>bb</w:t>' + omath() + '</w:r>')
        one = para('<w:r><w:t>aabb</w:t>' + omath() + '</w:r>')
        assert paragraph_identity(math_spans(many)) == paragraph_identity(math_spans(one))

    def test_identity_still_detects_a_real_move(self):
        from mathpatch import paragraph_identity

        before = para(run("A") + omath() + run("B"))
        after = para(run("A") + run("B") + omath())
        assert math_spans(before)[0].structural_path == (1,)
        assert math_spans(after)[0].structural_path == (2,)
        assert paragraph_identity(math_spans(before)) != paragraph_identity(math_spans(after))

    def test_comments_do_not_shift_structural_paths(self):
        """A comment consumes no structural index, so adding one cannot move an
        identity."""
        plain = para(run("a") + omath())
        commented = para(run("a") + "<!-- note -->" + omath())
        assert math_spans(plain)[0].structural_path == math_spans(commented)[0].structural_path

    def test_property_elements_do_not_shift_structural_paths(self):
        bare = para(run("a") + omath())
        with_props = para("<w:pPr/>" + run("a") + omath())
        assert math_spans(bare)[0].structural_path == math_spans(with_props)[0].structural_path

    def test_structural_paths_are_unique_per_span(self):
        p = para(run("a") + omath() + run("b") + omathpara() + f"<w:ins>{omath()}</w:ins>")
        paths = [s.structural_path for s in math_spans(p)]
        assert len(set(paths)) == len(paths)


class TestAdjacentMathInsertionLimits:
    """Two spans at one boundary: affinity places an insertion relative to BOTH."""

    def test_affinity_applies_to_every_span_at_that_boundary(self):
        from mathpatch import AuthorizedTextEdit, expected_boundaries

        p = para(run("A") + omath() + omath() + run("B"))
        assert project(p).math_boundaries() == (1, 1)
        left = AuthorizedTextEdit(1, 1, 1, affinity="left")
        right = AuthorizedTextEdit(1, 1, 1, affinity="right")
        assert expected_boundaries(project(p), [left]) == (2, 2)
        assert expected_boundaries(project(p), [right]) == (1, 1)

    # NOTE: inserting BETWEEN two adjacent equations -- boundaries (1, 2) -- is not
    # expressible, and deliberately so: a consumer's insertion attaches to a run
    # (`_insert_after_anchor` picks the fragment owning the character before the
    # position), and there is no run between two adjacent oMath elements. So "which run
    # hosts it" is exactly the left/right question, and no third case can arise from the
    # consumer's own insertion mechanism.

    def test_two_insertions_at_one_position_are_left_to_the_consumer(self):
        """ArtifactCert's `_insertions_share_a_slot` judges whether two insertions
        competing for one slot are compatible, using the anchor spans -- which MathPatch
        does not have. So it does not invent a rule here; it computes each edit's effect
        and lets the composition gate decide admissibility."""
        from mathpatch import AuthorizedTextEdit, expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        edits = [AuthorizedTextEdit(1, 1, 2), AuthorizedTextEdit(1, 1, 3)]
        assert expected_boundaries(project(p), edits) == (3 + 2 + 3,)
