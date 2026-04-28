# Policy Status

`aegis-code policy status` prints a read-only local runtime policy summary.

It uses local project state only and does not call networked services.

Included sections:

- mode from config
- configured model tiers (`cheap`, `mid`, `premium`)
- provider config (`enabled`, provider name, `api_key_env` name only)
- budget state from `.aegis/budget.json` if present
- runtime context availability and capped context metadata
- verification command (`commands.test`)
- runtime guard summary

Notes:

- This command does not switch models or change runtime routing.
- No backend/provider calls are made.
- No files are written.

## Budget-aware mode selection (v1)

Runtime invocations apply a deterministic pre-run mode selector:

- no budget file: keep configured/requested mode
- remaining budget `< 0.10`: force `cheapest`
- otherwise: keep configured/requested mode

This is an initial mode decision only; no mid-run switching is performed.

## Runtime control payload

Before runtime calls, Aegis Code now passes a structured control payload into runtime options:

- `project_context`
- `budget_state`
- `runtime_policy`

This is local-only metadata to prepare for deeper client integration later.

## Budget event observability

When runtime is invoked and budget tracking is active, budget events include:

- `selected_mode`
- `reason` (`default`, `low_budget`, `policy_adjustment`)
- `timestamp`

This logging is local-only and deterministic.
