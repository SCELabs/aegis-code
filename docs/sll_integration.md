# SLL Integration (Optional)

`aegis-code` can optionally use Structural Language Lab (SLL) for structural risk signals.

## Optional dependency
- SLL is optional.
- SLL is not a required PyPI dependency of `aegis-code`.

## Local install from sibling repo
- `pip install -e ../structural-language-lab`

## Verify local setup
- `aegis-code --check-sll`

## What SLL contributes
- `regime`
- `collapse_risk`
- `fragmentation_risk`
- `drift_risk`
- `stable_random_risk`

## What SLL does not do
- It does not make runtime decisions.
- It does not replace Aegis.
- It does not edit files.
- It does not call models.

