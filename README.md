# aegis-code

`aegis-code` is a terminal-native, Aegis-guided coding workflow runner focused on safe, supervised operation.

Current capabilities include failure-aware test triage, optional structural analysis, proposal-only patch diffs, deterministic patch-quality scoring, explicit human-confirmed apply with backups, and controlled project scaffold creation.

## Install (Dev)

```bash
pip install -e .
```

## Environment Variables

- `AEGIS_API_KEY` (optional for local smoke tests, required for real backend auth)
- `AEGIS_BASE_URL` (optional override; otherwise config/default is used)
- `OPENAI_API_KEY` (optional; only needed for provider-backed proposal diffs)

See `.env.example` for a starter template.

## Quick Start

```bash
aegis-code init
```

Run a task:

```bash
aegis-code "triage current test failures" --budget 1.25
```

View one-shot project state summary:

```bash
aegis-code overview
```

Inspect read-only runtime policy status:

```bash
aegis-code policy status
```

Refresh deterministic project-local context:

```bash
aegis-code context refresh
aegis-code context show
```

Set a local runtime budget guardrail:

```bash
aegis-code budget set 1.00
aegis-code budget status
```

List available stack profiles:

```bash
aegis-code create --list-stacks
```

Create a planning-only project plan:

```bash
aegis-code create "inventory tracker"
```

Force a stack profile:

```bash
aegis-code create "inventory tracker" --stack python-fastapi
```

Preview scaffold target without writing files:

```bash
aegis-code create "inventory tracker" --target ./inventory-api
```

Write scaffold files with explicit confirmation:

```bash
aegis-code create "inventory tracker" --target ./inventory-api --confirm
```

Write scaffold files and validate:

```bash
aegis-code create "inventory tracker" --target ./inventory-api --confirm --validate
```

## Stack Profiles

Current internal stack IDs:

- `python-basic`
- `python-cli`
- `python-fastapi`
- `node-react`

Profiles are versioned internally (starting at `0.1`) and surfaced in create planning output.

Scaffold writes `.aegis/create_manifest.yml` to record selected stack, stack version, idea, test command, and created files.

No external Copier/Cookiecutter template dependency is used yet.

`aegis-code create --list-stacks` lists internal stack profiles and versions without generating a plan or writing files.

`--validate` is optional and only runs after `--target` + `--confirm`; it runs tests for the scaffold and, on failure, runs Aegis stabilization planning/proposal flow.

## Runtime Policy

`aegis-code policy status` is read-only and local-only.

It shows current project runtime policy signals:

- mode and configured model tiers
- provider config flags (without secret values)
- budget state and remaining estimate
- context availability and capped runtime context metadata
- verification command and runtime guard summary

This pass does not change runtime routing or model selection.

Budget-aware mode selection policy (v1):

- no budget file: keep configured/requested mode
- remaining budget `< 0.10`: force `cheapest` mode for that invocation
- no mid-run mode switching
- deterministic per invocation

Runtime calls now receive a structured local control payload:

- `project_context`
- `budget_state`
- `runtime_policy`

This prepares Aegis Code for deeper client integration without adding new external calls.

Budget runtime events now record selected mode and decision reason (`default`, `low_budget`, or `policy_adjustment`) in `.aegis/budget.json` for local observability.

Runtime Control summaries in CLI/report output show selected mode, reason, budget remaining, and context availability.
Runtime Adapter summaries in CLI/report output show execution path (`local` or `aegis`) and optional client/fallback details.
Set `aegis.enhanced_runtime: true` in `.aegis/aegis-code.yml` to enable optional Aegis Client control guidance (requires `aegis` client package installed); default is `false` and local execution remains the safe default/fallback.

## Overview

`aegis-code overview` provides a compact full-project snapshot in one command:

- detected stack
- verification command
- budget remaining/limit
- context availability and size
- selected runtime mode + reason
- latest run presence
- backup count

This is local-only, deterministic, and read-only.

## Project Context

`aegis-code context refresh` and `aegis-code context show` manage deterministic local context under `.aegis/context/`.

- local only and deterministic
- no network/provider/backend calls
- selective reads from `README.md`, `pyproject.toml`, `package.json`, and bounded `docs/**/*.md`
- runtime commands load compact project context when available
- runtime inclusion order: `project_summary`, `constraints`, `architecture`
- runtime context is capped (default 6000 chars) with truncation marker when needed
- reports include context metadata (`available`, `included_paths`, `total_chars`)
- intended as high-signal project-local context for runtime control and project awareness

## Command Index

- `aegis-code init` - create `.aegis` config/project model files
- `aegis-code "<task>"` - run controlled failure-aware workflow
- `aegis-code overview` - show compact full-project state summary
- `aegis-code policy status` - show read-only local runtime policy summary
- `aegis-code context refresh` - build deterministic project-local context files
- `aegis-code context show` - show context status, paths, and compact previews
- `aegis-code create --list-stacks` - list available internal stack profiles and versions
- `aegis-code create "<idea>"` - generate a planning-only project plan preview
- `aegis-code create "<idea>" --stack STACK_ID` - force a stack profile
- `aegis-code create "<idea>" --target PATH` - preview scaffold file set (no writes)
- `aegis-code create "<idea>" --target PATH --confirm` - write scaffold to empty target
- `aegis-code create "<idea>" --target PATH --confirm --validate` - scaffold, verify, and run stabilization proposal on failures
- `aegis-code budget set AMOUNT` - set local runtime budget estimate limit
- `aegis-code budget status` - show local runtime budget estimate usage
- `aegis-code budget clear` - clear local runtime budget file
- `aegis-code report` - print latest markdown report
- `aegis-code status` - compact latest-run summary
- `aegis-code maintain` - read-only repo health and suggestions
- `aegis-code --check-sll` - verify optional SLL local import
- `aegis-code apply --check PATH` - inspect diff without modifying files
- `aegis-code apply PATH` - preview apply and require explicit confirmation
- `aegis-code apply PATH --confirm` - human-confirmed apply with backups
- `aegis-code backups` - list backup snapshots
- `aegis-code restore BACKUP_ID` - restore files from backup snapshot

## Safety Model

- No autonomous edits.
- No patch auto-apply.
- `--confirm` required for file mutation.
- Confirmed apply creates backups under `.aegis/backups/...`.
- Restore is available for rollback.
- No git commands are run by `aegis-code`.
- `create --target` refuses current repo root and non-empty targets.
- Local budget guardrails apply to runtime/Aegis calls only.
- Planning, listing, config, and other local-only operations are always free.
- Context refresh/show are local deterministic operations only.

## Optional Integrations

- SLL (`structural_language_lab`) is optional and local-install only.
- Provider-backed patch diffs are optional and proposal-only.
- Optional `aegis` client auto-detection is supported at runtime; when unavailable, Aegis Code automatically falls back to local runtime execution with no config changes required.
- Enhanced runtime is feature-flagged via `aegis.enhanced_runtime` and uses `client.auto().step(...)` as a control-layer call.
- Local verification/execution remains primary; Aegis guidance is attached as `aegis_result`.
- Fallback stays local when disabled, import is missing, or client execution errors.
