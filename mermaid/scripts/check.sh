#!/usr/bin/env bash
# Validate Mermaid diagrams locally with Mermaid CLI 12.0.0 (no MCP server needed).
#
# Usage:
#   check.sh diagram.mmd                 # validate (render to a temp SVG, discard)
#   check.sh diagram.mmd -o out.svg      # validate AND keep the rendered SVG/PNG/PDF
#   cat diagram.mmd | check.sh           # read from stdin
#   check.sh -c 'flowchart TD; A-->B'    # inline code
#   check.sh --markdown A.md [B.md ...]  # validate every ```mermaid fence, report PATH:LINE
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

OUT=""; INPUT=""; CODE=""; MARKDOWN=0
MD_FILES="" # newline-separated; bash 3.2 has no safe empty arrays under set -u
while [ $# -gt 0 ]; do
  case "$1" in
    -o) OUT="${2:-}"; shift 2;;
    -c) CODE="${2:-}"; shift 2;;
    --markdown) MARKDOWN=1; shift;;
    -h|--help) sed -n '2,16p' "$0"; exit 0;;
    *)
      if [ "${MARKDOWN}" = 1 ]; then
        MD_FILES="${MD_FILES}$1
"
      else
        INPUT="$1"
      fi
      shift;;
  esac
done

TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_LOCAL}"' EXIT
ERRLOG="${TMPDIR_LOCAL}/err.log"

# --- input --------------------------------------------------------------------------------

SRC="${TMPDIR_LOCAL}/in.mmd"
if [ "${MARKDOWN}" = 1 ]; then
  [ -n "${MD_FILES}" ] || { echo "ERROR: --markdown needs at least one file."; exit 2; }
  while IFS= read -r md; do
    [ -n "${md}" ] || continue
    [ -f "${md}" ] || { echo "ERROR: file not found: ${md}"; exit 2; }
  done <<EOF
${MD_FILES}
EOF
elif [ -n "${CODE}" ]; then
  printf '%s\n' "${CODE}" > "${SRC}"
elif [ -n "${INPUT}" ]; then
  [ -f "${INPUT}" ] || { echo "ERROR: file not found: ${INPUT}"; exit 2; }
  cp "${INPUT}" "${SRC}"
elif [ ! -t 0 ]; then
  cat > "${SRC}"
else
  echo "ERROR: no input. Pass a file, -c '<code>', or pipe via stdin. (-h for help)"; exit 2
fi

if [ "${MARKDOWN}" = 0 ]; then
  [ -s "${SRC}" ] || { echo "ERROR: empty diagram."; exit 2; }
fi

# --- CLI selection ------------------------------------------------------------------------

# A different mmdc version is never used: its verdict could differ from the pinned one.
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

# run_mmdc INPUT OUTPUT
run_mmdc() {
  if [ -n "${MERMAID_PUPPETEER_CONFIG:-}" ]; then
    "${RUN[@]}" -i "$1" -o "$2" -p "${MERMAID_PUPPETEER_CONFIG}"
  else
    "${RUN[@]}" -i "$1" -o "$2"
  fi
}

# --- diagnostics --------------------------------------------------------------------------

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

# source_line SOURCE LOG: the SOURCE line number the CLI log points at, or nothing.
source_line() {
  local n fm
  n="$(cli_line "$2")"
  [ -n "${n}" ] || return 0
  fm="$(frontmatter_lines "$1")"
  printf '%s' "$((n + ${fm:-0}))"
}

# --- Markdown mode ------------------------------------------------------------------------

# check_markdown FILE: validate every column-0 ```mermaid fence. Returns 1 on any failure.
check_markdown() {
  local md="$1" work count i start status line fence svg
  work="$(mktemp -d "${TMPDIR_LOCAL}/md.XXXXXX")"
  # Extract fences and the Markdown line of each fence's first content line.
  awk -v dir="${work}" '
    infence == 0 && $0 ~ /^```mermaid[ \t]*$/ {
      n++; infence = 1; file = dir "/fence-" n ".mmd"; printf "" > file
      print NR + 1 > (dir "/starts"); next
    }
    infence == 1 && $0 ~ /^```[ \t]*$/ { infence = 0; close(file); next }
    infence == 1 { print > file }
    END { print n + 0 > (dir "/count") }
  ' "${md}"
  count="$(cat "${work}/count")"
  if [ "${count}" = 0 ]; then
    echo "${md}: no mermaid fences"
    return 0
  fi

  # Fast path: one CLI run renders every fence (CLI 12.0.0 writes out-1.svg .. out-N.svg).
  : > "${work}/batch.md"
  i=1
  while [ "${i}" -le "${count}" ]; do
    { printf '```mermaid\n'; cat "${work}/fence-${i}.mmd"; printf '```\n\n'; } >> "${work}/batch.md"
    i=$((i + 1))
  done
  mkdir "${work}/out"
  status=0
  if run_mmdc "${work}/batch.md" "${work}/out/out.md" >"${work}/batch.log" 2>&1; then
    i=1
    while [ "${i}" -le "${count}" ]; do
      svg="${work}/out/out-${i}.svg"
      if [ ! -f "${svg}" ] || is_error_svg "${svg}"; then status=1; fi
      i=$((i + 1))
    done
  else
    status=1
  fi
  if [ "${status}" = 0 ]; then
    echo "PASS ${md} (${count} fences)"
    return 0
  fi

  # Slow path: render each fence alone to locate every failure.
  status=0
  i=1
  while [ "${i}" -le "${count}" ]; do
    fence="${work}/fence-${i}.mmd"
    start="$(sed -n "${i}p" "${work}/starts")"
    svg="${work}/fence-${i}.svg"
    if ! run_mmdc "${fence}" "${svg}" >"${ERRLOG}" 2>&1; then
      status=1
      line="$(source_line "${fence}" "${ERRLOG}")"
      if [ -n "${line}" ]; then
        echo "${md}:$((start + line - 1)): $(cli_message "${ERRLOG}")"
        echo "    $(sed -n "${line}p" "${fence}")"
      else
        echo "${md}:${start}: line unknown: $(cli_message "${ERRLOG}")"
      fi
    elif is_error_svg "${svg}"; then
      status=1
      echo "${md}:${start}: line unknown: Mermaid emitted an error SVG despite returning exit 0."
    fi
    i=$((i + 1))
  done
  if [ "${status}" = 0 ]; then
    # Every fence passes alone; the batch failure came from the batch run itself.
    echo "${md}: batch render failed although every fence renders alone"
    show_log "${work}/batch.log"
    return 1
  fi
  return 1
}

if [ "${MARKDOWN}" = 1 ]; then
  FAILED=0
  while IFS= read -r md; do
    [ -n "${md}" ] || continue
    check_markdown "${md}" || FAILED=1
  done <<EOF
${MD_FILES}
EOF
  exit "${FAILED}"
fi

# --- single diagram -----------------------------------------------------------------------

VALIDATION_DEST="${TMPDIR_LOCAL}/validation.svg"

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
