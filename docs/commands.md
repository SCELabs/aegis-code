# Command Reference

Mode note: see README.md section "Local vs Aegis-Enhanced Mode" for runtime behavior differences.

Project:
aegis-code init
aegis-code setup
aegis-code setup --check
aegis-code next
aegis-code overview
aegis-code status
aegis-code report
aegis-code compare
aegis-code maintain

Runtime:
aegis-code "<task>"
aegis-code "<task>" --dry-run
aegis-code "<task>" --mode cheapest
aegis-code "<task>" --propose-patch

Budget:
aegis-code budget set <amount>
aegis-code budget status
aegis-code budget clear
Budget is a control signal for runtime behavior, not real API spending.

Context:
aegis-code context refresh
aegis-code context show

Policy:
aegis-code policy status

Provider:
aegis-code provider status
aegis-code provider list
aegis-code provider detect
aegis-code provider preset <name>
aegis-code provider model <tier> <provider:model>
Presets include: openai, cheap-openai, anthropic, local-ollama, openrouter, gemini

Create:
aegis-code create --list-stacks
aegis-code create "<idea>"
aegis-code create "<idea>" --stack <stack-id>
aegis-code create "<idea>" --target <path>
aegis-code create "<idea>" --target <path> --confirm
aegis-code create "<idea>" --target <path> --confirm --validate

Workspace:
aegis-code workspace init
aegis-code workspace add <path>
aegis-code workspace remove <path>
aegis-code workspace status
aegis-code workspace status --detailed
aegis-code workspace overview
aegis-code workspace refresh-context
aegis-code workspace run "<task>" --dry-run
aegis-code workspace run "<task>" --confirm

Patches:
aegis-code apply --check <path>
aegis-code apply <path>
aegis-code apply <path> --confirm
aegis-code backups
aegis-code restore <backup-id>
