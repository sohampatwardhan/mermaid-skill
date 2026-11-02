#!/usr/bin/env bash
# Validate a Mermaid diagram locally with Mermaid CLI 12.0.0 (no MCP server needed).
#
# Usage:
#   check.sh diagram.mmd                 # validate (render to a temp SVG, discard)
#   check.sh diagram.mmd -o out.svg      # validate AND keep the rendered SVG/PNG/PDF
#   cat diagram.mmd | check.sh           # read from stdin
#   check.sh -c 'flowchart TD; A-->B'    # inline code
#
# Exit 0 = renders cleanly, 1 = render failure or error-placeholder SVG,
# 2 = bad input (missing file, empty diagram), 3 = no usable Mermaid CLI 12.0.0.
#
# CLI selection: an `mmdc` on PATH is used only when `mmdc --version` prints 12.0.0.
# Otherwise `npx -y ${MERMAID_CLI_PACKAGE}` (default @mermaid-js/mermaid-cli@12.0.0).
# Keep the pin in sync with .github/workflows/tests.yml.
#
# Optional: set MERMAID_PUPPETEER_CONFIG to a puppeteer JSON config path (e.g.
# {"args": ["--no-sandbox"]}) when the host can't grant Chromium a sandbox — some CI runners
# (e.g. GitHub Actions' ubuntu-latest, whose AppArmor policy blocks unprivileged user
# namespaces) need this. Unset by default; local/interactive use is unaffected.
#
# Compatible with bash 3.2 (macOS /bin/bash): no associative arrays, no mapfile, and no
# expansion of a possibly-empty array under `set -u`.
set -euo pipefail

REQUIRED_CLI_VERSION="12.0.0"
MERMAID_CLI_PACKAGE="${MERMAID_CLI_PACKAGE:-@mermaid-js/mermaid-cli@${REQUIRED_CLI_VERSION}}"

OUT=""; INPUT=""; CODE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) OUT="${2:-}"; shift 2;;
    -c) CODE="${2:-}"; shift 2;;
    -h|--help) sed -n '2,15p' "$0"; exit 0;;
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

# Select the CLI. A different mmdc version is never used: its verdict could differ.
if command -v mmdc >/dev/null 2>&1 \
  && [ "$(mmdc --version 2>/dev/null | tr -d '[:space:]')" = "${REQUIRED_CLI_VERSION}" ]; then
  RUN=(mmdc)
elif command -v npx >/dev/null 2>&1; then
  echo "note: no mmdc ${REQUIRED_CLI_VERSION} on PATH; using 'npx -y ${MERMAID_CLI_PACKAGE}' (first run downloads it)." >&2
  RUN=(npx -y "${MERMAID_CLI_PACKAGE}")
else
  echo "ERROR: need Mermaid CLI ${REQUIRED_CLI_VERSION} (mmdc ${REQUIRED_CLI_VERSION} or npx on PATH)."
  echo "Install once with: npm install -g @mermaid-js/mermaid-cli@${REQUIRED_CLI_VERSION}"
  exit 3
fi

VALIDATION_DEST="${TMPDIR_LOCAL}/validation.svg"
ERRLOG="${TMPDIR_LOCAL}/err.log"

# run_mmdc INPUT OUTPUT
run_mmdc() {
  if [ -n "${MERMAID_PUPPETEER_CONFIG:-}" ]; then
    "${RUN[@]}" -i "$1" -o "$2" -p "${MERMAID_PUPPETEER_CONFIG}"
  else
    "${RUN[@]}" -i "$1" -o "$2"
  fi
}

# Print a CLI log with the temp directory redacted, so output is stable across runs.
show_log() {
  echo "----- mermaid-cli output -----"
  sed "s#${TMPDIR_LOCAL}#<tmp>#g" "$1"
  echo "------------------------------"
}

is_error_svg() {
  grep -Eiq 'aria-roledescription="error"|class="error-icon"|>Syntax error in text<' "$1"
}

# Mermaid strips YAML frontmatter before parsing, so its line numbers count from the
# first line after the closing `---`. Print how many source lines the frontmatter uses.
frontmatter_lines() {
  awk 'NR == 1 { if ($0 !~ /^---[ \t]*$/) { print 0; exit } ; next }
       /^---[ \t]*$/ { print NR; exit }' "$1" | head -n 1
}

# Print the line number in a CLI log (`on line N`, else `line N`), or nothing.
cli_line() {
  local n
  n="$(sed -n -E 's/.*on line ([0-9]+).*/\1/p' "$1" | head -n 1)"
  [ -n "${n}" ] || n="$(sed -n -E 's/.*[Ll]ine:? ([0-9]+).*/\1/p' "$1" | head -n 1)"
  printf '%s' "${n}"
}

# Print the first CLI error line: the first line naming an error, else the first
# non-empty line that is not a progress message.
cli_message() {
  local msg
  msg="$(grep -m 1 -iE 'error' "$1" || true)"
  [ -n "${msg}" ] || msg="$(grep -m 1 -vE '^[[:space:]]*$|^Generating |^Found [0-9]+ mermaid' "$1" || true)"
  printf '%s' "${msg}" | sed "s#${TMPDIR_LOCAL}#<tmp>#g"
}

# Print the source line number (in SOURCE) that a CLI log points at, or nothing.
source_line() {
  local n fm
  n="$(cli_line "$2")"
  [ -n "${n}" ] || return 0
  fm="$(frontmatter_lines "$1")"
  printf '%s' "$((n + ${fm:-0}))"
}

if ! run_mmdc "${SRC}" "${VALIDATION_DEST}" >"${ERRLOG}" 2>&1; then
  LINE="$(source_line "${SRC}" "${ERRLOG}")"
  if [ -n "${LINE}" ]; then
    echo "FAIL line ${LINE}: $(sed -n "${LINE}p" "${SRC}")"
  else
    echo "FAIL line unknown: $(cli_message "${ERRLOG}")"
  fi
  show_log "${ERRLOG}"
  exit 1
fi

# Mermaid CLI can exit 0 while writing its syntax-error placeholder SVG. Inspect
# the artifact itself so an error image is never reported as a successful render.
if is_error_svg "${VALIDATION_DEST}"; then
  echo "FAIL line unknown: Mermaid emitted an error SVG despite returning exit 0."
  show_log "${ERRLOG}"
  exit 1
fi

if [ -n "${OUT}" ]; then
  case "${OUT}" in
    *.svg) cp "${VALIDATION_DEST}" "${OUT}" ;;
    *)
      if ! run_mmdc "${SRC}" "${OUT}" >"${ERRLOG}" 2>&1; then
        echo "FAIL: Mermaid validated as SVG but could not write ${OUT}."
        show_log "${ERRLOG}"
        exit 1
      fi
      ;;
  esac
fi

echo "PASS: diagram renders cleanly."
[ -n "${OUT}" ] && echo "Wrote ${OUT}"
exit 0
