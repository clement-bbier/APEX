# Merged Phase 3 Calculator PRs — Reference

| PR | Sub-phase | Calculator | Branch | Key decisions introduced |
|----|-----------|-----------|--------|--------------------------|
| #111 | 3.4 | HAR-RV (Corsi 2009) | phase-3/har-rv-validation | D024, D025, D026, D027 |
| #112 | 3.5 | Rough Vol (Gatheral 2018) | phase-3/rough-vol-validation | D028 (PIT classification) |
| #113 | 3.6 | OFI (Cont et al. 2014) | phase-3/ofi-validation | D029, D030 |
| #114 | 3.7 | CVD + Kyle (Kyle 1985) | phase-3/cvd-kyle-validation | D032 (inline vs wrapper) |
| #116 | 3.8 | GEX (Barbon-Buraschi 2020) | phase-3/gex-validation | D033, D034 |

## When to reference

When starting a new calculator:
1. Identify the closest existing calculator by granularity:
   - Bar-level daily/intraday: HAR-RV, Rough Vol
   - Tick-level: OFI, CVD+Kyle
   - Snapshot-level: GEX
2. Read the corresponding PR body for the exact test matrix and PR section structure
3. Follow the commit message and PR body format exactly
