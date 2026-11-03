# Mermaid Skill

An [Agent Skills](https://agentskills.io/specification)-compatible skill for authoring,
validating, and deterministically generating [Mermaid](https://mermaid.js.org/) diagrams. Built
for Claude Code, and portable to any tool that reads the open `SKILL.md` format. The skill is
named `mermaid`; [`mermaid/SKILL.md`](mermaid/SKILL.md) is a lean index that points at one
catalog file per diagram type.

- **One catalog file per type.** Every open-source Mermaid 12.0.0 diagram type has a file under
  `mermaid/reference/catalog/` with its syntax, every feature, config and theming, traps, and a
  complete worked example. An agent picks a type from the index and loads only that file. The
  cached upstream pages stay in `mermaid/reference/syntax/`, pinned to the `mermaid@12.0.0` tag.
- **Never presented unverified.** Every diagram is render-validated with `scripts/check.sh`,
  which pins Mermaid CLI 12.0.0, reports the failing line, and rejects Mermaid's silent
  error-placeholder SVG. CI runs it on every example in every catalog file.
- **Optional, reliable generation from structured data.** When a diagram's content is already
  structured data, `mermaid/scripts/render.py` generates the exact Mermaid source from a small
  JSON intermediate representation (IR) — see [`mermaid/reference/ir.md`](mermaid/reference/ir.md).
  A type keeps a builder only where it is 100% reliable: accepted IR always renders, and anything
  it cannot represent is rejected with a JSON path rather than guessed. The checked matrix of
  every type, its keywords, its builder, and its tests is
  [`mermaid/reference/coverage.md`](mermaid/reference/coverage.md).

## Install

### With the `skills` CLI

Install with the [`skills` CLI](https://github.com/vercel-labs/skills) (Node.js 22.20 or later). It records the source, so `npx skills update` keeps the skill current:

```bash
# Global install for every agent the CLI detects
npx skills add sohampatwardhan/mermaid-skill -g

# Or only for chosen agents
npx skills add sohampatwardhan/mermaid-skill -g -a claude-code -a codex

# Update later
npx skills update -g
```

### By hand

The [`mermaid/`](mermaid/) folder in this repository *is* the Agent Skill package — copy it
as-is into your tool's Agent Skills directory (e.g. `~/.claude/skills/mermaid/`,
`~/.agents/skills/mermaid/` — see the [Agent Skills spec](https://agentskills.io/specification)
for every supported tool's path). Nothing outside `mermaid/` (this README, the license, CI) is
part of the installed skill.

## Testing

```bash
cd mermaid && python3 -m pytest tests/ -q
```

The builder tests render every fixture and text-corpus case through `scripts/check.sh` (an
`mmdc` 12.0.0, otherwise `npx -y @mermaid-js/mermaid-cli@12.0.0`), and `check.sh --markdown`
validates every example in every catalog file — not just string matches. GitHub Actions installs
that same pin on Node 22. Mermaid 11 does not register `agentflow-beta`.

## License

MIT — see [LICENSE](LICENSE).
