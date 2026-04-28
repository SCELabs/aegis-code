# Commands

- `aegis-code init`  
  Initialize `.aegis` config and project model files.  
  Example: `aegis-code init`

- `aegis-code "<task>"`  
  Run the controlled workflow for a task.  
  Example: `aegis-code "triage current test failures" --budget 1.25`

- `aegis-code policy status`  
  Show read-only local runtime policy summary (mode, model tiers, budget, context, verification).  
  Example: `aegis-code policy status`

- `aegis-code context refresh`  
  Build deterministic project-local context files under `.aegis/context/`.  
  Example: `aegis-code context refresh`

- `aegis-code context show`  
  Show context availability, generated file paths, and compact previews.  
  Example: `aegis-code context show`

- `aegis-code budget set AMOUNT`  
  Set local runtime budget estimate limit in `.aegis/budget.json`.  
  Example: `aegis-code budget set 1.00`

- `aegis-code budget status`  
  Show current local runtime budget estimate usage.  
  Example: `aegis-code budget status`

- `aegis-code budget clear`  
  Clear local runtime budget file.  
  Example: `aegis-code budget clear`

- `aegis-code create --list-stacks`  
  List available internal stack profiles and versions; no plan/scaffold and no files written.  
  Example: `aegis-code create --list-stacks`

- `aegis-code create "<idea>"`  
  Generate a planning-only project plan preview (no files written).  
  Example: `aegis-code create "inventory tracker"`

- `aegis-code create "<idea>" --stack STACK_ID`  
  Force a specific internal stack profile (versioned).  
  Example: `aegis-code create "inventory tracker" --stack python-fastapi`

- `aegis-code create "<idea>" --target PATH`  
  Preview scaffold files for a target path (still no files written; confirmation required).  
  Example: `aegis-code create "inventory tracker" --target ./inventory-api`

- `aegis-code create "<idea>" --target PATH --confirm`  
  Write deterministic scaffold files to an empty target directory.  
  Example: `aegis-code create "inventory tracker" --target ./inventory-api --confirm`

- `aegis-code create "<idea>" --target PATH --confirm --validate`  
  Scaffold, run tests, and if failing run Aegis stabilization planning/proposal flow.  
  Example: `aegis-code create "inventory tracker" --target ./inventory-api --confirm --validate`

- `aegis-code report`  
  Print the latest markdown report.  
  Example: `aegis-code report`

- `aegis-code status`  
  Show compact latest-run status and backup count.  
  Example: `aegis-code status`

- `aegis-code maintain`  
  Show read-only repo health summary and safe next actions.  
  Example: `aegis-code maintain`

- `aegis-code --check-sll`  
  Verify optional local SLL import.  
  Example: `aegis-code --check-sll`

- `aegis-code apply --check PATH`  
  Validate a diff without modifying files.  
  Example: `aegis-code apply --check .aegis/runs/latest.diff`

- `aegis-code apply PATH`  
  Preview apply summary without modifying files.  
  Example: `aegis-code apply .aegis/runs/latest.diff`

- `aegis-code apply PATH --confirm`  
  Human-confirmed apply with backups.  
  Example: `aegis-code apply .aegis/runs/latest.diff --confirm`

- `aegis-code backups`  
  List backup snapshots.  
  Example: `aegis-code backups`

- `aegis-code restore BACKUP_ID`  
  Restore files from a backup snapshot.  
  Example: `aegis-code restore 20260428_143210`
