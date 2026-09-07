"""Protected-span digests survive reserialization and catch real change."""

from __future__ import annotations

from conftest import omath, para, run
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
