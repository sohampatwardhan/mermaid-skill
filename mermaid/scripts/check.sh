#!/usr/bin/env bash
# Validate Mermaid diagrams by PARSING them with the pinned Mermaid 12.0.0 (no render, no
# browser, no MCP server). A diagram is valid when mermaid.parse() accepts it; a parse error
# is reported with the parser's own line number and message.
#
# Usage:
#   check.sh diagram.mmd                 # validate one .mmd file
#   cat diagram.mmd | check.sh           # read from stdin
#   check.sh -c 'flowchart TD; A-->B'    # inline code
#   check.sh --markdown A.md [B.md ...]  # validate every ```mermaid fence, report PATH:LINE
#
# Exit 0 = parses cleanly, 1 = parse failure, 2 = bad input (missing file, empty diagram),
# 3 = no usable Mermaid 12.0.0 parser (Node 22+ with mermaid@12.0.0 and jsdom).
#
# Parser: scripts/mermaid-parse.mjs loads mermaid@12.0.0 once and parses the whole batch in one
# Node process. The pinned mermaid and jsdom are resolved from MERMAID_PARSE_NODE_MODULES when
# set (a node_modules directory holding both at the pin); otherwise check.sh installs the pin
# once into a cache dir (MERMAID_PARSE_CACHE, default under the system temp) with npm. Keep the
# pin in sync with .github/workflows/tests.yml.
#
# Optional: set MERMAID_CHECK_TIMEOUT to the per-diagram parse bound in seconds (default 120).
# The whole-batch Node process gets this bound times the number of diagrams, so a healthy large
# batch is never killed for its size while a wedged process is still bounded. A parse that
# outlives its budget is reported as a failure naming "timeout" — never a pass. The bound is
# portable (GNU/BSD `timeout`, else a perl or python3 watchdog). Set 0 to disable it.
#
# Compatible with bash 3.2 (macOS /bin/bash): no associative arrays, no mapfile, and no
# expansion of a possibly-empty array under `set -u`.
set -euo pipefail

REQUIRED_MERMAID_VERSION="12.0.0"
MERMAID_PARSE_PACKAGE="${MERMAID_PARSE_PACKAGE:-mermaid@${REQUIRED_MERMAID_VERSION}}"
JSDOM_PACKAGE="${JSDOM_PACKAGE:-jsdom}"
# zenuml is an external diagram the catalog documents; the parser registers it so a zenuml
# fence validates. It is optional: without it a zenuml diagram reports a parse failure.
ZENUML_PACKAGE="${ZENUML_PACKAGE:-@mermaid-js/mermaid-zenuml@1.0.1}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARSER="${SCRIPT_DIR}/mermaid-parse.mjs"

OUT=""; INPUT=""; CODE=""; MARKDOWN=0
MD_FILES="" # newline-separated; bash 3.2 has no safe empty arrays under set -u
while [ $# -gt 0 ]; do
  case "$1" in
    -o) OUT="${2:-}"; shift 2;;
    -c) CODE="${2:-}"; shift 2;;
    --markdown) MARKDOWN=1; shift;;
    -h|--help) sed -n '2,14p' "$0"; exit 0;;
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

if [ -n "${OUT}" ]; then
  echo "note: check.sh validates by parsing and does not produce images; -o is ignored. Use a" >&2
  echo "      separate render tool (a host Mermaid render tool, or render.py then your renderer)." >&2
fi

TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_LOCAL}"' EXIT

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

# --- parser dependencies ------------------------------------------------------------------

command -v node >/dev/null 2>&1 || {
  echo "ERROR: need Node.js 22+ to run the pinned Mermaid ${REQUIRED_MERMAID_VERSION} parser."
  exit 3
}

# node_modules holding mermaid@12.0.0 and jsdom. Honour a caller-provided one (CI points this
# at its pinned install); otherwise install the pin once into a cache dir and reuse it.
resolve_node_modules() {
  if [ -n "${MERMAID_PARSE_NODE_MODULES:-}" ]; then
    if [ -d "${MERMAID_PARSE_NODE_MODULES}/mermaid" ] && [ -d "${MERMAID_PARSE_NODE_MODULES}/jsdom" ]; then
      printf '%s' "${MERMAID_PARSE_NODE_MODULES}"
      return 0
    fi
    echo "ERROR: MERMAID_PARSE_NODE_MODULES=${MERMAID_PARSE_NODE_MODULES} lacks mermaid or jsdom." >&2
    return 1
  fi
  local cache="${MERMAID_PARSE_CACHE:-${TMPDIR:-/tmp}/mermaid-parse-${REQUIRED_MERMAID_VERSION}}"
  local modules="${cache}/node_modules"
  if [ -d "${modules}/mermaid" ] && [ -d "${modules}/jsdom" ]; then
    printf '%s' "${modules}"
    return 0
  fi
  command -v npm >/dev/null 2>&1 || {
    echo "ERROR: need npm to install the pinned Mermaid ${REQUIRED_MERMAID_VERSION} parser (set" >&2
    echo "       MERMAID_PARSE_NODE_MODULES to a node_modules that already has mermaid and jsdom)." >&2
    return 1
  }
  echo "note: installing ${MERMAID_PARSE_PACKAGE}, ${JSDOM_PACKAGE}, and ${ZENUML_PACKAGE} into ${cache} (first run only)." >&2
  mkdir -p "${cache}"
  ( cd "${cache}" \
      && { [ -f package.json ] || npm init -y >/dev/null 2>&1; } \
      && npm install --no-fund --no-audit --save-exact "${MERMAID_PARSE_PACKAGE}" "${JSDOM_PACKAGE}" "${ZENUML_PACKAGE}" >/dev/null 2>&1 ) || {
    echo "ERROR: could not install the pinned Mermaid ${REQUIRED_MERMAID_VERSION} parser." >&2
    return 1
  }
  printf '%s' "${modules}"
}

NODE_MODULES="$(resolve_node_modules)" || exit 3

# Verify the pin: a different mermaid version is never used, its verdict could differ.
INSTALLED_VERSION="$(node -e "try{process.stdout.write(require('${NODE_MODULES}/mermaid/package.json').version)}catch(e){}" 2>/dev/null || true)"
if [ "${INSTALLED_VERSION}" != "${REQUIRED_MERMAID_VERSION}" ]; then
  echo "ERROR: need Mermaid ${REQUIRED_MERMAID_VERSION}; found '${INSTALLED_VERSION:-none}' in ${NODE_MODULES}."
  exit 3
fi

export MERMAID_PARSE_NODE_MODULES="${NODE_MODULES}"

# --- whole-batch parse bound --------------------------------------------------------------

# Per-diagram wall-clock bound (seconds). The whole-batch Node process gets this bound times the
# number of diagrams, so a large but healthy batch is never killed for being large while a
# wedged process is still bounded. A parse that outlives its budget is a failure, never a pass.
MERMAID_CHECK_TIMEOUT="${MERMAID_CHECK_TIMEOUT:-120}"

# run_with_timeout SECONDS CMD...: run CMD under a wall-clock bound, portable across macOS and
# Linux. Prefer GNU/BSD `timeout` (or `gtimeout`); otherwise fall back to a perl or python3
# SIGALRM watchdog. Exit 124 means the bound was hit (the convention GNU `timeout` uses); any
# other code is CMD's own. With no usable timer, run CMD unbounded rather than refuse to parse.
run_with_timeout() {
  local secs="$1"; shift
  if [ "${secs}" -le 0 ] 2>/dev/null; then
    "$@"
    return $?
  fi
  if command -v timeout >/dev/null 2>&1; then
    timeout -k 5 "${secs}" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout -k 5 "${secs}" "$@"
  elif command -v perl >/dev/null 2>&1; then
    perl -e '
      my $t = shift;
      my $pid = fork();
      die "fork: $!" unless defined $pid;
      if ($pid == 0) { exec @ARGV or exit 127; }
      $SIG{ALRM} = sub { kill "TERM", $pid; sleep 5; kill "KILL", $pid; waitpid($pid, 0); exit 124; };
      alarm $t;
      waitpid($pid, 0);
      my $code = $?;
      exit($code & 127 ? 128 + ($code & 127) : $code >> 8);
    ' "${secs}" "$@"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c '
import subprocess, sys
secs = int(sys.argv[1])
try:
    sys.exit(subprocess.run(sys.argv[2:], timeout=secs).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
' "${secs}" "$@"
  else
    "$@"
  fi
}

# parse_batch BATCH_JSON RESULTS_OUT [DIAGRAM_COUNT]: run the parser once over a JSON batch under
# a wall-clock bound of MERMAID_CHECK_TIMEOUT seconds *per diagram* (count defaults to 1), so a
# healthy large batch gets proportional time while a wedged process is still bounded. Writes the
# parser's line-based results to RESULTS_OUT. Returns the parser exit (0 all pass, 1 any failed,
# 2 bad batch/deps), or synthesises a timeout failure (exit 1, a BATCHERROR line) on the bound.
# The parser's output is shell-readable, so no second Node process is needed.
parse_batch() {
  local batch="$1" out="$2" count="${3:-1}" status=0 budget
  if [ "${MERMAID_CHECK_TIMEOUT}" -le 0 ] 2>/dev/null; then
    budget=0
  else
    budget=$((MERMAID_CHECK_TIMEOUT * count))
  fi
  run_with_timeout "${budget}" node "${PARSER}" <"${batch}" >"${out}" 2>"${TMPDIR_LOCAL}/parser.err" || status=$?
  if [ "${status}" = 124 ]; then
    printf 'BATCHERROR parse timeout after %ss (%ss x %s, MERMAID_CHECK_TIMEOUT)\n' \
      "${budget}" "${MERMAID_CHECK_TIMEOUT}" "${count}" >"${out}"
    return 1
  fi
  return "${status}"
}

# --- line-based result helpers (pure shell, no second Node) -------------------------------

# batch_error RESULTS: print a BATCHERROR message (dependency/bad-batch/timeout), or nothing.
batch_error() {
  sed -n 's/^BATCHERROR //p' "$1" | head -n 1
}

# result_ok RESULTS ID: print "true" when diagram ID parsed, else "false".
result_ok() {
  if grep -q "^OK $2\$" "$1"; then printf 'true'; else printf 'false'; fi
}

# result_line RESULTS ID: print the parser line for a failed diagram ID (empty when none).
result_line() {
  local f
  f="$(grep -m1 "^FAIL $2 " "$1" || true)"
  [ -n "${f}" ] || return 0
  # FAIL <id> <line|-> <message...>
  f="${f#FAIL $2 }"
  f="${f%% *}"
  [ "${f}" = "-" ] || printf '%s' "${f}"
}

# result_message RESULTS ID: print the parser message for a failed diagram ID.
result_message() {
  local f
  f="$(grep -m1 "^FAIL $2 " "$1" || true)"
  [ -n "${f}" ] || return 0
  f="${f#FAIL $2 }"      # strip "FAIL <id> "
  printf '%s' "${f#* }"  # strip the line token, leaving the message
}

# --- batch assembly: a diagram is one JSON record {id, source} ----------------------------
#
# A JSON string is built with python3 when present (robust), else a portable sed/awk escaper.
json_string() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys; sys.stdout.write(json.dumps(sys.stdin.read()))' <"$1"
  else
    # Escape backslash, double quote, and control characters for a JSON string.
    awk 'BEGIN{ printf "\"" }
         { gsub(/\\/,"\\\\"); gsub(/"/,"\\\""); gsub(/\t/,"\\t"); gsub(/\r/,"\\r");
           if (NR>1) printf "\\n"; printf "%s", $0 }
         END{ printf "\"" }' "$1"
  fi
}

# --- Markdown mode ------------------------------------------------------------------------

# Mermaid strips YAML frontmatter before parsing, so its line numbers count from the first
# line after the closing `---`. Print how many source lines a fence's frontmatter uses.
frontmatter_lines() {
  awk 'NR == 1 { if ($0 !~ /^---[ \t]*$/) { print 0; exit } ; next }
       /^---[ \t]*$/ { print NR; exit }' "$1" | head -n 1
}

# check_markdown FILE: validate every column-0 ```mermaid fence. Returns 1 on any failure.
check_markdown() {
  local md="$1" work count i start status line fence ok msg fm
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

  # Build one batch with a record per fence, parse it in a single Node process.
  {
    printf '{"diagrams":['
    i=1
    while [ "${i}" -le "${count}" ]; do
      [ "${i}" = 1 ] || printf ','
      printf '{"id":%s,"source":%s}' "${i}" "$(json_string "${work}/fence-${i}.mmd")"
      i=$((i + 1))
    done
    printf ']}\n'
  } > "${work}/batch.json"

  parse_batch "${work}/batch.json" "${work}/results.txt" "${count}" || true
  local berr
  berr="$(batch_error "${work}/results.txt")"
  if [ -n "${berr}" ]; then
    echo "${md}: parser error: ${berr}"
    return 1
  fi

  status=0
  i=1
  while [ "${i}" -le "${count}" ]; do
    ok="$(result_ok "${work}/results.txt" "${i}")"
    if [ "${ok}" != "true" ]; then
      status=1
      start="$(sed -n "${i}p" "${work}/starts")"
      fence="${work}/fence-${i}.mmd"
      line="$(result_line "${work}/results.txt" "${i}")"
      msg="$(result_message "${work}/results.txt" "${i}")"
      if [ -n "${line}" ]; then
        fm="$(frontmatter_lines "${fence}")"
        echo "${md}:$((start + line - 1 + ${fm:-0})): ${msg}"
        echo "    $(sed -n "$((line + ${fm:-0}))p" "${fence}")"
      else
        echo "${md}:${start}: line unknown: ${msg}"
      fi
    fi
    i=$((i + 1))
  done
  if [ "${status}" = 0 ]; then
    echo "PASS ${md} (${count} fences)"
    return 0
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

RESULTS="${TMPDIR_LOCAL}/results.txt"
printf '{"diagrams":[{"id":0,"source":%s}]}\n' "$(json_string "${SRC}")" > "${TMPDIR_LOCAL}/batch.json"

parse_batch "${TMPDIR_LOCAL}/batch.json" "${RESULTS}" || true
BERR="$(batch_error "${RESULTS}")"
if [ -n "${BERR}" ]; then
  echo "FAIL line unknown: ${BERR}"
  exit 1
fi

OK="$(result_ok "${RESULTS}" 0)"
if [ "${OK}" = "true" ]; then
  echo "PASS: diagram parses cleanly."
  exit 0
fi

LINE="$(result_line "${RESULTS}" 0)"
MSG="$(result_message "${RESULTS}" 0)"
FM="$(frontmatter_lines "${SRC}")"
if [ -n "${LINE}" ]; then
  SRCLINE="$((LINE + ${FM:-0}))"
  echo "FAIL line ${SRCLINE}: $(sed -n "${SRCLINE}p" "${SRC}")"
  echo "${MSG}"
else
  echo "FAIL line unknown: ${MSG}"
fi
exit 1
