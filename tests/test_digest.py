"""Protected-span digests survive reserialization and catch real change."""

from __future__ import annotations

import pytest

from conftest import omath, para, run
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
        edits = [(4, 10, 16)]
        assert expected_boundaries(math_spans(before), edits) == (21,)
        assert actual_boundaries(math_spans(after)) == (21,)

    def test_edit_after_the_equation_leaves_the_boundary_fixed(self):
        from mathpatch import expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        assert expected_boundaries(math_spans(p), [(3, 6, 12)]) == (3,)

    def test_a_crossing_edit_has_no_defined_transform(self):
        from mathpatch import BoundaryCrossing, expected_boundaries

        p = para(run("aaa") + omath() + run("bbb"))
        with pytest.raises(BoundaryCrossing):
            expected_boundaries(math_spans(p), [(2, 5, 3)])

    def test_multiple_edits_accumulate_only_before_the_boundary(self):
        from mathpatch import expected_boundaries

        # patch_text "aaabbbccc" with math after "aaabbb" -> boundary 6
        p = para(run("aaa") + run("bbb") + omath() + run("ccc"))
        (span,) = math_spans(p)
        assert span.patch_boundary == 6
        # +2 before, -1 before, +5 after -> boundary 6 + 1
        assert expected_boundaries([span], [(0, 3, 5), (3, 6, 2), (6, 9, 14)]) == (6 + 2 - 1,)
