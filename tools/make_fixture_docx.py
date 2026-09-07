#!/usr/bin/env python3
"""Generate tests/fixtures/descent.docx -- structures the real corpus does not contain.

Measured on the seven reference manuscripts: all 1,167 math spans are DIRECT children
of `w:p`. Zero sit inside a revision wrapper, hyperlink, content control, or run. So
`tools/drift_gate.py` over that corpus cannot exercise the descent path of PLAN.md F5,
and a regression that dropped descent entirely passed the gate unnoticed.

This fixture supplies the missing shapes so the gate is sensitive to them:

  p0  math-free control
  p1  inline math with text on both sides            (the 48.5% shape, F2)
  p2  math inside w:ins                              (descent, F5)
  p3  math inside w:hyperlink                        (descent + excluded link text)
  p4  math inside a w:r                              (total discovery)
  p5  m:oMathPara wrapping m:oMath                   (outermost-only)
  p6  two adjacent math spans
  p7  deeply nested w:t inside a direct run          (F6: _para_text uses .iter())
  p8  math-only paragraph (display equation)

Usage: make_fixture_docx.py [out.docx]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def r(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def om(sym: str = "x") -> str:
    return f"<m:oMath><m:r><m:t>{sym}</m:t></m:r></m:oMath>"


def p(inner: str) -> str:
    return f"<w:p>{inner}</w:p>"


def document() -> str:
    ins = '<w:ins w:id="101" w:author="fixture" w:date="2026-09-07T00:00:00Z">'
    body = "".join(
        [
            p(r("A math-free control paragraph.")),
            p(r("The deformation ") + om("sigma") + r(" increases rapidly.")),
            p(r("before ") + ins + r("inserted") + om("a") + "</w:ins>" + r(" after")),
            p(r("AAA ") + f'<w:hyperlink w:anchor="ref1">{r("LINK")}{om("b")}</w:hyperlink>' + r(" BBB")),
            p(f'<w:r><w:t xml:space="preserve">in-run </w:t>{om("c")}<w:t>tail</w:t></w:r>'),
            p(f"<m:oMathPara>{om('d')}</m:oMathPara>"),
            p(r("pair ") + om("e") + om("f") + r(" done")),
            p(f'<w:r><w:t>shallow</w:t><w:smartTag w:element="x"><w:t>deep</w:t></w:smartTag></w:r>'),
            p(om("g")),
        ]
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:m="{M}">'
        f"<w:body>{body}</w:body></w:document>"
    )


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else (
        Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "descent.docx"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", document())
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
