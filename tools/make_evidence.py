#!/usr/bin/env python3
"""Write M0_EVIDENCE.json: bind the M0 claims to exact versions and inputs.

"M0 complete" is otherwise tied to whatever happens to sit in a local directory.
This records the commits, interpreter, library versions, and a content hash per
corpus document, so the claim can be re-checked later or disputed precisely.

Manuscripts are recorded by ALIAS plus sha256, never by filename: the titles are
unpublished work and the repository is a public artifact. The sha256 is what makes
the record verifiable -- anyone holding the same file can confirm the binding.

Usage:
    ARTIFACTCERT_DIR=/path/to/manuscripts \
    ARTIFACTCERT_SRC=/path/to/ArtifactCert/src \
    make_evidence.py [-o M0_EVIDENCE.json]
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def expected_artifactcert_commit() -> str:
    """The pinned integration target, from INTEGRATION_TARGET.txt."""
    for line in (ROOT / "INTEGRATION_TARGET.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise SystemExit("INTEGRATION_TARGET.txt contains no commit hash")


def sh(*args: str, cwd: Path | None = None) -> str | None:
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=60, check=False
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    out_path = ROOT / "M0_EVIDENCE.json"
    if "-o" in argv:
        out_path = Path(argv[argv.index("-o") + 1])

    ac_src = os.environ.get("ARTIFACTCERT_SRC", "/media/volume/cpu-vm/ArtifactCert/src")
    ac_dir = os.environ.get("ARTIFACTCERT_DIR", str(Path(ac_src).parent))
    if not (Path(ac_src) / "artifactcert" / "docx_manifest.py").is_file():
        print(f"ARTIFACTCERT_SRC not usable: {ac_src}", file=sys.stderr)
        return 2

    # FAIL CLOSED on the pin. An evidence record that names one commit while the
    # code under test came from another certifies nothing -- that is precisely the
    # wrong-tree failure this record exists to prevent.
    expected = expected_artifactcert_commit()
    actual = sh("git", "rev-parse", "HEAD", cwd=Path(ac_src).parent)
    if actual != expected:
        print(
            f"REFUSED: ArtifactCert at {ac_src} is {actual}, not the pinned "
            f"{expected}.\n"
            f"  Create a pinned tree:  git -C <artifactcert> worktree add --detach "
            f"<dir> {expected}\n"
            f"  or run tools/verify_m0.sh, which does that for you.",
            file=sys.stderr,
        )
        return 3

    # A record generated from an uncommitted tree cannot be re-derived.
    if sh("git", "status", "--porcelain", cwd=ROOT):
        print(
            "REFUSED: the MathPatch tree is dirty. Commit the implementation first, "
            "then generate the evidence record, then commit the record.",
            file=sys.stderr,
        )
        return 4

    sys.path.insert(0, ac_src)

    from lxml import etree

    from artifactcert.docx_manifest import enumerate_paragraphs, paragraph_flags
    from artifactcert.opc_xml import parse_untrusted_xml
    from mathpatch import CANONICAL_TEXT_CONTRACT_VERSION, C14N_KWARGS, __version__, project

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    corpus = []
    corpus_errors: list[str] = []
    for i, path in enumerate(sorted(glob.glob(os.path.join(ac_dir, "*.docx"))), start=1):
        try:
            with zipfile.ZipFile(path) as z:
                raw = z.read("word/document.xml")
            root = parse_untrusted_xml(raw, part_name="word/document.xml")
        except Exception as exc:  # recorded, never silently dropped
            corpus.append({"alias": f"doc-{i:02d}", "error": str(exc)})
            corpus_errors.append(f"doc-{i:02d}: {exc}")
            continue
        body = root.find(f"{W}body")
        if body is None:
            corpus.append({"alias": f"doc-{i:02d}", "error": "no w:body"})
            corpus_errors.append(f"doc-{i:02d}: no w:body")
            continue
        paras = math_paras = spans = anomalies = 0
        disagreements = 0
        for _loc, p in enumerate_paragraphs(body):
            proj = project(p)
            paras += 1
            if proj.spans:
                math_paras += 1
                spans += len(proj.spans)
            if proj.anomalies:
                anomalies += 1
            if ("math" in paragraph_flags(p)) != bool(proj.spans):
                disagreements += 1
        if disagreements:
            corpus_errors.append(
                f"doc-{i:02d}: {disagreements} detection disagreement(s) vs paragraph_flags"
            )
        corpus.append({
            "detection_disagreements": disagreements,
            "alias": f"doc-{i:02d}",
            "sha256": file_sha256(path),
            "bytes": os.path.getsize(path),
            "paragraph_count": paras,
            "math_paragraph_count": math_paras,
            "math_span_count": spans,
            "paragraphs_with_anomalies": anomalies,
        })

    fixture = ROOT / "tests" / "fixtures" / "descent.docx"
    record = {
        "record": "MathPatch M0 evidence",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mathpatch": {
            "version": __version__,
            "commit": sh("git", "rev-parse", "HEAD", cwd=ROOT),
            "dirty": False,  # refused above if dirty
            "canonical_text_contract_version": CANONICAL_TEXT_CONTRACT_VERSION,
            "c14n_kwargs": C14N_KWARGS,
        },
        "artifactcert": {
            "src": ac_src,
            "pinned_target": expected,
            "commit": actual,
            "origin_main": sh("git", "rev-parse", "origin/main", cwd=Path(ac_src).parent),
            "origin_main_date": sh(
                "git", "log", "-1", "--format=%cI", "origin/main", cwd=Path(ac_src).parent
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "lxml": etree.__version__,
            "platform": platform.platform(),
        },
        "fixture": {
            "path": "tests/fixtures/descent.docx",
            "sha256": file_sha256(str(fixture)) if fixture.is_file() else None,
        },
        "corpus": corpus,
        "checks": {
            "unit_tests": subprocess.run(
                [sys.executable, "-m", "pytest", "-q"], cwd=ROOT,
                capture_output=True, text=True, check=False,
            ).returncode == 0,
            "note": "drift gate and C14N probe are run by tools/verify_m0.sh; "
                    "this record binds the inputs they were run against.",
        },
    }

    unit_ok = record["checks"]["unit_tests"]
    if corpus_errors or not unit_ok:
        print("REFUSED: not writing an evidence record for a failing run.",
              file=sys.stderr)
        for e in corpus_errors:
            print(f"  corpus: {e}", file=sys.stderr)
        if not unit_ok:
            print("  unit tests: FAILED", file=sys.stderr)
        return 1

    out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out_path}")
    print(f"  artifactcert origin/main = {record['artifactcert']['origin_main']}"
          f" ({record['artifactcert']['origin_main_date']})")
    print(f"  corpus documents = {len(corpus)}")
    print(f"  unit tests pass  = {record['checks']['unit_tests']}")
    print(f"  pinned target certified = {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
