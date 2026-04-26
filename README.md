# aegis-code

`aegis-code` is a terminal-native, budget-aware coding runtime powered by Aegis execution guidance.

This repository currently implements the first MVP vertical slice (`v0.1`): planning and reporting only, with no autonomous file editing.

## v0.1 Scope

- Installable Python package (`aegis-code`, import as `aegis_code`)
- CLI command: `aegis-code`
- Project bootstrap: `aegis-code init`
- Task planning/execution guidance fetch: `aegis-code "<task>"`
- Report rendering: `aegis-code report`
- Local project state in `.aegis/`
- Aegis backend client integration using `scelabs-aegis>=0.6.1`
- Execution guidance consumption:
  - `result.execution`
  - `result.model_tier`
  - `result.context_mode`
  - `result.max_retries`
  - `result.allow_escalation`
- Model tier routing (`cheap`, `mid`, `premium`)
- Budget tracking (`total`, `spent`, `remaining`)
- Markdown + JSON report output

## Important Limitations in v0.1

- No model provider calls (OpenAI/Anthropic/etc.) yet
- No code modifications yet
- No autonomous coding loop yet
- Only safe baseline local actions:
  - repository file tree scan
  - optional configured test command (when not `--dry-run`)

## Install (Dev)

```bash
pip install -e .
```

## Environment Variables

- `AEGIS_API_KEY` (optional for local smoke tests, required for real backend auth)
- `AEGIS_BASE_URL` (optional override; otherwise config/default is used)

See `.env.example` for a starter template.

## Quick Start

Initialize project files:

```bash
aegis-code init
```

Run a planning task:

```bash
aegis-code "triage current test failures" --budget 1.25 --mode balanced --dry-run
```

Show latest report:

```bash
aegis-code report
```

## Aegis Guidance Flow

For each task, `aegis-code` requests Aegis execution guidance and then maps returned `model_tier` to a concrete local model from config:

- `cheap` -> `models.cheap`
- `mid` -> `models.mid`
- `premium` -> `models.premium`

This preserves centralized policy from Aegis while keeping local model resolution configurable per repo.
