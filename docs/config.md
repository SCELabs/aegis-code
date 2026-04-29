# Configuration

Stored under .aegis/

Main config:
.aegis/aegis-code.yml

Contains:
- mode
- budget defaults
- model tiers
- commands
- aegis settings
- provider config
- patch config

Note: `aegis.enhanced_runtime` controls whether Aegis guidance is applied when an `AEGIS_API_KEY` is available.

Project model:
.aegis/project_model.md

Runtime reports:
.aegis/runs/latest.json
.aegis/runs/latest.md
.aegis/runs/history/

Workspace:
.aegis/workspace.json

Secrets:
DO NOT store keys in config.
Use environment variables.

## Budget

The budget in Aegis Code is a control signal used to influence runtime behavior (such as model selection and retry strategies).

It does NOT track or limit real API spending.
