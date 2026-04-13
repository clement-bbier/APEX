# APEX Calculator Skill

Skill for creating and validating new FeatureCalculator implementations in the APEX/CashMachine quant trading system.

## When to use this skill

Trigger this skill when:
- User asks to implement a new calculator in `features/calculators/`
- User references Phase 3 sub-phases 3.4-3.8 (HAR-RV, Rough Vol, OFI, CVD+Kyle, GEX) OR 3.9-3.13 patterns
- User mentions D024, D025, D026, D027, D028, D029, D030, D032, D033, D034
- PR needs to match the established template from PR #111 (HAR-RV), #112 (Rough Vol), #113 (OFI), #114 (CVD+Kyle), #116 (GEX)

Do NOT trigger for:
- Modifications of existing calculators (not new ones)
- Changes to S01-S10 services
- Analysis-phase sub-phases (3.9 multicollinearity, 3.10 CPCV, 3.11 DSR/PBO) — these have different structure

## Core invariants

Every new calculator MUST:

1. **Strict wrapper (D026)** — wrap existing S02/S07 if available, OR implement inline with decision justification (D030/D032/D033 pattern). Never modify S02/S07.
2. **Expanding window for look-ahead safety (D024)** — for regression-based outputs, fit on strict past `[0, t-1]` or rolling `[t-w, t-1]`. O(n²) is acceptable if it's correct.
3. **tanh normalization k=3 (D025)** — all signal outputs in `[-1, +1]` via `tanh(x / (k * rolling_std))`.
4. **D027 intraday emission** — if the calculator aggregates a period (e.g., daily from 5m bars), realization-like columns emit ONLY on period-close bars. Forecast-like columns broadcast safely.
5. **D028 explicit classification** — every output column must be declared as "realization at t" or "forecast-like at t" in the class docstring. Load `patterns/d028-classification.md` for decision rules.
6. **D029 variance gate per signal column** — every signal output needs a test verifying `std(output.mean() across 100 synthetic DataFrames) > 0.01`. Load `patterns/d029-variance-gates.md`.
7. **D030 dynamic configurable params** — any constructor parameter must propagate dynamically to column names, indices, output shape. Never hardcode downstream. Load `patterns/d030-dynamic-params.md`.
8. **D034 snapshot-level IC for snapshot-granularity features** — if the calculator broadcasts its outputs across multiple rows per timestamp (like GEX), IC measurement in integration tests must aggregate to snapshot level first.

## File structure (mandatory)

```
features/calculators/
  <name>.py              # Calculator class
features/validation/
  <name>_report.py       # ICReport wrapper (schema compatible w/ HAR-RV)
tests/unit/features/calculators/
  test_<name>.py          # 20+ tests following the template
```

Also update `features/calculators/__init__.py` to export the new calculator (alphabetical order).

## Test structure (mandatory minimum 20 tests, target 25+)

Load `test-templates/calculator-test-structure.md` for the full template. Categories:

- **ABC conformity** (3): name, required_columns, output_columns
- **Constructor validation D030** (N, one per configurable param)
- **Correctness** (7+): output shape, warm-up NaN, Hypothesis bounds, determinism, version
- **Look-ahead defense D024** (2): strict past independence from future
- **D028 compliance** (1): docstring declares classification keywords
- **D029 variance gates** (one per signal column)
- **Edge cases** (3): insufficient data, missing column, unsorted timestamps
- **Integration** (2): ValidationPipeline with ICStage, measurable IC on synthetic predictive data
- **Report** (2): summary schema stability, None significance → "n/a"

## Preflight gates (mandatory before commit)

```bash
CI=true ruff check .
CI=true ruff format --check .
CI=true mypy . --strict
CI=true pytest tests/unit/features/calculators/test_<name>.py -v --timeout=30
CI=true pytest tests/unit/features/ --cov=features --cov-report=term-missing --cov-fail-under=85 --timeout=30
```

Coverage: new calculator file >= 90%, features/ >= 85%, 0 regressions.

## Commit and PR conventions

Commit message pattern (from PR #111-#116):

```
feat(features): add Phase 3.X <Name>Calculator (<Author> <Year>)

- <one-line summary per major design point>
- D024 expanding window / rolling strict past
- D028 classification: <column list per type>
- D029 variance gates on <signal columns>
- D030 constructor validation: <param list>
- <wrapping decision: D032/D033 if inline, D026 if wrapper>
- <N> unit tests covering <categories>

Refs: PHASE_3_SPEC §2.X, ADR-0004, D024-DXXX,
<academic references with year and journal>.
Closes #<issue>
```

PR body must include:
- Files created with LOC
- Full test matrix (categories and count)
- Preflight gates table
- D028 classification table per output column
- D030 constructor validation table
- Sign convention / magnitude sanity (if applicable)
- Pattern reuse breakdown vs merged PR references

## Anti-patterns (do NOT do)

- Do NOT modify S02-S10 services
- Do NOT reimplement math if S02/S07 has a correct version (D026 strict wrapper)
- Do NOT hardcode column names when constructor accepts configurable params (D030)
- Do NOT use expanding window on an entire series with a single fit (that's look-ahead — D024 violation)
- Do NOT relax IC threshold in integration tests if snapshot-level IC is low — fix the synthetic predictive data instead (D034)
- Do NOT merge the PR yourself — always wait for Copilot review
