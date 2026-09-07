#!/usr/bin/env bash
# Run exactly what CI would, locally, in a throwaway virtualenv.
#
#   tools/test_local.sh
#
# Needs nothing but Python and this repository: no manuscripts, no ArtifactCert,
# no GitHub Actions minutes. This is the gate for the library's internal
# consistency. For the corpus claims (drift gate, C14N probe over real
# manuscripts) use tools/verify_m0.sh instead.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${TMPDIR:-/tmp}/mathpatch-test-$$"
trap 'rm -rf "$VENV"' EXIT
echo "== clean virtualenv: $VENV =="
python3 -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip
"$VENV/bin/pip" -q install -e ".[dev]"
echo "   python $("$VENV/bin/python" -c 'import platform;print(platform.python_version())')"

echo; echo "== unit tests =="
"$VENV/bin/python" -m pytest -q

echo; echo "== fixture generator is byte-reproducible =="
before=$(sha256sum tests/fixtures/descent.docx | cut -d' ' -f1)
"$VENV/bin/python" tools/make_fixture_docx.py >/dev/null
after=$(sha256sum tests/fixtures/descent.docx | cut -d' ' -f1)
if [ "$before" != "$after" ]; then
  echo "   FAIL: regenerating descent.docx changed its bytes"
  echo "     before $before"
  echo "     after  $after"
  exit 1
fi
echo "   ok ($before)"

echo; echo "== inventory runs on the synthetic fixture =="
"$VENV/bin/python" tools/corpus_math_inventory.py tests/fixtures/descent.docx >/dev/null
echo "   ok"

echo; echo "ALL LOCAL CHECKS PASSED"
