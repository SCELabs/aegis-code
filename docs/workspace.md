# Workspace

Workspace lets you run the same controlled pipeline across multiple local projects.

State file:

`.aegis/workspace.json`

## Initialize

```bash
aegis-code workspace init
```

## Add / Remove

```bash
aegis-code workspace add <path>
aegis-code workspace remove <path>
```

Rules:

- path must exist
- path must be a directory
- stored as absolute path
- duplicates rejected

## Status

```bash
aegis-code workspace status
aegis-code workspace status --detailed
```

Detailed status includes existence/config/budget/context/latest run/mode.

## Overview

```bash
aegis-code workspace overview
```

## Refresh Context

```bash
aegis-code workspace refresh-context
```

## Run

Preview:

```bash
aegis-code workspace run "<task>" --dry-run
```

Execute:

```bash
aegis-code workspace run "<task>" --confirm
```

Execution notes:

- sequential per project
- skips missing projects
- preserves each project's local budget/mode/context controls
- uses normal per-project validation/repair/safety/apply rules
- no parallel execution

## Keys and Scope

Workspace runs use each target project's config plus available key scope:

- project-scoped keys
- global-scoped keys

Use `aegis-code keys` to inspect/set/clear keys.

## Safety

- local lifecycle/inspection operations are deterministic
- mutation requires explicit confirm in the command flow
- no git commands are run
