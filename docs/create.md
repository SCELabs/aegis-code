# Create Command

`aegis-code create "<project idea>"` is planning-only by default.

- It generates a deterministic local project plan preview.
- It does not write project files unless both `--target` and `--confirm` are provided.

Examples:

```bash
aegis-code create "build a REST API for user management"
aegis-code create "build a CLI for parsing logs"
aegis-code create "build a React dashboard"
```

Preview scaffold target (no writes):

```bash
aegis-code create "build a REST API" --target ./my-project
```

Write scaffold files (explicit confirmation required):

```bash
aegis-code create "build a REST API" --target ./my-project --confirm
```

Safety rules:

- No `--target` means planning-only (no writes).
- Target must not be the current repository root.
- Existing non-empty target is refused.
- Existing files are not overwritten.
