## Summary
<!-- What does this PR do? Which phase/objective does it address? -->

## Type of change
- [ ] Bug fix (non-breaking)
- [ ] New feature
- [ ] Breaking change
- [ ] Performance improvement
- [ ] Documentation

## Testing
- [ ] `mypy .` returns zero errors
- [ ] `ruff check .` passes
- [ ] All new functions have unit tests
- [ ] `pytest tests/unit/` passes
- [ ] Coverage did not decrease (run `pytest --cov`)
- [ ] Integration tests pass (if applicable): `pytest tests/integration/`

## Mathematical validation (if applicable)
- [ ] Formula documented in docstring with academic reference
- [ ] Property test added with Hypothesis
- [ ] Result verified against manual calculation

## CLAUDE.md compliance
- [ ] Decimal used for all prices/sizes (no float)
- [ ] UTC datetime used (no naive datetimes)
- [ ] structlog used (no print())
- [ ] ZMQ topics via core/topics.py (no hardcoded strings)
- [ ] SOLID principles applied
- [ ] Adaptive behavior maintained (service reads inputs continuously, not only at startup)
