"""Span discovery: outermost-only, and by descent."""

from __future__ import annotations

from conftest import omath, omathpara, para, run

from mathpatch import MATH_TAGS, has_math, outermost_math


def test_outermost_does_not_recurse_into_a_match():
    """m:oMathPara wraps m:oMath; a naive descent double-counts.

    Measured on Hygrochastic Revision v5: naive descent 114, outermost 90.
    """
    p = para(omathpara())
    found = list(outermost_math(p))
    assert len(found) == 1
    assert found[0].tag.endswith("oMathPara")
    # the inner oMath exists but is not yielded separately
    assert sum(1 for el in p.iter() if el.tag in MATH_TAGS) == 2


def test_descent_finds_math_inside_a_revision_wrapper():
    """Scanning direct children of w:p under-reports, the dangerous direction."""
    p = para(f"{run('a')}<w:ins>{omath()}</w:ins>")
    assert [el.tag.endswith("oMath") for el in outermost_math(p)] == [True]
    assert not any(c.tag in MATH_TAGS for c in p)  # not a direct child


def test_descent_order_is_document_order():
    p = para(f"{run('a')}{omath()}<w:hyperlink>{omath()}</w:hyperlink>{omath()}")
    assert len(list(outermost_math(p))) == 3


def test_has_math():
    assert has_math(para(omath()))
    assert has_math(para(f"<w:ins>{omath()}</w:ins>"))
    assert not has_math(para(run("plain")))
