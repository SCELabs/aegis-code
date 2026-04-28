# v0.4 Patch Proposal Validation

## Manual failing-test validation
1. Manually create `tests/test_tmp_failure.py` with:

```python
def test_tmp_failure():
    assert 1 == 2
```

2. Run:
- `python -m pytest -q`
- `aegis-code "triage current test failures" --budget 1.25 --propose-patch`
- `aegis-code report`

## Expected behavior
- Tests fail and failure metadata is observed.
- Synthesized symptoms include `test_failure`.
- `patch_plan` references the failing test.
- `patch_diff` is attempted only when proposal mode is enabled and failures remain.
- `latest.diff` is written only when a valid unified diff is produced.
- No project files are edited by `aegis-code`.
- `aegis-code` does not create or delete the temporary failing test.

## SLL-active validation
1. Install SLL locally:
- `pip install -e ../structural-language-lab`

2. Verify:
- `aegis-code --check-sll`

3. Manually create temporary failure:
- `tests/test_tmp_failure.py`

4. Run:
- `aegis-code "triage current test failures" --budget 1.25 --propose-patch`
- `aegis-code report`

Expected:
- Structural Analysis shows regime and risks.
- Synthesized Symptoms include `test_failure`.
- Patch plan references failing test(s).
- Patch Diff Proposal is attempted only when provider path is enabled and API key exists.
- No patch is applied automatically.
- User deletes the temporary test manually afterward.

## Cleanup
- `rm tests/test_tmp_failure.py`
- `python -m pytest -q`
