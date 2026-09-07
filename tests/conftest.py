from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def para(inner: str) -> etree._Element:
    """Parse a paragraph body into a w:p element, namespaces declared."""
    return etree.fromstring(f'<w:p xmlns:w="{W}" xmlns:m="{M}">{inner}</w:p>')


def run(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def omath(body: str = "<m:r><m:t>x</m:t></m:r>") -> str:
    return f"<m:oMath>{body}</m:oMath>"


def omathpara(body: str = "") -> str:
    """A display container, which always wraps at least one m:oMath."""
    return f"<m:oMathPara>{body or omath()}</m:oMathPara>"
