"""Canonicalized digests of protected math subtrees.

A protection oracle must prove a subtree did not change across a patch. Raw
serialization is the wrong basis: `lxml` legitimately perturbs untouched subtrees on
reserialization (namespace declarations move, empty-element forms and attribute order
normalize). XML canonicalization removes exactly that noise.

Parameters were chosen on measurement, not taste. `tools/c14n_roundtrip_probe.py`
found all four candidate parameter sets stable across 499 real math spans under a
parse -> mutate -> reserialize -> reparse round trip, including a mutation inside a
math-bearing paragraph. The choice therefore rests on purpose:

  exclusive=True      matches ArtifactCert's existing `revision_ingest._canonical_xml`,
                      and omits inherited namespace declarations the subtree does not
                      visibly use, so a span that moves in the tree still digests equal.

  with_comments=True  DIVERGES from `revision_ingest`, deliberately. That function
                      hashes textual revision evidence, where comments are noise. This
                      one proves a protected region did not change, so nothing inside
                      it may change undetected -- a comment included. ArtifactCert's
                      `opc_xml.parse_untrusted_xml` already preserves comments
                      (`remove_comments=False`), so they survive to be hashed.
"""

from __future__ import annotations

import hashlib

from lxml import etree

from .spans import ProtectedMathSpan

C14N_KWARGS: dict[str, bool] = {"exclusive": True, "with_comments": True}


def c14n_bytes(el: etree._Element) -> bytes:
    """Canonical (C14N 1.0, exclusive, comments retained) serialization of `el`."""
    return etree.tostring(el, method="c14n", **C14N_KWARGS)


def digest(el: etree._Element) -> str:
    """sha256 of `el`'s canonical serialization."""
    return hashlib.sha256(c14n_bytes(el)).hexdigest()


def span_digest(span: ProtectedMathSpan | etree._Element) -> str:
    """sha256 of a protected span's canonical serialization."""
    el = span.element if isinstance(span, ProtectedMathSpan) else span
    return digest(el)


def span_digests(spans: tuple[ProtectedMathSpan, ...] | list[ProtectedMathSpan]) -> tuple[str, ...]:
    """Ordered digests, for comparing a whole paragraph's protected regions."""
    return tuple(span_digest(s) for s in spans)
