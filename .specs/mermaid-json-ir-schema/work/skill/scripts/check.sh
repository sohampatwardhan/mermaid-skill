#!/usr/bin/env bash
# Validate/render a Mermaid diagram LOCALLY, without the MCP server.
# Uses @mermaid-js/mermaid-cli (mmdc). Good as a fallback when the MCP is
# unavailable, or for offline/CI validation.
#
# Usage:
#   check.sh diagram.mmd                 # validate (render to a temp SVG, discard)
#   check.sh diagram.mmd -o out.svg      # validate AND keep the rendered SVG/PNG/PDF
#   cat diagram.mmd | check.sh           # read from stdin
#   check.sh -c 'flowchart TD; A-->B'    # inline code
#
# Exit 0 = renders cleanly. Non-zero = syntax/render error (message printed).
set -euo pipefail

OUT=""; INPUT=""; CODE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) OUT="${2:-}"; shift 2;;
    -c) CODE="${2:-}"; shift 2;;
    -h|--help) sed -n '2,11p' "$0"; exit 0;;
    *) INPUT="$1"; shift;;
  esac
done

TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_LOCAL}"' EXIT

# Resolve the source into a .mmd file.
SRC="${TMPDIR_LOCAL}/in.mmd"
if [ -n "${CODE}" ]; then
  printf '%s\n' "${CODE}" > "${SRC}"
elif [ -n "${INPUT}" ]; then
  [ -f "${INPUT}" ] || { echo "ERROR: file not found: ${INPUT}"; exit 2; }
  cp "${INPUT}" "${SRC}"
elif [ ! -t 0 ]; then
  cat > "${SRC}"
else
  echo "ERROR: no input. Pass a file, -c '<code>', or pipe via stdin. (-h for help)"; exit 2
fi

[ -s "${SRC}" ] || { echo "ERROR: empty diagram."; exit 2; }

# Rendering is a separate, explicitly versioned capability. npx may populate its external npm
# cache on first use; compilation/schema processing never invokes it or requires network access.
if command -v npx >/dev/null 2>&1; then
  RUN=(npx --yes --package @mermaid-js/mermaid-cli@11.16.0 mmdc)
else
  echo "ERROR: exact Mermaid CLI 11.16.0 requires npx on PATH."
  exit 3
fi

# CLI 11.16.0 is contract-bound to Mermaid core 11.16.1. The source and error-artifact checks
# below validate the exact bytes passed to that execution context; a different core is unsupported.
PINNED_CORE="11.16.1"
export MERMAID_IR_EXPECTED_CORE="${PINNED_CORE}"

VALIDATION_DEST="${TMPDIR_LOCAL}/validation.svg"
ERRLOG="${TMPDIR_LOCAL}/err.log"

if ! "${RUN[@]}" -i "${SRC}" -o "${VALIDATION_DEST}" >"${ERRLOG}" 2>&1; then
  echo "FAIL: Mermaid could not render the diagram."
  echo "----- mermaid-cli output -----"
  cat "${ERRLOG}"
  echo "------------------------------"
  echo "Fix the reported line/token and re-run. Syntax reference:"
  echo "  reference/syntax/<type>.md  or  reference/type-cheatsheets.md"
  exit 1
fi

# Mermaid CLI can exit 0 while writing its syntax-error placeholder SVG. Inspect
# the artifact itself so an error image is never reported as a successful render.
if grep -Eiq 'aria-roledescription="error"|class="error-icon"|>Syntax error in text<' "${VALIDATION_DEST}"; then
  echo "FAIL: Mermaid emitted an error SVG despite returning exit 0."
  echo "----- mermaid-cli output -----"
  cat "${ERRLOG}"
  echo "------------------------------"
  echo "Inspect the source with the target Mermaid version; beta diagram lexers may reject"
  echo "label punctuation accepted by other diagram types."
  exit 1
fi

if [ -n "${OUT}" ]; then
  case "${OUT}" in
    *.svg) cp "${VALIDATION_DEST}" "${OUT}" ;;
    *)
      if ! "${RUN[@]}" -i "${SRC}" -o "${OUT}" >"${ERRLOG}" 2>&1; then
        echo "FAIL: Mermaid validated as SVG but could not write ${OUT}."
        cat "${ERRLOG}"
        exit 1
      fi
      ;;
  esac
fi

echo "PASS: diagram renders cleanly."
[ -n "${OUT}" ] && echo "Wrote ${OUT}"
exit 0
