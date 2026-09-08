"""M2a: address one m:t inside an equation and swap its text, source-preserving.

Scoped by F16: every named Phase-2 edit in the real corpus -- one identifier, one
subscript, one literal, one operator -- is a change to the text of a single m:t. So the
first real mutation needs no AST, and 72% of an equation being Word formatting is exactly
why it must mutate the smallest original node rather than regenerate anything.
"""

from __future__ import annotations

import pytest
from conftest import para, run
from lxml import etree

from mathpatch import (
    MathTextEdit,
    PreimageMismatch,
    TargetNotFound,
    apply_math_text_edit,
    math_spans,
    project,
    span_digest,
    text_targets,
)

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def mr(text: str, *, space: bool = False, fmt: bool = False) -> str:
    """One m:r, optionally carrying xml:space and a w:rPr formatting block."""
    rpr = (
        f'<m:rPr><m:sty m:val="p"/></m:rPr>'
        f'<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>'
        f'<w:i w:val="0"/><w:color w:val="FF0000"/><w:sz w:val="24"/></w:rPr>'
        if fmt else ""
    )
    sp = ' xml:space="preserve"' if space else ""
    return f"<m:r>{rpr}<m:t{sp}>{text}</m:t></m:r>"


def eq(*runs: str) -> str:
    return f"<m:oMath>{''.join(runs)}</m:oMath>"


def subscripted(base: str, sub: str) -> str:
    """m:sSub -- the most common structure in the corpus (431 occurrences)."""
    return (
        f"<m:oMath><m:sSub><m:sSubPr><m:ctrlPr/></m:sSubPr>"
        f"<m:e>{mr(base)}</m:e><m:sub>{mr(sub)}</m:sub></m:sSub></m:oMath>"
    )


class TestAddressing:
    def test_targets_are_listed_in_document_order(self):
        p = para(run("x") + eq(mr("E"), mr("+"), mr("m")))
        (span,) = math_spans(p)
        targets = text_targets(span)
        assert [t.text for t in targets] == ["E", "+", "m"]
        assert [t.text_ordinal for t in targets] == [0, 1, 2]

    def test_targets_reach_into_nested_structures(self):
        p = para(subscripted("E", "f"))
        (span,) = math_spans(p)
        assert [t.text for t in text_targets(span)] == ["E", "f"]

    def test_target_carries_a_locating_path(self):
        p = para(subscripted("E", "f"))
        (span,) = math_spans(p)
        for target in text_targets(span):
            node = span.source_element
            for index in target.source_path:
                node = node[index]
            assert node is target.element

    def test_empty_equation_has_no_targets(self):
        p = para("<m:oMath><m:r><m:t></m:t></m:r></m:oMath>")
        (span,) = math_spans(p)
        assert text_targets(span) == ()


class TestPreimage:
    """MathPatch owns the statement "I mutated exactly the state you authorized"."""

    @staticmethod
    def _setup():
        p = para(run("where ") + subscripted("E", "f"))
        (span,) = math_spans(p)
        return p, span

    def test_a_correct_preimage_applies(self):
        p, span = self._setup()
        edit = MathTextEdit(
            span_ordinal=0, text_ordinal=1, expected_text="f",
            expected_span_digest=span_digest(span), new_text="m",
        )
        receipt = apply_math_text_edit(p, edit)
        assert receipt.applied
        assert [t.text for t in text_targets(math_spans(p)[0])] == ["E", "m"]

    def test_wrong_expected_text_is_refused(self):
        p, span = self._setup()
        edit = MathTextEdit(0, 1, "WRONG", span_digest(span), "m")
        with pytest.raises(PreimageMismatch) as exc:
            apply_math_text_edit(p, edit)
        assert "text" in str(exc.value).lower()

    def test_stale_span_digest_is_refused(self):
        p, span = self._setup()
        edit = MathTextEdit(0, 1, "f", "0" * 64, "m")
        with pytest.raises(PreimageMismatch) as exc:
            apply_math_text_edit(p, edit)
        assert "digest" in str(exc.value).lower()

    def test_nothing_is_mutated_when_the_preimage_fails(self):
        p, span = self._setup()
        before = span_digest(span)
        with pytest.raises(PreimageMismatch):
            apply_math_text_edit(p, MathTextEdit(0, 1, "WRONG", before, "m"))
        assert span_digest(math_spans(p)[0]) == before

    def test_missing_span_or_target_is_refused(self):
        p, span = self._setup()
        with pytest.raises(TargetNotFound):
            apply_math_text_edit(p, MathTextEdit(9, 0, "E", span_digest(span), "X"))
        with pytest.raises(TargetNotFound):
            apply_math_text_edit(p, MathTextEdit(0, 9, "E", span_digest(span), "X"))


class TestSourcePreservation:
    """72% of an equation is Word formatting (F16). None of it may move."""

    def test_formatting_blocks_survive(self):
        p = para(eq(mr("E", fmt=True), mr("+"), mr("m", fmt=True)))
        (span,) = math_spans(p)
        edit = MathTextEdit(0, 0, "E", span_digest(span), "G")
        apply_math_text_edit(p, edit)
        after = math_spans(p)[0].source_element
        rprs = after.findall(f".//{{{W}}}rPr")
        assert len(rprs) == 2
        assert after.find(f".//{{{W}}}color").get(f"{{{W}}}val") == "FF0000"
        assert after.find(f".//{{{M}}}sty").get(f"{{{M}}}val") == "p"

    def test_only_the_target_changes(self):
        """The skeleton digest -- the span with the target's text blanked -- must be
        byte-identical before and after."""
        from mathpatch import skeleton_digest

        p = para(eq(mr("E", fmt=True), mr("+"), mr("m", fmt=True)))
        (span,) = math_spans(p)
        before = skeleton_digest(span, 0)
        apply_math_text_edit(p, MathTextEdit(0, 0, "E", span_digest(span), "G"))
        assert skeleton_digest(math_spans(p)[0], 0) == before

    def test_xml_space_is_preserved_when_present(self):
        p = para(eq(mr(" E ", space=True)))
        (span,) = math_spans(p)
        apply_math_text_edit(p, MathTextEdit(0, 0, " E ", span_digest(span), " G "))
        t = math_spans(p)[0].source_element.find(f".//{{{M}}}t")
        assert t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"

    def test_xml_space_is_added_when_new_text_needs_it(self):
        p = para(eq(mr("E")))
        (span,) = math_spans(p)
        apply_math_text_edit(p, MathTextEdit(0, 0, "E", span_digest(span), " G "))
        t = math_spans(p)[0].source_element.find(f".//{{{M}}}t")
        assert t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"

    def test_xml_space_is_not_removed_gratuitously(self):
        p = para(eq(mr("E", space=True)))
        (span,) = math_spans(p)
        apply_math_text_edit(p, MathTextEdit(0, 0, "E", span_digest(span), "G"))
        t = math_spans(p)[0].source_element.find(f".//{{{M}}}t")
        assert t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"


class TestParagraphInvariants:
    """An equation edit must be invisible to the text stream."""

    def test_patch_text_is_unchanged(self):
        """Math is zero width, so a mutation inside it must not touch patch_text."""
        p = para(run("where ") + subscripted("E", "f") + run(" holds"))
        before = project(p).patch_text
        (span,) = math_spans(p)
        apply_math_text_edit(p, MathTextEdit(0, 1, "f", span_digest(span), "m"))
        assert project(p).patch_text == before

    def test_boundaries_are_unchanged(self):
        p = para(run("a") + subscripted("E", "f") + run("b"))
        before = project(p).math_boundaries()
        (span,) = math_spans(p)
        apply_math_text_edit(p, MathTextEdit(0, 1, "f", span_digest(span), "m"))
        assert project(p).math_boundaries() == before

    def test_other_spans_keep_their_identity(self):
        from mathpatch import math_identity

        p = para(run("a") + subscripted("E", "f") + run("b") + eq(mr("Z")))
        spans = math_spans(p)
        untouched_before = math_identity(spans[1])
        apply_math_text_edit(p, MathTextEdit(0, 1, "f", span_digest(spans[0]), "m"))
        assert math_identity(math_spans(p)[1]) == untouched_before

    def test_the_edited_span_identity_changes(self):
        """It must: the whole point is that its contents differ now."""
        from mathpatch import math_identity

        p = para(subscripted("E", "f"))
        (span,) = math_spans(p)
        before = math_identity(span)
        apply_math_text_edit(p, MathTextEdit(0, 1, "f", span_digest(span), "m"))
        assert math_identity(math_spans(p)[0]) != before

    def test_span_count_and_order_are_unchanged(self):
        p = para(eq(mr("A")) + run("x") + eq(mr("B")))
        spans = math_spans(p)
        apply_math_text_edit(p, MathTextEdit(1, 0, "B", span_digest(spans[1]), "C"))
        after = math_spans(p)
        assert len(after) == 2
        assert [s.ordinal for s in after] == [0, 1]
        assert [t.text for t in text_targets(after[0])] == ["A"]


class TestReceipt:
    def test_receipt_records_what_changed(self):
        p = para(subscripted("E", "f"))
        (span,) = math_spans(p)
        edit = MathTextEdit(0, 1, "f", span_digest(span), "m")
        receipt = apply_math_text_edit(p, edit)
        assert receipt.applied
        assert receipt.old_text == "f"
        assert receipt.new_text == "m"
        assert receipt.span_digest_before == edit.expected_span_digest
        assert receipt.span_digest_after != receipt.span_digest_before
        assert receipt.skeleton_digest_before == receipt.skeleton_digest_after

    def test_a_no_op_edit_is_refused(self):
        p = para(subscripted("E", "f"))
        (span,) = math_spans(p)
        with pytest.raises(ValueError):
            apply_math_text_edit(p, MathTextEdit(0, 1, "f", span_digest(span), "f"))


class TestAtomicity:
    """Every refusal path must leave the document exactly as it was.

    The library's promise is "I mutated exactly what you authorized, and nothing else".
    A refusal that leaves a half-applied edit behind breaks it: a caller catching the
    error holds a corrupted document believing nothing happened. Verified broken before
    it was fixed -- the fail-closed guard left ['E','+','m'] as ['E','G','m'].
    """

    @staticmethod
    def _paragraph():
        return para(eq(mr("E"), mr("+"), mr("m", space=True)))

    def test_preimage_refusal_leaves_no_trace(self):
        p = self._paragraph()
        (span,) = math_spans(p)
        before = span_digest(span)
        with pytest.raises(PreimageMismatch):
            apply_math_text_edit(p, MathTextEdit(0, 0, "WRONG", before, "G"))
        assert span_digest(math_spans(p)[0]) == before

    def test_containment_guard_restores_the_target(self, monkeypatch):
        """Force the guard to fire and require the document to be untouched."""
        import mathpatch.edit as edit_module

        p = self._paragraph()
        (span,) = math_spans(p)
        before_digest = span_digest(span)
        before_texts = [t.text for t in text_targets(span)]

        real = edit_module.skeleton_digest
        calls = {"n": 0}

        def flaky(seg, ordinal):
            calls["n"] += 1
            return "deadbeef" if calls["n"] > 1 else real(seg, ordinal)

        monkeypatch.setattr(edit_module, "skeleton_digest", flaky)
        with pytest.raises(AssertionError):
            apply_math_text_edit(p, MathTextEdit(0, 0, "E", before_digest, "G"))

        assert [t.text for t in text_targets(math_spans(p)[0])] == before_texts
        assert span_digest(math_spans(p)[0]) == before_digest

    def test_guard_restores_an_absent_xml_space(self, monkeypatch):
        """Restoring must remove an attribute the edit added, not just reset text."""
        import mathpatch.edit as edit_module

        p = para(eq(mr("E")))          # no xml:space to begin with
        (span,) = math_spans(p)
        before_digest = span_digest(span)
        real = edit_module.skeleton_digest
        calls = {"n": 0}

        def flaky(seg, ordinal):
            calls["n"] += 1
            return "deadbeef" if calls["n"] > 1 else real(seg, ordinal)

        monkeypatch.setattr(edit_module, "skeleton_digest", flaky)
        with pytest.raises(AssertionError):
            apply_math_text_edit(p, MathTextEdit(0, 0, "E", before_digest, " G "))

        t = math_spans(p)[0].source_element.find(
            "{http://schemas.openxmlformats.org/officeDocument/2006/math}r/"
            "{http://schemas.openxmlformats.org/officeDocument/2006/math}t"
        )
        assert t.get("{http://www.w3.org/XML/1998/namespace}space") is None
        assert span_digest(math_spans(p)[0]) == before_digest

    def test_no_op_and_empty_refusals_leave_no_trace(self):
        p = self._paragraph()
        (span,) = math_spans(p)
        before = span_digest(span)
        with pytest.raises(ValueError):
            apply_math_text_edit(p, MathTextEdit(0, 0, "E", before, "E"))
        with pytest.raises(ValueError):
            apply_math_text_edit(p, MathTextEdit(0, 0, "E", before, ""))
        assert span_digest(math_spans(p)[0]) == before

    def test_guard_restores_even_a_write_to_the_wrong_node(self, monkeypatch):
        """Restoring only the intended target is not enough: a writer bug that touched a
        different node would be caught by the guard and then left in place. Observed
        before the fix -- the refusal kept ['E','G','m']."""
        import mathpatch.edit as edit_module

        p = para(eq(mr("E"), mr("+"), mr("m")))
        (span,) = math_spans(p)
        before_digest = span_digest(span)
        before_texts = [t.text for t in text_targets(span)]

        real_targets = edit_module.text_targets

        def sabotage(seg):
            found = real_targets(seg)
            # simulate a bug: hand back a target list pointing one node to the right
            if len(found) > 1:
                return (found[1],) + found[1:]
            return found

        monkeypatch.setattr(edit_module, "text_targets", sabotage)
        with pytest.raises((AssertionError, PreimageMismatch)):
            apply_math_text_edit(p, MathTextEdit(0, 0, "E", before_digest, "G"))

        assert [t.text for t in text_targets(math_spans(p)[0])] == before_texts
        assert span_digest(math_spans(p)[0]) == before_digest


class TestOrdinalDriftIsCaught:
    """text_ordinal counts NON-EMPTY m:t, so filling an empty one renumbers them.

    The address alone would then point at a different node. It is the span digest in the
    preimage that protects against this -- any change to the equation, including filling
    an empty text node, changes the digest and refuses the edit. This tests that the
    protection actually holds rather than assuming it.
    """

    def test_filling_an_empty_m_t_shifts_ordinals(self):
        empty = para(
            "<m:oMath><m:r><m:t></m:t></m:r>" + mr("E") + mr("f") + "</m:oMath>"
        )
        assert [t.text for t in text_targets(math_spans(empty)[0])] == ["E", "f"]
        filled = para("<m:oMath>" + mr("Q") + mr("E") + mr("f") + "</m:oMath>")
        assert [t.text for t in text_targets(math_spans(filled)[0])] == ["Q", "E", "f"]

    def test_a_digest_authorized_before_the_fill_is_refused_after(self):
        p = para("<m:oMath><m:r><m:t></m:t></m:r>" + mr("E") + mr("f") + "</m:oMath>")
        (span,) = math_spans(p)
        stale = span_digest(span)
        assert text_targets(span)[0].text == "E"

        # something fills the empty node; ordinal 0 now means a different element
        empty_t = span.source_element.find(
            "{http://schemas.openxmlformats.org/officeDocument/2006/math}r/"
            "{http://schemas.openxmlformats.org/officeDocument/2006/math}t"
        )
        empty_t.text = "Q"
        assert text_targets(math_spans(p)[0])[0].text == "Q"

        with pytest.raises(PreimageMismatch) as exc:
            apply_math_text_edit(p, MathTextEdit(0, 0, "E", stale, "G"))
        assert "digest" in str(exc.value).lower()
