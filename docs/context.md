# Context Command

`aegis-code context` manages deterministic, project-local context under `.aegis/context/`.

Commands:

- `aegis-code context refresh`
- `aegis-code context show`

## Refresh

`aegis-code context refresh` creates/updates:

- `.aegis/context/project_summary.md`
- `.aegis/context/architecture.md`
- `.aegis/context/constraints.md`

Behavior:

- Local only and deterministic.
- No provider calls, no Aegis backend calls, no network.
- Reads selective inputs:
  - `README.md` (if present)
  - `pyproject.toml` (if present)
  - `package.json` (if present)
  - `docs/**/*.md` (if present)
- `docs/` scanning limits:
  - markdown files only
  - skip files over 100KB
  - read at most first 250 lines per file
  - skip hidden directories

## Show

`aegis-code context show` prints:

- whether context exists
- generated context file paths
- compact preview lines

If context is missing:

- `No project context found. Run \`aegis-code context refresh\`.`

## Runtime usage

When runtime commands are executed (`aegis-code "<task>"`, `aegis-code fix`, create validation stabilization path), Aegis Code loads project context if present:

- inclusion order: `project_summary`, `constraints`, `architecture`
- capped to a combined runtime budget (default 6000 chars)
- includes truncation marker when capped
- passes compact metadata (`available`, `included_paths`, `total_chars`) into reports

Budget guardrails still apply before runtime calls.

## Purpose

This context is designed as a small, structured local signal for runtime control and project awareness.
