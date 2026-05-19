# CLI Architecture (Target Information Architecture)

## 1. Purpose

This document defines the long-term command-surface architecture for Aegis Code.

Goals:

- keep the CLI easy to explain
- keep the primary user flow minimal
- separate public workflow commands from advanced/internal commands
- reduce conceptual overlap between commands
- create a stable base for future API/server/agent integration

This is a product architecture target. It does not imply immediate command behavior changes.

Current implementation status (Phase 3E):

- `aegis-code config ...` is now available as the preferred namespace for provider/budget/keys.
- Top-level `provider`, `budget`, and `keys` remain supported as compatibility aliases.
- `aegis-code setup` is the canonical onboarding/initialization command.
- `aegis-code init` and `aegis-code onboard` remain available as compatibility/direct commands.
- Inspection/diagnostics commands are retained with explicit roles: `status`, `report`, `doctor`, `overview`, `probe`, `next`, `usage`.
- Top-level help and command docs now classify commands into: daily workflow, project/workspace, advanced/admin specialized tools, and compatibility aliases.

## 2. Product Mental Model

Primary workflow:

1. setup
2. patch / fix / batch
3. diff
4. apply
5. report
6. status
7. configure provider/budget/keys
8. workspace management (optional, multi-repo)

Operational model:

- proposal-first patching
- explicit confirmation for mutation
- deterministic local safety checks
- inspectability via run artifacts and reports

## 3. Public Command Set (Target)

Stable public commands:

- `setup`
- `patch`
- `fix`
- `diff`
- `apply`
- `report`
- `status`
- `config`
- `workspace`
- `scaffold` (preferred long-term name)

Notes:

- `scaffold` is preferred over `create` for clearer intent.
- batch stays part of patch flow (`patch --operation batch --batch-file ...`) unless a future explicit `patch batch` subcommand is introduced.

## 4. Advanced/Admin Command Set (Target)

These commands are useful, but should eventually move under an advanced namespace:

- `admin context ...`
- `admin backups ...`
- `admin restore ...`
- `admin probe ...`
- `admin policy ...`
- `admin usage ...`
- `admin maintain ...`
- `admin sll ...` diagnostics

Design intent:

- keep default help focused on public workflow commands
- keep advanced tools discoverable but clearly non-primary

## 5. Command Responsibility Table

| Command | Primary Responsibility | Target Visibility | Notes |
|---|---|---|---|
| `setup` | Initialize and verify project/runtime prerequisites | Public | Absorbs onboarding/init responsibilities. |
| `patch` | Generate scoped patch proposals (including batch) | Public | Primary mutation-proposal interface. |
| `fix` | Guided bounded fix loop over patch/apply/test flow | Public | Convenience workflow command. |
| `diff` | Inspect latest proposed/invalid diff artifacts | Public | Read-only inspection surface. |
| `apply` | Validate/apply approved diffs with optional tests | Public | Explicit mutation gate. |
| `report` | Show and compare run reports | Public | Includes report comparison view. |
| `status` | Current run/system summary and next actions | Public | Includes doctor-style diagnostics. |
| `config` | Provider/budget/keys configuration | Public | Unified configuration namespace. |
| `workspace` | Multi-project orchestration and status | Public | Optional advanced workflow, still public. |
| `scaffold` | Generate project scaffolds/templates | Public | Preferred rename from `create`. |
| `admin` | Internal/advanced diagnostics and maintenance | Advanced | Houses non-primary operational utilities. |

## 6. Planned Command Consolidations

Planned target mappings:

- `provider` -> `config provider`
- `budget` -> `config budget`
- `keys` -> `config keys`
- `onboard` -> `setup` (compatibility/direct command retained)
- `init` -> `setup` (compatibility/direct command retained)
- `doctor` -> retained as dedicated diagnostics command (role clarified in help/docs)
- `compare` -> `report compare`
- `overview` -> retained as high-level project summary command
- `next` -> retained as recommended next-actions command
- `usage` -> retained as dedicated Aegis API usage summary command
- `create` -> `scaffold`
- `policy` -> `admin policy` (or status diagnostics)
- `probe` -> retained as stack/capability discovery command
- `context` -> `admin context`
- `backups` / `restore` -> `admin backups` / `admin restore`
- `--check-sll` -> `admin sll check`
- `maintain` -> `admin maintain`
- `scaffold` (export subflows) -> stay under `scaffold ...` or move to `admin scaffold ...` if purely operational

## 7. Deprecation Strategy

General strategy:

1. Introduce target commands and keep old commands as compatibility aliases.
2. Update docs/help/examples to prefer target commands immediately.
3. Mark legacy commands as deprecated in help output.
4. Emit explicit migration hints in command output for legacy paths.
5. Remove legacy aliases after documented migration window.

Principles:

- preserve user trust with deterministic migration guidance
- avoid silent behavior changes
- keep one obvious way to do common tasks

## 8. Migration Phases

Phase A: Taxonomy publish

- publish this architecture
- align docs terminology with target command groups

Phase B: Config consolidation

- introduce `config` namespace
- alias `provider`, `budget`, `keys` to `config` subcommands
- status: implemented (aliases retained)

Phase C: Setup/status consolidation

- make `setup` canonical; keep `init` and `onboard` as compatibility/direct commands
- keep `doctor`, `overview`, and `next` as distinct read-only inspection commands with clear roles

Phase D: Report/analysis consolidation

- fold `compare` into `report compare`
- clarify and consolidate inspection/diagnostics command roles in help/docs without removing commands

Phase E: Taxonomy-first advanced/admin classification

- keep existing commands while classifying advanced/admin tools explicitly in help/docs
- emphasize daily workflow commands as the recommended path
- mark compatibility aliases as backward-compatible entry points

Phase F: Naming cleanup

- migrate `create` to `scaffold` naming
- keep aliases during transition, then remove legacy names

## 9. Example Workflows

Single-project patch flow:

```bash
aegis-code setup
aegis-code patch --file src/main.py "fix null guard in parser"
aegis-code diff --stat
aegis-code apply --check
aegis-code apply --confirm --run-tests
aegis-code report
aegis-code status
```

Configuration flow (target):

```bash
aegis-code config provider status
aegis-code config provider preset openai
aegis-code config budget set 1.00
aegis-code config budget status
aegis-code config keys status
```

Workspace flow:

```bash
aegis-code workspace init
aegis-code workspace add ../service-a
aegis-code workspace add ../service-b
aegis-code workspace status --detailed
aegis-code workspace run "triage failing tests" --dry-run
```

Advanced diagnostics (target namespace):

```bash
aegis-code status --doctor
aegis-code admin probe
aegis-code admin context show
aegis-code admin backups
```
