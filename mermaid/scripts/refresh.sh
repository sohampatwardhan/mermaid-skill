#!/usr/bin/env bash
# Refresh the skill's cached Mermaid syntax pages from one pinned mermaid-js/mermaid tag.
#
# Regenerates:
#   reference/diagram-types.md   — shipped diagram implementations at the tag
#   reference/syntax/<type>.md   — upstream per-type syntax docs (offline copy)
#
# MERMAID_REF selects the tag (default mermaid@12.0.0, the version check.sh validates with).
# Every download goes to a temp directory first. The cache is replaced only after every
# fetch succeeded; any failure exits 1 and leaves the existing cache untouched.
set -euo pipefail

MERMAID_REF="${MERMAID_REF:-mermaid@12.0.0}"
MERMAID_VERSION="${MERMAID_REF#mermaid@}"

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${SKILL_DIR}/reference/diagram-types.md"
SYNTAX_DIR="${SKILL_DIR}/reference/syntax"
API="https://api.github.com/repos/mermaid-js/mermaid"
DIAGRAMS_PATH="packages/mermaid/src/diagrams"
DOCS_PATH="packages/mermaid/src/docs/syntax"
REF_QS="ref=$(printf '%s' "${MERMAID_REF}" | sed 's/@/%40/g')"
RAW="https://raw.githubusercontent.com/mermaid-js/mermaid/$(printf '%s' "${MERMAID_REF}" | sed 's/@/%40/g')"

AUTH=()
[ -n "${GITHUB_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
[ -z "${GITHUB_TOKEN:-}" ] && [ -n "${GH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${GH_TOKEN}")

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 required"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

fail() { echo "ERROR: $*. Nothing updated."; exit 1; }

# gh_get URL FILE
gh_get() { curl -fsSL ${AUTH[@]+"${AUTH[@]}"} "$1" -o "$2" 2>/dev/null; }

# json_names FILE TYPE: names of entries with .type == TYPE, sorted.
json_names() {
  python3 -c 'import json,sys; print("\n".join(sorted(e["name"] for e in json.load(open(sys.argv[1])) if e["type"] == sys.argv[2])))' "$1" "$2"
}

# ---------------------------------------------------------------------------
# 1. Type list: directory names under src/diagrams at the tag.
# ---------------------------------------------------------------------------
echo "Fetching diagram list from ${DIAGRAMS_PATH} at ${MERMAID_REF}..."
gh_get "${API}/contents/${DIAGRAMS_PATH}?${REF_QS}" "${WORK}/dirs.json" || fail "could not list ${DIAGRAMS_PATH}"
TYPES="$(json_names "${WORK}/dirs.json" dir)" || fail "could not parse the diagram list"
[ -n "${TYPES}" ] || fail "empty diagram list"

# Not authorable diagrams: shared helpers, and the renderer Mermaid uses for syntax errors.
SKIP_TYPES='^(common|error)$'
{
  echo "# Mermaid diagram types (auto-generated)"
  echo
  echo "> cached against Mermaid ${MERMAID_VERSION} (tag \`${MERMAID_REF}\` of mermaid-js/mermaid)."
  echo "> Source of truth: \`${DIAGRAMS_PATH}\`. Regenerate with \`scripts/refresh.sh\`."
  echo "> \`common\` and \`error\` are omitted: shared code and the syntax-error renderer."
  echo "> Per-type catalog files are \`reference/catalog/<type>.md\`; builders are in \`reference/coverage.md\`."
  echo
  echo "## Shipped diagram implementations"
  echo
  echo "The opening keyword may differ from the directory name (e.g."
  echo "\`flowchart\`/\`graph\`, \`stateDiagram-v2\`, \`architecture-beta\`)."
  echo
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    printf '%s\n' "$t" | grep -Eq "${SKIP_TYPES}" && continue
    echo "- \`$t\`"
  done <<< "${TYPES}"
} > "${WORK}/diagram-types.md"

# ---------------------------------------------------------------------------
# 2. Offline copy of the per-type syntax docs at the tag.
# ---------------------------------------------------------------------------
echo "Fetching syntax docs from ${DOCS_PATH} at ${MERMAID_REF}..."
gh_get "${API}/contents/${DOCS_PATH}?${REF_QS}" "${WORK}/docs.json" || fail "could not list ${DOCS_PATH}"
NAMES="$(json_names "${WORK}/docs.json" file | grep '\.md$' || true)"
[ -n "${NAMES}" ] || fail "no syntax docs listed"

mkdir "${WORK}/syntax"
COUNT=0
while IFS= read -r name; do
  [ -n "${name}" ] || continue
  curl -fsSL "${RAW}/${DOCS_PATH}/${name}" -o "${WORK}/syntax/${name}" 2>/dev/null \
    || fail "could not fetch ${name} at ${MERMAID_REF}"
  COUNT=$((COUNT + 1))
done <<< "${NAMES}"

{
  echo "# Cached Mermaid syntax docs"
  echo
  echo "cached against Mermaid ${MERMAID_VERSION}: tag \`${MERMAID_REF}\` of mermaid-js/mermaid, \`${DOCS_PATH}\`."
  echo "Regenerate with \`scripts/refresh.sh\`. One upstream page per diagram type."
  echo "Agents load \`../catalog/<type>.md\` first; open a page here only for upstream detail."
  echo "Which types have an IR builder is \`../coverage.md\`."
} > "${WORK}/syntax/README.md"

# ---------------------------------------------------------------------------
# 3. Every fetch succeeded: replace the cache.
# ---------------------------------------------------------------------------
rm -rf "${SYNTAX_DIR}.old"
[ -d "${SYNTAX_DIR}" ] && mv "${SYNTAX_DIR}" "${SYNTAX_DIR}.old"
mv "${WORK}/syntax" "${SYNTAX_DIR}"
rm -rf "${SYNTAX_DIR}.old"
cp "${WORK}/diagram-types.md" "${OUT}"

echo "Cached ${COUNT} syntax docs into ${SYNTAX_DIR} and wrote ${OUT}."
echo "Types:"
printf '%s\n' "${TYPES}" | grep -Ev "${SKIP_TYPES}" | sed 's/^/  - /'
