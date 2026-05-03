# Providers and Keys

## Environment Variables

Common keys:

- `AEGIS_API_KEY`
- `AEGIS_BASE_URL`
- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

Examples:

```bash
export AEGIS_API_KEY=...
export OPENAI_API_KEY=...
```

Windows:

```powershell
setx AEGIS_API_KEY ...
setx OPENAI_API_KEY ...
```

## Key Management (`aegis-code keys`)

Aegis Code supports scoped key management:

- project scope (`--project`)
- global scope (`--global`)

Commands:

```bash
aegis-code keys status
aegis-code keys list
aegis-code keys set <NAME> [VALUE] --project
aegis-code keys set <NAME> [VALUE] --global
aegis-code keys clear <NAME> --project
aegis-code keys clear <NAME> --global
```

Key values are never printed in plain text.

## Provider Control

Use provider commands to inspect or update provider routing:

```bash
aegis-code provider status
aegis-code provider detect
aegis-code provider list
aegis-code provider preset <name>
aegis-code provider model <tier> <provider:model>
```

## Behavior Notes

- Provider-backed patch generation is proposal-only.
- All generated patches still go through validation, safety scoring, and apply gating.
- Aegis Code remains a controlled pipeline even when provider output is available.

## Aegis Integration

Aegis integration is optional.

Without Aegis:

- commands still run locally
- control behavior remains deterministic

With Aegis control enabled:

- runtime control signals may influence strategy
- mutation rules do not change (`--confirm` still required)
