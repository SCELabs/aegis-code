# Commands

- `aegis-code init`  
  Initialize `.aegis` config and project model files.  
  Example: `aegis-code init`

- `aegis-code "<task>"`  
  Run the controlled workflow for a task.  
  Example: `aegis-code "triage current test failures" --budget 1.25`

- `aegis-code report`  
  Print the latest markdown report.  
  Example: `aegis-code report`

- `aegis-code status`  
  Show compact latest-run status and backup count.  
  Example: `aegis-code status`

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

