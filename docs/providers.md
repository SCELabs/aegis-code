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

## Key Management (`aegis-code config keys`)

Aegis Code supports scoped key management:

- project scope (`--project`)
- global scope (`--global`)

Commands:

```bash
aegis-code config keys status
aegis-code config keys list
aegis-code config keys set <NAME> [VALUE] --project
aegis-code config keys set <NAME> [VALUE] --global
aegis-code config keys clear <NAME> --project
aegis-code config keys clear <NAME> --global
```

Key values are never printed in plain text.
Top-level `aegis-code keys ...` remains available as a compatibility alias.

## Provider Control

Use provider commands to inspect or update provider routing:

```bash
aegis-code config provider status
aegis-code config provider detect
aegis-code config provider list
aegis-code config provider preset <name>
aegis-code config provider model <tier> <provider:model>
```

Top-level `aegis-code provider ...` remains available as a compatibility alias.

Runtime support matrix:

- Supported runtime providers today: `openai`, `openai-compatible`
- Provider presets may include additional providers for future/optional routing setups
- `aegis-code provider status` distinguishes:
  - runtime-supported providers
  - configured provider (enabled/base URL/timeout/key env)
  - preset catalog entries, including preset-only providers not yet runtime-supported for execution

## Behavior Notes

- Provider-backed patch generation is proposal-only.
- All generated patches still go through validation, safety scoring, and apply gating.
- Aegis Code remains a controlled pipeline even when provider output is available.
- Provider integration is pluggable; control policy and validation remain local runtime responsibilities.
- `aegis-code provider status` shows configured provider, base URL, timeout, enabled state, and model tier routing.

## Prompt Ownership (Current)

Operation-specific prompts are owned by dedicated prompt modules:

- `aegis_code/providers/prompts/append.py`
- `aegis_code/providers/prompts/create_file.py`
- `aegis_code/providers/prompts/insert_after.py`
- `aegis_code/providers/prompts/insert_before.py`
- `aegis_code/providers/prompts/replace_block.py`

Runtime/provider orchestration routes request context and contracts to these builders; prompt specialization is intentionally decoupled from core runtime flow.

## Aegis Integration

Aegis integration is optional.

Without Aegis:

- commands still run locally
- control behavior remains deterministic

With Aegis control enabled:

- runtime control signals may influence strategy
- mutation rules do not change (`--confirm` still required)
