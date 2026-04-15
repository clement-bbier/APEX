## Phase 4.6 — Meta-Labeler Persistence + Model Card

Closes #130. Implements the model-serialisation + schema-v1 card contract
from ADR-0005 D6 and PHASE_4_SPEC §3.6.

### What this PR delivers

A validated Meta-Labeler (post-Phase-4.5 PASS verdict) can now be
serialised to disk as a `.joblib` binary with a sibling schema-v1 JSON
model card that captures full training provenance, and re-loaded into
a new process with a **bit-exact** `predict_proba` round-trip. The
persistence contract is the deployment gate: any silent drift between
training and inference predictions is a blocker (ADR-0005 D6).

| Concern | Guarantee |
| --- | --- |
| Binary format | `joblib` (sklearn's documented persistence). ONNX deferred — no Phase 4 consumer requires interop. |
| Card format | Canonical JSON, `sort_keys=True`, `ensure_ascii=False`, `indent=2`, trailing newline. Two saves of the same card are byte-identical on disk. |
| Schema version | `schema_version: Literal[1]` in both TypedDict and runtime validator. Bumping to v2 requires an explicit migration. |
| Reproducibility | `save_model` refuses to write unless the git working tree is clean AND `card.training_commit_sha == git HEAD`. |
| Round-trip | `np.array_equal(predict_proba(x_fixture))` on 1000 fixed rows. Tolerance 0.0 — `np.allclose` is explicitly not enough. |
| Filename | `{training_date_iso_no_colons}_{commit_sha8}.{joblib,json}`. Colons replaced with dashes for Windows safety; 8-char SHA suffix disambiguates same-minute trainings. |

### New modules

- `features/meta_labeler/model_card.py` —
  - `ModelCardV1` TypedDict: `schema_version`, `model_type`,
    `hyperparameters`, `training_date_utc`, `training_commit_sha`,
    `training_dataset_hash`, `cpcv_splits_used`, `features_used`,
    `sample_weight_scheme`, `gates_measured`, `gates_passed`,
    `baseline_auc_logreg`, `notes`.
  - `validate_model_card(raw)` — runtime guard used on every load.
    Enforces exact key-set match (rejects extras and omissions),
    `ALLOWED_MODEL_TYPES = {"RandomForestClassifier", "LogisticRegression"}`,
    regex guards for `training_commit_sha` (`^[0-9a-f]{40}$`) and
    `training_dataset_hash` (`^sha256:[0-9a-f]{64}$`), Z-suffix ISO-8601
    on `training_date_utc`, non-empty unique `features_used`, all gate
    booleans strict `bool` (rejects `int`), aggregate cross-check
    (`gates_passed["aggregate"]` must equal AND of per-gate bools),
    `baseline_auc_logreg ∈ [0, 1]`, full JSON round-trip check.
- `features/meta_labeler/persistence.py` —
  - `save_model(model, card, output_dir) -> (model_path, card_path)`.
    Pre-flight: card validation → model isinstance check → clean tree →
    HEAD SHA match → `mkdir` → `joblib.dump` → canonical card write.
  - `load_model(model_path, card_path) -> (model, card)`. Re-runs the
    validator; cross-checks `type(model).__name__` against
    `card["model_type"]` to catch swapped pairs.
  - `compute_dataset_hash(feature_names, X, y) -> "sha256:<64-hex>"`.
    Library-agnostic: consumes, in this exact order,
    `json.dumps(feature_names, sort_keys=True, separators=(",", ":"))`,
    JSON meta `{"shape", "dtype"}` for X, `X.tobytes(order="C")`, JSON
    meta for y, `y.tobytes(order="C")`. Stable across numpy versions.
  - `derive_artifact_stem`, `get_head_commit_sha`,
    `is_working_tree_clean` — small helpers with explicit error
    paths for unit-test spying.
  - `MetaLabelerModel: TypeAlias = RandomForestClassifier | LogisticRegression`
    — the only estimators schema v1 accepts.

### New tests

- `tests/unit/features/meta_labeler/test_model_card.py` (~34 tests)
  - `_valid_card()` fixture + happy-path assertion.
  - Negative branches: wrong `schema_version` (2, `"1"`),
    unknown `model_type`, missing required key, extra key,
    non-ISO / tz-missing / non-Z `training_date_utc`, bad SHA regex,
    bad dataset-hash regex, empty / duplicated / non-string
    `features_used`, non-bool gate value, `aggregate` != AND of
    per-gate bools, out-of-range `baseline_auc_logreg`, non-string
    `notes`, non-JSON-serialisable payload.
  - `test_example_model_card_on_disk_is_valid` loads
    `docs/examples/model_card_v1_example.json` and round-trips it
    through the validator — catches any drift between the example
    and the schema.
- `tests/unit/features/meta_labeler/test_persistence.py` (~22 tests)
  - `git_repo` fixture: throwaway `tmp_path/repo` with `git init`,
    identity config, initial commit; `monkeypatch.chdir` so the
    subprocess calls in `persistence.py` pick it up.
  - `test_load_roundtrip_bit_exact_predictions` — the ADR-0005 D6
    deployment gate. 1000 fixed `x_fixture` rows, `np.array_equal`,
    tolerance 0.0.
  - Rejection cases: dirty working tree, HEAD SHA / card SHA
    mismatch, wrong `model_path` extension, wrong `card_path`
    extension, unsupported estimator type, model / card type
    disagreement, invalid JSON on disk, bad card schema.
  - Determinism: two saves of the same card produce byte-identical
    JSON on disk.
  - Hash protocol: permuting `feature_names` changes the hash;
    `X` and `y` bytes contribute independently; `C`-order
    canonicalisation defeats stride-order aliasing.

### Supporting artefacts

- `reports/phase_4_6/audit.md` — pre-implementation design contract
  (12 sections: objective, deliverables, reuse inventory, schema-v1
  rules, dataset-hash protocol, save/load contract, determinism
  requirements, fail-loud inventory, file-naming grammar,
  out-of-scope, references). Mirrors the style of
  `reports/phase_4_5/audit.md`.
- `docs/examples/model_card_v1_example.json` — canonical reference
  card, all keys sorted alphabetically, every gate PASS +
  aggregate PASS, 8 canonical Phase-4.3 `FEATURE_NAMES`.
- `scripts/generate_phase_4_6_report.py` — env-var-driven demo
  mirroring the 4.4 / 4.5 contract (`APEX_SEED`, `APEX_REPORT_NOW`,
  `APEX_REPORT_WALLCLOCK_MODE`). Reads
  `reports/phase_4_5/validation_report.json` when present (else
  synthesises defaults), trains a small RF on the same synthetic
  alpha as 4.3, saves, reloads, verifies bit-exact round-trip,
  emits `reports/phase_4_6/persistence_report.{md,json}`.
- `.gitignore` — excludes `models/meta_labeler/*.{joblib,json}`.
  Trained weights are artefacts, not source.
- `pyproject.toml` — adds `"joblib.*"` to the mypy
  `ignore_missing_imports` overrides (joblib ships no type stubs).

### Fail-loud inventory

Every caller-facing error path raises a typed exception with a
message that points at the fix:

| Condition | Exception |
| --- | --- |
| Unsupported estimator passed to `save_model` | `TypeError` |
| `card.model_type != type(model).__name__` | `ValueError` |
| Dirty working tree at save | `ValueError` |
| `card.training_commit_sha != HEAD` | `ValueError` |
| Invalid card schema (any of ~20 checks) | `ValueError` |
| Wrong file extension on load | `ValueError` |
| Non-JSON card file | `ValueError` |
| Loaded estimator type not in allowed set | `ValueError` |
| git unavailable / not a repo | `RuntimeError` |

### How to verify locally

```bash
make lint
pytest tests/unit/features/meta_labeler/test_model_card.py -q
pytest tests/unit/features/meta_labeler/test_persistence.py -q

# End-to-end demo (needs a clean working tree):
APEX_SEED=42 \
  APEX_REPORT_NOW=2026-04-15T00:00:00+00:00 \
  APEX_REPORT_WALLCLOCK_MODE=omit \
  python3 scripts/generate_phase_4_6_report.py
```

### References

- ADR-0005 (Meta-Labeling and Fusion Methodology), D6 — Persistence
  format, round-trip gate, card schema.
- PHASE_4_SPEC §3.6 — Persistence + Model Card.
- López de Prado, M. (2018). *Advances in Financial Machine
  Learning*, Wiley. §7 (baseline for the 4.3–4.5 contract that this
  PR now packages for deployment).
