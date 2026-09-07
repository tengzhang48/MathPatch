#!/usr/bin/env bash
# Reproduce every M0 claim in one command.
#
#   ARTIFACTCERT_DIR=/path/to/manuscripts \
#   ARTIFACTCERT_PY=/path/to/ArtifactCert/.venv/bin/python \
#   tools/verify_m0.sh
#
# ARTIFACTCERT_PY must be an interpreter that can import artifactcert (the drift gate
# compares against _para_text; copying it instead would be the drift the gate exists
# to detect). The unit tests need only lxml + pytest.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${MATHPATCH_PY:-/media/volume/cpu-vm/venvs/mathpatch/bin/python}"
AC_PY="${ARTIFACTCERT_PY:-/media/volume/cpu-vm/ArtifactCert/.venv/bin/python}"
AC_DIR="${ARTIFACTCERT_DIR:-/media/volume/cpu-vm/ArtifactCert}"

echo "== unit tests =="
"$PY" -m pytest -q

echo; echo "== regenerate the descent fixture =="
"$PY" tools/make_fixture_docx.py

echo; echo "== C14N round trip (Tier 2, shipping digest config) =="
"$AC_PY" tools/c14n_roundtrip_probe.py "$AC_DIR"/*.docx tests/fixtures/descent.docx

echo; echo "== M0 drift gate (strict extension of _para_text) =="
"$AC_PY" tools/drift_gate.py "$AC_DIR"/*.docx tests/fixtures/descent.docx

echo; echo "== corpus shape baseline (F2) =="
echo "   (all .docx: tracked-changes derivatives double-count. PLAN.md section 4 uses"
echo "    the four DISTINCT manuscripts -- read the per-file rows, not the total.)"
"$PY" tools/corpus_math_inventory.py "$AC_DIR"/*.docx

echo; echo "M0 verification complete."
