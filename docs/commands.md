# Command Reference

Project:
aegis-code init
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

Context:
aegis-code context refresh
aegis-code context show

Policy:
aegis-code policy status

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
