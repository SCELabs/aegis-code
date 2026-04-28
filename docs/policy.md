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
