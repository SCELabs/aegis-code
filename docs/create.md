# Create Command

`aegis-code create "<project idea>"` is planning-only by default.

- It generates a deterministic local project plan preview.
- It does not write project files unless both `--target` and `--confirm` are provided.

Discover stack profiles without planning or scaffolding:

```bash
aegis-code create --list-stacks
```

- Lists available internal stack profiles and versions.
- Does not generate a plan.
- Does not write files.

Stack selection:

- Automatic selection uses deterministic keyword scoring.
- Override with `--stack STACK_ID`.
- Profiles are internal and versioned.

Current stack IDs:

- `python-basic`
- `python-cli`
- `python-fastapi`
- `node-react`

Examples:

```bash
aegis-code create "inventory tracker"
aegis-code create "inventory tracker" --stack python-fastapi
aegis-code create "inventory tracker" --stack python-fastapi --target ./inventory-api
aegis-code create "inventory tracker" --stack python-fastapi --target ./inventory-api --confirm
aegis-code create "inventory tracker" --target ./inventory-api --confirm --validate
```

Scaffold behavior:

- `--target` without `--confirm` previews files only (`Applied: false`).
- `--target` with `--confirm` writes deterministic scaffold files (`Applied: true`).
- Scaffolding writes `.aegis/create_manifest.yml` with stack/version and created file list.
- `--validate` is only supported with `--target` and `--confirm`.
- Validation runs the planned test command; if tests fail, Aegis runs a stabilization pass using existing runtime behavior.

Safety rules:

- No `--target` means planning-only (no writes).
- Target must not be the current repository root.
- Existing non-empty target is refused.
- Existing files are not overwritten.

Notes:

- Internal scaffold profiles only for now.
- No external Copier/Cookiecutter template dependency yet.
