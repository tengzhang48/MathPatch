"""MathPatch -- precise, auditable editing of equations in Word documents.

MathPatch owns math representation and serialization. It does NOT own document
addressing, object identity, authorization, or release decisions. Every entry point
takes an already-located `lxml` element and returns offsets relative to that element;
MathPatch never opens a file, resolves a locator, or sees an object id. See PLAN.md
section 2 -- that boundary is binding, not aspirational.
"""

from __future__ import annotations

from .canonical import (
    CANONICAL_TEXT_CONTRACT_VERSION,
    Projection,
    SentinelCollision,
    canonical_text,
    crosses_math_boundary,
    intersects_math,
    math_spans,
    project,
)
from .digest import (
    C14N_KWARGS,
    BoundaryCrossing,
    actual_boundaries,
    c14n_bytes,
    digest,
    expected_boundaries,
    math_identity,
    paragraph_fingerprint,
    paragraph_identity,
    span_digest,
    span_digests,
    span_fingerprint,
)
from .spans import (
    MATH_TAGS,
    OMATH,
    OMATHPARA,
    SENTINEL,
    M_NS,
    ProtectedMathSpan,
    W_NS,
    has_math,
    outermost_math,
    qn,
)

__version__ = "0.1.0"

__all__ = [
    "CANONICAL_TEXT_CONTRACT_VERSION",
    "BoundaryCrossing",
    "C14N_KWARGS",
    "actual_boundaries",
    "MATH_TAGS",
    "M_NS",
    "OMATH",
    "OMATHPARA",
    "ProtectedMathSpan",
    "Projection",
    "SENTINEL",
    "SentinelCollision",
    "W_NS",
    "__version__",
    "c14n_bytes",
    "canonical_text",
    "crosses_math_boundary",
    "digest",
    "expected_boundaries",
    "math_identity",
    "has_math",
    "intersects_math",
    "math_spans",
    "outermost_math",
    "paragraph_fingerprint",
    "paragraph_identity",
    "project",
    "qn",
    "span_digest",
    "span_digests",
    "span_fingerprint",
]
