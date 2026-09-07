#!/usr/bin/env bash
# Reproduce every M0/M0.1 claim, against the PINNED ArtifactCert commit.
#
#   ARTIFACTCERT_REPO=/path/to/ArtifactCert \
#   ARTIFACTCERT_DIR=/path/to/manuscripts \
#   ARTIFACTCERT_PY=/path/to/ArtifactCert/.venv/bin/python \
#   tools/verify_m0.sh
#
# This script CHECKS OUT ArtifactCert at the commit named in INTEGRATION_TARGET.txt,
# into a temporary git worktree that it removes on exit, and runs everything against
# that. It does not use whatever tree happens to be checked out: findings in this
# repository were wrong three times because of exactly that.
#
# Every step is fatal. Nothing here is allowed to print success over a failure.
#
# For the library alone -- no manuscripts, no ArtifactCert, no CI minutes -- use
# tools/test_local.sh instead.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

PY="${MATHPATCH_PY:-/media/volume/cpu-vm/venvs/mathpatch/bin/python}"
AC_REPO="${ARTIFACTCERT_REPO:-/media/volume/cpu-vm/ArtifactCert}"
AC_DIR="${ARTIFACTCERT_DIR:-$AC_REPO}"
AC_PY="${ARTIFACTCERT_PY:-$AC_REPO/.venv/bin/python}"

PIN=$(grep -vE '^\s*(#|$)' INTEGRATION_TARGET.txt | head -1)
echo "== pinned ArtifactCert target =="
echo "   $PIN"

[ -d "$AC_REPO/.git" ] || { echo "   FAIL: $AC_REPO is not a git repository"; exit 1; }
git -C "$AC_REPO" fetch --all --quiet || echo "   (fetch failed; continuing with local objects)"
git -C "$AC_REPO" rev-parse --verify --quiet "$PIN^{commit}" >/dev/null || {
  echo "   FAIL: commit $PIN not present in $AC_REPO"; exit 1; }
echo "   date: $(git -C "$AC_REPO" log -1 --format=%cI "$PIN")"

WT="${TMPDIR:-/tmp}/artifactcert-pinned-$$"
cleanup() { git -C "$AC_REPO" worktree remove --force "$WT" >/dev/null 2>&1 || true; }
trap cleanup EXIT
git -C "$AC_REPO" worktree add --detach --quiet "$WT" "$PIN"
AC_SRC="$WT/src"
echo "   checked out at $WT ($(git -C "$WT" rev-parse --short HEAD))"

echo; echo "== unit tests =="
"$PY" -m pytest -q

echo; echo "== fixture generator is byte-reproducible =="
before=$(sha256sum tests/fixtures/descent.docx | cut -d' ' -f1)
"$PY" tools/make_fixture_docx.py >/dev/null
after=$(sha256sum tests/fixtures/descent.docx | cut -d' ' -f1)
[ "$before" = "$after" ] || { echo "   FAIL: fixture bytes changed"; exit 1; }
echo "   ok"

echo; echo "== C14N round trip (Tier 2, shipping digest config) =="
"$AC_PY" tools/c14n_roundtrip_probe.py "$AC_DIR"/*.docx tests/fixtures/descent.docx

echo; echo "== F7 regression probe (must NOT reproduce against the pin) =="
ARTIFACTCERT_SRC="$AC_SRC" "$AC_PY" tools/probe_offset_skew.py

echo; echo "== M0 drift gate (strict extension of _para_text) =="
ARTIFACTCERT_SRC="$AC_SRC" "$AC_PY" tools/drift_gate.py --artifactcert-src "$AC_SRC" \
  "$AC_DIR"/*.docx tests/fixtures/descent.docx

echo; echo "== corpus shape baseline (F2) =="
echo "   (all .docx: tracked-changes derivatives double-count. PLAN.md section 4 uses"
echo "    the four DISTINCT manuscripts -- read the per-file rows, not the total.)"
"$PY" tools/corpus_math_inventory.py "$AC_DIR"/*.docx

echo; echo "== evidence record =="
ARTIFACTCERT_SRC="$AC_SRC" ARTIFACTCERT_DIR="$AC_DIR" "$PY" tools/make_evidence.py

echo; echo "M0 VERIFICATION COMPLETE -- all steps passed against $PIN"
