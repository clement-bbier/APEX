# Phase 4.6 — Implementation Audit

**Issue**: #130
**Branch**: `phase-4.6-persistence-model-card`
**Author**: Clément Barbier (with Claude Code)
**Date**: 2026-04-15
**Status**: PRE-IMPLEMENTATION — design contract; code in this PR
implements it.
**Predecessors**: Phase 4.3 (PR #140, `d5dc3a0`), Phase 4.4 (PR #141,
`e477c96`), mid-phase leakage audit (PR #142, `acbbe07`), Phase 4.5
(PR #143, `d4768a3`).

References: `docs/phases/PHASE_4_SPEC.md` §3.6;
`docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D6;
`docs/adr/0002-quant-methodology-charter.md` Section A item 7.

---

## 1. Objective

Persist a validated Meta-Labeler (post-4.5 PASS verdict) to disk as a
`.joblib` artifact with a schema-versioned JSON model card, and
guarantee a deterministic `save → load → predict` round-trip on a
fixed 1,000-row test batch with **zero tolerance** on the predicted
probabilities (bit-exact). Per ADR-0005 D6, non-determinism on
round-trip is a deployment blocker.

This sub-phase adds **no training logic** and **no statistical
computation**. It is pure I/O + schema + reproducibility plumbing
that seals the contract between a trained model and every downstream
consumer (Phase 4.7 Fusion Engine, Phase 5 model registry).

## 2. Deliverables

Two new production modules under `features/meta_labeler/`:

```
features/meta_labeler/
├── model_card.py     NEW — ModelCardV1 TypedDict + validate_model_card
└── persistence.py    NEW — save_model / load_model + dataset hasher
```

Two new test modules under `tests/unit/features/meta_labeler/`:

```
tests/unit/features/meta_labeler/
├── test_model_card.py   ~10 tests, ≥ 94 % cov on model_card.py
└── test_persistence.py  ~14 tests, ≥ 94 % cov on persistence.py
```

Supporting artefacts:

```
docs/examples/model_card_v1_example.json     NEW — reference card
scripts/generate_phase_4_6_report.py         NEW — round-trip demo
models/meta_labeler/                         NEW dir (gitignored)
.gitignore                                   UPDATED
reports/phase_4_6/audit.md                   (this file)
```

Scope estimate: ~450 LOC production + ~600 LOC tests.

## 3. Reuse inventory

Every upstream component is reused without modification.

| Component | Path | Phase 4.6 usage |
|---|---|---|
| `BaselineTrainingResult` | `features/meta_labeler/baseline.py` | source of `rf_model` / `logreg_model` and their HPs |
| `MetaLabelerValidationReport` | `features/meta_labeler/validation.py` | `gates_measured` + `gates_passed` for the card |
| `MetaLabelerFeatureSet.feature_names` | `features/meta_labeler/feature_builder.py` | `features_used` list order |
| `MetaLabelerFeatureSet.X`, `.y` | same | dataset hash input |
| Synthetic bars + label fixtures | `tests/unit/features/meta_labeler/*` | round-trip fixtures |

No modification of `features/meta_labeler/{baseline,tuning,validation,
pnl_simulation,feature_builder}.py`. No modification of the ADR
contracts (D6 is implemented verbatim).

## 4. Model card schema (v1)

Per ADR-0005 D6 + PHASE_4_SPEC §3.6 public API:

```python
class ModelCardV1(TypedDict):
    schema_version: Literal[1]
    model_type: str                       # "RandomForestClassifier" | "LogisticRegression"
    hyperparameters: dict[str, Any]
    training_date_utc: str                # ISO-8601, MUST end with "Z"
    training_commit_sha: str              # exactly 40 lowercase hex chars
    training_dataset_hash: str            # "sha256:" + 64 lowercase hex chars
    cpcv_splits_used: list[list[list[int]]]
    features_used: list[str]              # order matches X column order
    sample_weight_scheme: str
    gates_measured: dict[str, float]
    gates_passed: dict[str, bool]         # must contain "aggregate"
    baseline_auc_logreg: float
    notes: str
```

`validate_model_card` enforces all of:

1. Exact key-set match (no extras, no missing).
2. `schema_version == 1` — any other value raises `ValueError`
   (explicit rejection of schema v2 is a test).
3. `model_type ∈ {"RandomForestClassifier", "LogisticRegression"}`.
4. `training_date_utc` parses as ISO-8601 UTC AND ends with `"Z"`
   (no ±hh:mm offsets — D6 mandates Z-suffix).
5. `training_commit_sha` matches `^[0-9a-f]{40}$`.
6. `training_dataset_hash` matches `^sha256:[0-9a-f]{64}$`.
7. `features_used` is a non-empty list of strings, no duplicates.
8. `gates_passed` contains the key `"aggregate"` and its value is
   the boolean AND of all other gate booleans (cross-consistency).
9. `baseline_auc_logreg` ∈ [0.0, 1.0].
10. All of `cpcv_splits_used`, `gates_measured`, `gates_passed`,
    `hyperparameters` are JSON-serialisable.

Any violation raises `ValueError` with a message naming the failing
field. No silent-pass (D6 hard rule).

## 5. Deterministic dataset hash

Per PHASE_4_SPEC §3.6 algorithm note. The hasher is library-agnostic
(no pandas, no pyarrow) and stable across numpy versions because the
byte layout of a C-contiguous `.tobytes()` is numpy-version
independent for fixed `(shape, dtype)`.

The hasher consumes, in this exact order:

1. UTF-8 of `json.dumps(feature_names, sort_keys=True,
   separators=(",", ":"))` where `feature_names` is the ordered list
   of column names.
2. UTF-8 of `json.dumps({"shape": list(X.shape), "dtype":
   str(X.dtype)}, sort_keys=True, separators=(",", ":"))`.
3. `np.ascontiguousarray(X).tobytes(order="C")`.
4. UTF-8 of `json.dumps({"shape": list(y.shape), "dtype":
   str(y.dtype)}, sort_keys=True, separators=(",", ":"))`.
5. `np.ascontiguousarray(y).tobytes(order="C")`.

Final card value: `"sha256:" + hashlib.sha256(...).hexdigest()`.

A reference test (`test_dataset_hash_is_stable_for_fixed_xy`) pins
the hash to a fixed `(X, y)` pair so any accidental change to the
hashing protocol is caught by CI.

## 6. Save contract

`save_model(model, card, output_dir) -> (model_path, card_path)`:

1. Validate `card` via `validate_model_card`. Fail loud on violation
   before any disk write (atomic semantics: either both files land or
   neither does).
2. Check the working tree is clean: call
   `git status --porcelain` and raise `ValueError` if any line comes
   back. This enforces D6's "reproducible training provenance"
   guarantee — a dirty tree means the committed `training_commit_sha`
   cannot reproduce the artifact.
3. Re-read HEAD via `git rev-parse HEAD`, compare against the
   supplied `training_commit_sha`; raise `ValueError` on mismatch.
4. Derive filenames:
   - `date_token = training_date_utc.replace(":", "-").replace("Z", "Z")`
     (so `2026-05-01T14:30:00Z` → `2026-05-01T14-30-00Z`; safe on
     Windows, macOS, Linux).
   - `sha8 = training_commit_sha[:8]`.
   - `model_path = output_dir / f"{date_token}_{sha8}.joblib"`.
   - `card_path = output_dir / f"{date_token}_{sha8}.json"`.
5. Write the joblib via `joblib.dump(model, model_path)`.
6. Write the card JSON via
   `json.dumps(card, sort_keys=True, ensure_ascii=False, indent=2)`
   then a trailing newline, UTF-8 encoded. `sort_keys=True` makes
   the on-disk byte layout canonical; a determinism test asserts
   that two saves of the same card produce byte-identical JSON.
7. Return `(model_path, card_path)`.

## 7. Load contract

`load_model(model_path, card_path) -> (model, card)`:

1. Read + parse the card JSON.
2. Validate the card via `validate_model_card`.
3. `joblib.load(model_path)` → `model`.
4. Cross-check: `type(model).__name__ == card["model_type"]`. Any
   mismatch raises `ValueError` with both names in the message. This
   catches the common failure of loading a card pointing to a RF
   with a LogReg `.joblib` (or vice versa).
5. Return `(model, card)`.

Both functions are the only public entry points for persistence.
Callers never touch `joblib` or `json` directly.

## 8. Determinism

No new randomness. The only stochastic artefacts in the pipeline
(`RandomForestClassifier`, the stationary bootstrap in 4.5) are
seeded via `APEX_SEED` upstream. Persistence is pure I/O.

The bit-exact round-trip test:

```python
rng = np.random.default_rng(APEX_SEED)
X_fixture = rng.standard_normal((1000, n_features))

model, _ = _train_tiny_rf()
save_model(model, card, tmp_path)
loaded_model, _ = load_model(model_path, card_path)

proba_before = model.predict_proba(X_fixture)
proba_after  = loaded_model.predict_proba(X_fixture)
assert np.array_equal(proba_before, proba_after)  # tolerance 0.0
```

`np.array_equal` (not `np.allclose`) enforces the zero-tolerance
contract.

## 9. Fail-loud inventory

| Trigger | Raised by |
|---|---|
| Card missing a required key, or containing an extra key | `validate_model_card` |
| `schema_version != 1` | `validate_model_card` (explicit v2-rejection test) |
| `training_date_utc` missing `Z` suffix | `validate_model_card` |
| `training_commit_sha` length ≠ 40 or non-hex | `validate_model_card` |
| `gates_passed["aggregate"]` inconsistent with other gates | `validate_model_card` |
| Working tree dirty at `save_model` call | `save_model` |
| `type(model).__name__ != card["model_type"]` at load | `load_model` |
| `model_path.suffix != ".joblib"` | `save_model` / `load_model` |
| `card_path.suffix != ".json"` | `save_model` / `load_model` |

## 10. File-naming grammar

```
{training_date_iso_no_colons}_{commit_sha8}.{joblib,json}
```

- `training_date_iso_no_colons`: the card's `training_date_utc`
  with `:` replaced by `-`. Example: `2026-05-01T14-30-00Z`.
- `commit_sha8`: first 8 hex chars of `training_commit_sha`.

Colons are replaced because Windows filesystems reject `:` in file
names — the project runs on Linux in CI, but this keeps local dev
on Windows unbroken.

## 11. Out of scope (deferred)

- ONNX export (D6 permits it; deferred until a Rust/executable
  consumer appears in Phase 5+).
- Model registry / versioning (Phase 5+).
- Remote artifact storage (S3, GCS). Local filesystem only.
- Digital signatures on the card or model binary (Phase 5+).

## 12. References used (canonical)

- ADR-0002 (Quant Methodology Charter), Section A item 7.
- ADR-0005 (Meta-Labeling and Fusion Methodology), D6.
- PHASE_4_SPEC §3.6.
- López de Prado, M. (2018). *Advances in Financial Machine
  Learning*, Wiley. §7 (reproducibility rationale).
- Joblib: https://joblib.readthedocs.io/en/stable/persistence.html —
  pickle-based sklearn persistence, the reference implementation.
