# Providers and Keys

Environment variables:

AEGIS_API_KEY
AEGIS_BASE_URL
OPENAI_API_KEY

Example:
export AEGIS_API_KEY=...
export OPENAI_API_KEY=...

Windows:
setx AEGIS_API_KEY ...
setx OPENAI_API_KEY ...

Future direction:

aegis-code keys set AEGIS_API_KEY
aegis-code keys status
aegis-code keys clear OPENAI_API_KEY

Secrets must not be committed.

## Using Aegis

Aegis integration is optional.

Without Aegis:
- all commands run locally
- behavior is deterministic
- no external calls are made

With Aegis enabled:
- runtime behavior can be adjusted dynamically
- additional stabilization signals are applied
- system performance may improve for complex workflows

To enable:

aegis-code onboard

Or manually:

aegis-code keys set AEGIS_API_KEY <key>
