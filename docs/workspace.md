# Workspace

Workspace allows aegis-code to manage multiple local projects.

State file:
.aegis/workspace.json

## Initialize
aegis-code workspace init

## Add / Remove
aegis-code workspace add <path>
aegis-code workspace remove <path>

Rules:
- path must exist
- must be directory
- stored as absolute path
- duplicates rejected

## Status
aegis-code workspace status
aegis-code workspace status --detailed

Detailed includes:
- existence
- config
- budget
- context
- latest run
- mode

## Overview
aegis-code workspace overview

## Refresh Context
aegis-code workspace refresh-context

## Run

Preview:
aegis-code workspace run "<task>" --dry-run

Execute:
aegis-code workspace run "<task>" --confirm

Execution notes:
- sequential
- skips missing projects
- preserves budget/mode/context
- no parallel execution

## Safety
- local-only
- deterministic
- no external calls for lifecycle/inspection
- execution uses normal per-project runtime
