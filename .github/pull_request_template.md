## Summary

Describe the contract or defect changed and why.

## Safety and compatibility

Describe tool exposure/approval, privacy, account-risk, and compatibility
implications. State “none” where appropriate.

## Verification

- [ ] Fixtures are synthetic and contain no credentials, account data, raw authenticated DOM, or traces.
- [ ] New behavior has positive, negative, ambiguity, and bounded cases as applicable.
- [ ] Write behavior has exact-target, attachment-boundary, interruption, uncertainty, and postcondition coverage as applicable.
- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run pyright`
- [ ] `uv run pytest`
- [ ] `uv build`
- [ ] Public documentation and `CHANGELOG.md` are updated when required.
